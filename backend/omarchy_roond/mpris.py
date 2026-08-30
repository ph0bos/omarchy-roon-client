"""MPRIS for the pinned Roon zone.

This is the cheapest surface in the whole project. Omarchy 4 already ships
`omarchy.media` -- a generic MPRIS bar widget with now-playing and transport --
and the shell already routes media keys and the OSD through MPRIS. So publishing
one MPRIS player gives the endpoint a bar presence, working media keys and a
volume OSD without a line of QML.

The mapping is not quite free, and the seams are worth naming:

* **MPRIS is one player; Roon is many zones.** The pinned zone stands in for
  "this machine's music". There is no MPRIS vocabulary for rooms, so the widget
  cannot name the zone or switch it -- that is what a dedicated bar widget would
  add later, if it ever earns its place.
* **Roon has no track ids.** `mpris:trackid` must be an object path and must
  change when the track does, or clients will not notice a new song. We
  synthesise one from a counter keyed on the title/artist/album triple.
* **Art comes from the Core**, as a plain HTTP URL, which is exactly what
  `mpris:artUrl` wants. No proxying, no temp files.
* **Position is polled by clients but pushed by Roon at ~1Hz.** Interpolating
  from a monotonic anchor between ticks is what makes a progress bar move
  smoothly instead of stepping once a second.

Needs PyGObject, which is already a pacman package and already present wherever
the TIDAL backend runs. Absent, `start()` reports why and the daemon carries on
without a bar presence rather than refusing to run.
"""
from __future__ import annotations

import threading
import time

BUS_NAME = "org.mpris.MediaPlayer2.omarchy_roon"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

INTROSPECTION = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" type="x" name="Offset"/></method>
    <method name="SetPosition">
      <arg direction="in" type="o" name="TrackId"/>
      <arg direction="in" type="x" name="Position"/>
    </method>
    <method name="OpenUri"><arg direction="in" type="s" name="Uri"/></method>
    <signal name="Seeked"><arg type="x" name="Position"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""

LOOP_TO_MPRIS = {"disabled": "None", "loop": "Playlist", "loop_one": "Track"}
LOOP_FROM_MPRIS = {v: k for k, v in LOOP_TO_MPRIS.items()}


