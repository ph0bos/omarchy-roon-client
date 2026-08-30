"""Announce each track on the pinned zone.

The record goes on screen as playback moves on -- sleeve, title, and
artist · album -- through the desktop's own notification daemon, so it looks
like everything else that talks to you. Each notification *replaces* the
previous one rather than stacking a card per song.

Three things this has to get right, all of them learned from how annoying the
naive version is:

* **Never announce the first update.** A daemon restart would otherwise pop a
  notification for whatever happened to be playing, which reads as a bug.
* **Only on an actual track change, and only while playing.** Pausing, seeking,
  a volume nudge and the 1Hz seek tick must all stay silent, or the notification
  becomes noise and gets muted.
* **Art has to be a local file.** Notification daemons do not fetch `http://`
  for `image-path`, so the sleeve is cached to disk first and the notification
  goes out without art rather than late if that fails.
"""
from __future__ import annotations

import hashlib
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

BUS = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
IFACE = "org.freedesktop.Notifications"

ART_PX = 128
TIMEOUT_MS = 5000

# Sleeves accumulate one file per album ever played. At 128px they are a few
# kilobytes each, so this is about not leaving unbounded litter in a cache
# directory rather than about reclaiming space.
ART_CACHE_MAX_FILES = 300


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "omarchy-roon" / "art"


class Notifier:
    def __init__(self, session, enabled: bool = True):
        self.session = session
        self.enabled = enabled
        # Transient, never persisted: set while a surface that already shows the
        # track is on screen. A notification card telling you what is playing,
        # drawn on top of the player showing you what is playing, is pure noise.
        self.suppressed = False
        self.error: str | None = None
        self._conn = None
        self._glib = None
        self._last_id = 0
        self._last_key: tuple | None = None
        self._primed = False
        self._lock = threading.Lock()
        self._cache = _cache_dir()

    def start(self) -> bool:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as e:
            self.error = f"notifications unavailable: {e}"
            return False
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:                                   # noqa: BLE001
            self.error = f"no session bus: {e}"
            return False
        self._glib = GLib
        return True

    # -- artwork ---------------------------------------------------------
    def _art_path(self, image_key: str) -> str:
        """Cache the sleeve to disk; notification daemons will not fetch URLs."""
        if not image_key or not self.session.core:
            return ""
        name = hashlib.sha1(f"{image_key}:{ART_PX}".encode()).hexdigest()
        path = self._cache / f"{name}.jpg"
        if path.exists():
            return str(path)
        try:
            url = self.session.image_url(image_key, ART_PX, ART_PX)
            self._cache.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=4) as r:
                data = r.read()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            self._prune_cache()
            return str(path)
        except (urllib.error.URLError, OSError, ValueError):
            # No art beats a late notification.
            return ""

    def _prune_cache(self) -> None:
        """Keep the sleeve cache bounded, oldest first."""
        try:
            files = sorted(self._cache.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return
        for stale in files[:-ART_CACHE_MAX_FILES]:
            try:
                stale.unlink()
            except OSError:
                pass

    # -- announcing ------------------------------------------------------
    def on_zones(self, _touched=None) -> None:
        if not (self.enabled and self._conn):
            return
        if self.suppressed:
            # Still fall through to the bookkeeping below so that closing the
            # panel does not then announce a track that changed while it was
            # open -- the user watched that change happen.
            zone = self.session.pinned_zone()
            if zone is not None:
                track = zone["track"]
                with self._lock:
                    self._primed = True
                    self._last_key = (zone["zone_id"], track["title"],
                                      track["artist"], track["album"])
            return
        zone = self.session.pinned_zone()
        if zone is None:
            return

        track = zone["track"]
        key = (zone["zone_id"], track["title"], track["artist"], track["album"])

        with self._lock:
            first = not self._primed
            self._primed = True
            if key == self._last_key:
                return                      # seek tick, pause, volume: silent
            self._last_key = key
            if first:
                return                      # never announce on startup
            if zone["state"] != "playing" or not track["title"]:
                return

        self._announce(zone, track)

    def _announce(self, zone, track) -> None:
        GLib = self._glib
        body = " · ".join(p for p in (track["artist"], track["album"]) if p)
        hints = {
            "urgency": GLib.Variant("y", 0),
            "category": GLib.Variant("s", "x-roon.track"),
            # Distinguishes rooms when several zones are announcing.
            "x-roon-zone": GLib.Variant("s", zone["name"]),
        }
        art = self._art_path(track["image_key"])
        if art:
            hints["image-path"] = GLib.Variant("s", art)

        args = GLib.Variant("(susssasa{sv}i)", (
            "Roon",
            self._last_id,          # replaces the previous card rather than stacking
            art,
            track["title"],
            body,
            [],
            hints,
            TIMEOUT_MS,
        ))
        try:
            reply = self._conn.call_sync(BUS, PATH, IFACE, "Notify", args,
                                         GLib.VariantType("(u)"),
                                         0, 3000, None)
            self._last_id = reply.unpack()[0]
        except Exception:                                        # noqa: BLE001
            # A missing or unhappy notification daemon must never take the
            # Roon read loop down with it.
            pass