class MprisPlayer:
    def __init__(self, session):
        self.session = session
        self.error: str | None = None
        self._conn = None
        self._loop = None
        self._thread = None
        self._reg_ids: list[int] = []
        self._name_id = 0

        # Position interpolation: Roon pushes a seek tick about once a second,
        # and clients poll Position whenever they like. Anchoring on a monotonic
        # clock keeps a progress bar smooth without ever drifting, because the
        # answer is always derived rather than accumulated.
        self._anchor_pos = 0.0
        self._anchor_at = time.monotonic()
        self._anchor_playing = False

        self._track_serial = 0
        self._track_key: tuple | None = None
        self._last: dict = {}

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as e:
            self.error = f"MPRIS unavailable: {e} (install python-gobject)"
            return False

        self._gio, self._glib = Gio, GLib
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:                          # noqa: BLE001
            self.error = f"no session bus: {e}"
            return False

        # PyGObject's vtable callbacks take (conn, sender, path, iface, prop)
        # for get and one more for set. Unlike the C API there is no trailing
        # GError, and an arity mismatch fails silently per property: the bus name
        # is claimed, introspection looks right, and every read returns
        # "Unable to retrieve property".
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        for iface in node.interfaces:
            self._reg_ids.append(self._conn.register_object(
                OBJECT_PATH, iface, self._on_method, self._on_get, self._on_set))

        self._name_id = Gio.bus_own_name_on_connection(
            self._conn, BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)

        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, daemon=True)
        self._thread.start()

        self.session.on_pinned_changed = lambda _zid: self.publish(force=True)
        return True

    def stop(self) -> None:
        if self._conn:
            for rid in self._reg_ids:
                self._conn.unregister_object(rid)
            if self._name_id:
                self._gio.bus_unown_name(self._name_id)
        if self._loop:
            self._loop.quit()

    # -- state -----------------------------------------------------------
    def _zone(self):
        return self.session.pinned_zone()

    def _metadata(self, zone) -> dict:
        GLib = self._glib
        if not zone:
            return {"mpris:trackid": GLib.Variant("o", "/org/omarchy/roon/none")}

        track = zone["track"]
        key = (track["title"], track["artist"], track["album"])
        if key != self._track_key:
            self._track_key = key
            self._track_serial += 1

        meta = {
            "mpris:trackid": GLib.Variant(
                "o", f"/org/omarchy/roon/track/{self._track_serial}"),
            "mpris:length": GLib.Variant("x", int(track["length"] * 1_000_000)),
            "xesam:title": GLib.Variant("s", track["title"]),
            "xesam:artist": GLib.Variant("as", [track["artist"]] if track["artist"] else []),
            "xesam:album": GLib.Variant("s", track["album"]),
        }
        if track["image_key"] and self.session.core:
            meta["mpris:artUrl"] = GLib.Variant(
                "s", self.session.image_url(track["image_key"], 600, 600))
        return meta

    def _position_us(self, zone) -> int:
        if not zone:
            return 0
        elapsed = (time.monotonic() - self._anchor_at) if self._anchor_playing else 0.0
        pos = self._anchor_pos + elapsed
        length = zone["track"]["length"]
        if length:
            pos = min(pos, length)
        return max(0, int(pos * 1_000_000))

    def _volume(self, zone) -> float:
        """MPRIS volume is 0.0-1.0; Roon's is per-output with its own bounds.

        Mapped through the same clamp the UI uses, so a soft-limited zone reports
        1.0 at its ceiling rather than at a level the Core would refuse.
        """
        if not zone:
            return 0.0
        for out in zone["outputs"]:
            if out["bounds"] and out["volume"]:
                low, high = out["bounds"]
                if high > low:
                    # `or low` would be wrong: a dB control sits at 0 when it is
                    # at FULL volume, and 0 is falsy, so the default would fire
                    # on the one value that means "loudest" and report silence.
                    raw = out["volume"].get("value")
                    value = float(low if raw is None else raw)
                    return max(0.0, min(1.0, (value - low) / (high - low)))
        return 0.0

    def _properties(self) -> dict:
        zone = self._zone()
        state = (zone or {}).get("state", "stopped")
        can = (zone or {}).get("can", {})
        settings = (zone or {}).get("settings", {})
        return {
            "PlaybackStatus": ("Playing" if state == "playing"
                               else "Paused" if state == "paused" else "Stopped"),
            "LoopStatus": LOOP_TO_MPRIS.get(settings.get("loop", "disabled"), "None"),
            "Shuffle": bool(settings.get("shuffle")),
            "Metadata": self._metadata(zone),
            "Volume": self._volume(zone),
            "Rate": 1.0,
            "MinimumRate": 1.0,
            "MaximumRate": 1.0,
            "CanGoNext": bool(can.get("next")),
            "CanGoPrevious": bool(can.get("previous")),
            "CanPlay": bool(can.get("play")),
            "CanPause": bool(can.get("pause")),
            "CanSeek": bool(can.get("seek")),
            "CanControl": zone is not None,
        }

    # -- publishing ------------------------------------------------------
    def publish(self, force: bool = False) -> None:
        """Emit PropertiesChanged for whatever actually changed."""
        if not self._conn:
            return
        zone = self._zone()

        if zone:
            playing = zone["state"] == "playing"
            pos = zone["track"]["seek_position"]
            # Re-anchor on every push: the tick is the truth, interpolation only
            # fills the gaps between ticks.
            self._anchor_pos = float(pos)
            self._anchor_at = time.monotonic()
            self._anchor_playing = playing

        props = self._properties()
        changed = props if force else {
            k: v for k, v in props.items()
            if k not in self._last or self._repr(self._last[k]) != self._repr(v)
        }
        self._last = props
        if not changed:
            return

        GLib = self._glib
        body = GLib.Variant("(sa{sv}as)", (
            PLAYER_IFACE,
            {k: self._variant(k, v) for k, v in changed.items()},
            [],
        ))
        try:
            self._conn.emit_signal(None, OBJECT_PATH,
                                   "org.freedesktop.DBus.Properties",
                                   "PropertiesChanged", body)
        except Exception:                               # noqa: BLE001
            pass

    @staticmethod
    def _repr(value):
        if isinstance(value, dict):
            return {k: str(v) for k, v in value.items()}
        return value

    def _variant(self, name: str, value):
        GLib = self._glib
        if name == "Metadata":
            return GLib.Variant("a{sv}", value)
        if isinstance(value, bool):
            return GLib.Variant("b", value)
        if isinstance(value, float):
            return GLib.Variant("d", value)
        if isinstance(value, int):
            return GLib.Variant("x", value)
        return GLib.Variant("s", str(value))

    # -- D-Bus callbacks -------------------------------------------------
    def _on_get(self, _conn, _sender, _path, iface, name):
        GLib = self._glib
        if iface == ROOT_IFACE:
            zone = self._zone()
            root = {
                "CanQuit": GLib.Variant("b", False),
                # Nothing to raise in R1: the endpoint has no window. When the
                # standalone client exists this becomes true and Raise focuses it.
                "CanRaise": GLib.Variant("b", False),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant(
                    "s", f"Roon — {zone['name']}" if zone else "Roon"),
                "DesktopEntry": GLib.Variant("s", "omarchy-roon"),
                "SupportedUriSchemes": GLib.Variant("as", []),
                "SupportedMimeTypes": GLib.Variant("as", []),
            }
            return root.get(name)

        if iface == PLAYER_IFACE:
            if name == "Position":
                return GLib.Variant("x", self._position_us(self._zone()))
            props = self._properties()
            if name in props:
                return self._variant(name, props[name])
        return None

    def _on_set(self, _conn, _sender, _path, iface, name, value):
        if iface != PLAYER_IFACE:
            return False
        zone = self._zone()
        if not zone:
            return False
        try:
            if name == "Volume":
                for out in zone["outputs"]:
                    if out["bounds"]:
                        low, high = out["bounds"]
                        target = low + max(0.0, min(1.0, value.get_double())) * (high - low)
                        self.session.change_volume(out["output_id"], target)
                        return True
                return False
            if name == "Shuffle":
                self.session.change_settings(zone["zone_id"], shuffle=value.get_boolean())
                return True
            if name == "LoopStatus":
                loop = LOOP_FROM_MPRIS.get(value.get_string())
                if loop:
                    self.session.change_settings(zone["zone_id"], loop=loop)
                    return True
        except Exception:                               # noqa: BLE001
            return False
        return False

    def _on_method(self, _conn, _sender, _path, iface, method, params, invocation):
        zone = self._zone()
        try:
            if iface == ROOT_IFACE:
                invocation.return_value(None)
                return
            if zone is None:
                invocation.return_value(None)
                return

            zid = zone["zone_id"]
            simple = {"Play": "play", "Pause": "pause", "PlayPause": "playpause",
                      "Stop": "stop", "Next": "next", "Previous": "previous"}
            if method in simple:
                self.session.control(zid, simple[method])
            elif method == "Seek":
                self.session.seek(zid, params.unpack()[0] / 1_000_000, "relative")
            elif method == "SetPosition":
                self.session.seek(zid, params.unpack()[1] / 1_000_000, "absolute")
            invocation.return_value(None)
        except Exception:                               # noqa: BLE001
            # A failed transport call must not take the bus connection down; the
            # next zone push will correct whatever the client now believes.
            invocation.return_value(None)
        finally:
            self.publish()
