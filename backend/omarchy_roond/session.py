"""RoonSession -- the whole Roon-facing surface, behind one narrow seam.

Everything above this module deals in zones, tracks and browse lists. Everything
below is MOO frames. Keeping that boundary narrow is what makes the daemon
testable: a fake session that replays captured fixtures satisfies the same five
verbs a real one does.

    connect()     find a Core, register, subscribe
    control()     transport verbs
    browse()      the browse tree
    load()        a page of it
    queue()       the pinned zone's queue, kept live
    run_forever() reconnect until told to stop

Three protocol facts the shape here exists to respect, all learned against a live
Core rather than from the documentation:

* Registration answers `CONTINUE Registered` and the request stays open, so it is
  never a one-shot call that can be awaited and forgotten.
* Subscriptions answer `Subscribed`, not `Success`.
* Zone payloads are fragmented across WebSocket frames. `moo.Moo` reassembles
  them; a reader that does not will serve browse perfectly while silently losing
  every zone update, which looks like a transport bug rather than a framing one.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import discovery, palette
from .endpoint import OutputFormat
from .moo import Moo, MooError
from .queue import QueueStore
from .zones import ZoneStore


class AwaitingApproval(MooError):
    """The Core has not been told to trust this extension yet.

    Distinct from every other connection failure because the fix is not on this
    machine: someone has to open Roon on a phone or another computer, since Roon
    ships no GUI for Linux.
    """


# Sleeve analyses are a few dozen bytes each; the cap exists to bound a
# long-running daemon rather than to save meaningful memory.
PALETTE_CACHE_MAX = 256

TRANSPORT = "com.roonlabs.transport:2"
BROWSE = "com.roonlabs.browse:1"
IMAGE = "com.roonlabs.image:1"

# Subscription keys are ours to choose; they only have to be distinct, because
# every message from a subscription carries the key it belongs to.
ZONES_SUBSCRIPTION_KEY = 1
QUEUE_SUBSCRIPTION_KEY = 2

# Deep enough that scrolling the queue never waits on the Core, shallow enough
# that a 10,000-track playlist does not arrive as one message.
QUEUE_MAX_ITEMS = 100

REGINFO = {
    "extension_id": "org.omarchy.roon",
    "display_name": "Roon for Omarchy",
    "display_version": "0.2.1",
    "publisher": "ph0bos",
    "email": "noreply@omarchy.local",
    "website": "https://github.com/ph0bos/omarchy-roon-client",
    "required_services": [TRANSPORT, BROWSE, IMAGE],
    "optional_services": [],
    "provided_services": [],
}


def _data_dir() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "omarchy-roon"


def _token_path() -> Path:
    return _data_dir() / "tokens.json"


def _config_path() -> Path:
    return _data_dir() / "config.json"


class TokenStore:
    """Pairing tokens, one per Core, keyed by core_id.

    A token is what makes reconnection silent: without it every daemon restart
    would ask the user to approve the extension again, and `Restart=always` would
    be unusable.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or _token_path()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, core_id: str) -> str | None:
        return self._read().get(core_id)

    def put(self, core_id: str, token: str) -> None:
        tokens = self._read()
        tokens[core_id] = token
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens, indent=2))
        self.path.chmod(0o600)


class RoonSession:
    def __init__(self, host: str | None = None, port: int | None = None,
                 tokens: TokenStore | None = None):
        self.host, self.port = host, port
        self.tokens = tokens or TokenStore()
        self.zones = ZoneStore()
        self.queue = QueueStore()
        self._palettes: dict[str, dict] = {}
        self._output = OutputFormat()
        self.core: discovery.Core | None = None
        self.core_id: str | None = None
        self.connected = False
        # Why we are not connected, kept rather than only announced. The
        # callbacks fire once, at the moment it happens; a surface that opens
        # afterwards has to be able to ask. `awaiting_approval` is separate from
        # `last_error` because it is not an error -- nothing is broken, someone
        # simply has to say yes somewhere else.
        self.awaiting_approval: str | None = None
        self.last_error: str = ""
        self._config_path = _config_path()
        _config = self._load_config()
        self._pinned_zone_id: str | None = _config.get("pinned_zone_id")
        self.notifications: bool = bool(_config.get("notifications", True))

        # Callbacks, all optional; the daemon and the CLI use the same ones.
        self.on_zones: Callable[[set[str]], None] | None = None
        self.on_connected: Callable[[dict], None] | None = None
        self.on_disconnected: Callable[[str], None] | None = None
        self.on_awaiting_approval: Callable[[str], None] | None = None
        self.on_pinned_changed: Callable[[str | None], None] | None = None
        self.on_queue: Callable[[str | None], None] | None = None

        self._moo: Moo | None = None
        self._send_lock = threading.Lock()
        self._pending: dict[int, list] = {}      # reqid -> [Event, Message|None]
        self._streams: dict[int, Callable] = {}  # reqid -> handler
        self._queue_reqid: int | None = None
        self._queue_zone_id: str | None = None
        self._stop = threading.Event()

    # -- the pinned zone -------------------------------------------------
    #
    # Roon is inherently multi-zone; MPRIS is one player with one track. So one
    # zone has to stand for "this machine's music", and everything single-valued
    # -- the MPRIS interface, the media keys, the bar widget -- follows it.
    #
    # The default is the zone this machine is itself playing to, because that is
    # what a user pressing pause on this keyboard almost always means. Following
    # whichever zone happens to be playing instead would make the bar widget
    # change rooms under you when someone elsewhere in the house hits play.

    def _load_config(self) -> dict:
        try:
            return json.loads(self._config_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save_config(self, **changes) -> None:
        config = self._load_config()
        config.update(changes)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(config, indent=2))

    def local_zone_id(self) -> str | None:
        """The zone this machine plays to, found by matching the hostname.

        RoonBridge names its outputs after the host, so the local zone is the one
        whose zone or output display name contains it. Best-effort by design: a
        renamed zone in Roon simply falls through to the explicit pin.
        """
        host = socket.gethostname().split(".")[0].lower()
        if not host:
            return None
        for zone in self.zones.all():
            names = [zone.get("display_name") or ""]
            names += [o.get("display_name") or "" for o in zone.get("outputs") or []]
            if any(host in n.lower() for n in names):
                return zone["zone_id"]
        return None

    @property
    def pinned_zone_id(self) -> str | None:
        """The pin if it still exists, else the local zone, else the first zone."""
        if self._pinned_zone_id and self._pinned_zone_id in self.zones:
            return self._pinned_zone_id
        local = self.local_zone_id()
        if local:
            return local
        zones = self.zones.all()
        return zones[0]["zone_id"] if zones else None

    def pinned_zone(self) -> dict | None:
        zone_id = self.pinned_zone_id
        return self.zones.summary(zone_id) if zone_id else None

    def set_notifications(self, enabled: bool) -> None:
        self.notifications = bool(enabled)
        self._save_config(notifications=self.notifications)

    def pin(self, zone_id: str | None) -> None:
        self._pinned_zone_id = zone_id
        self._save_config(pinned_zone_id=zone_id)
        # The queue follows the pin, and only the pin: this is the one moment it
        # is allowed to cost a round trip.
        self._ensure_queue_subscription()
        if self.on_pinned_changed:
            self.on_pinned_changed(zone_id)

    # -- requests --------------------------------------------------------
    def _request(self, name: str, body: dict | None = None,
                 stream: Callable | None = None) -> int:
        if self._moo is None:
            raise MooError("not connected")
        with self._send_lock:
            reqid = self._moo.request(name, body)
            if stream is not None:
                self._streams[reqid] = stream
        return reqid

    def call(self, name: str, body: dict | None = None, timeout: float = 10.0):
        """Send a request and wait for its reply. Safe from any thread."""
        done = threading.Event()
        slot: list = [done, None]
        if self._moo is None:
            raise MooError("not connected")
        with self._send_lock:
            reqid = self._moo.request(name, body)
            self._pending[reqid] = slot
        if not done.wait(timeout):
            self._pending.pop(reqid, None)
            raise MooError(f"timed out waiting for {name}")
        msg = slot[1]
        if msg is None:
            raise MooError(f"connection lost during {name}")
        return msg

    # -- transport -------------------------------------------------------
    def control(self, zone_id: str, action: str):
        """action: play | pause | playpause | stop | previous | next"""
        return self.call(f"{TRANSPORT}/control",
                         {"zone_or_output_id": zone_id, "control": action})

    def seek(self, zone_id: str, seconds: float, how: str = "absolute"):
        return self.call(f"{TRANSPORT}/seek",
                         {"zone_or_output_id": zone_id, "how": how, "seconds": seconds})

    def change_volume(self, output_id: str, value: float, how: str = "absolute"):
        return self.call(f"{TRANSPORT}/change_volume",
                         {"output_id": output_id, "how": how, "value": value})

    def mute(self, output_id: str, muted: bool):
        """Mute or unmute one output.

        Roon's own call rather than driving the volume to zero: muting is
        reversible to the previous level and survives a volume change, which
        setting the fader to 0 is not.
        """
        return self.call(f"{TRANSPORT}/mute",
                         {"output_id": output_id,
                          "how": "mute" if muted else "unmute"})

    def change_settings(self, zone_id: str, **settings):
        return self.call(f"{TRANSPORT}/change_settings",
                         {"zone_or_output_id": zone_id, **settings})

    def play_from_here(self, zone_id: str, queue_item_id) -> object:
        """Jump to an item already in the queue, keeping everything after it.

        The only way to start playback from a queue entry: there is no "play
        item n". `queue_item_id` is the Core's own handle and the position of an
        item is not usable in its place -- the list edits underneath it.
        """
        return self.call(f"{TRANSPORT}/play_from_here",
                         {"zone_or_output_id": zone_id,
                          "queue_item_id": queue_item_id})

    # -- the queue subscription ------------------------------------------
    #
    # One subscription, following the pinned zone, re-subscribed only when the
    # pin moves. Everything here is fire-and-forget rather than `call()`,
    # because `_ensure_queue_subscription` runs on the read loop's own thread:
    # waiting there for a reply the same thread has to read is a deadlock.

    def subscribe_queue(self, zone_id: str,
                        max_item_count: int = QUEUE_MAX_ITEMS) -> None:
        if self._queue_reqid is not None:
            self.unsubscribe_queue()
        self.queue.reset(zone_id)
        self._queue_zone_id = zone_id
        self._queue_reqid = self._request(
            f"{TRANSPORT}/subscribe_queue",
            {"subscription_key": QUEUE_SUBSCRIPTION_KEY,
             "zone_or_output_id": zone_id,
             "max_item_count": max_item_count},
            stream=self._on_queue_message)

    def unsubscribe_queue(self) -> None:
        reqid, self._queue_reqid = self._queue_reqid, None
        self._queue_zone_id = None
        self.queue.reset(None)
        if reqid is None:
            return
        self._streams.pop(reqid, None)
        try:
            self._request(f"{TRANSPORT}/unsubscribe_queue",
                          {"subscription_key": QUEUE_SUBSCRIPTION_KEY})
        except MooError:
            pass          # the connection is gone; there is nothing to leave

    def _ensure_queue_subscription(self) -> None:
        """Point the queue at whichever zone is pinned now. Cheap when unchanged."""
        if not self.connected:
            return
        zone_id = self.pinned_zone_id
        if zone_id == self._queue_zone_id:
            return
        if zone_id is None:
            self.unsubscribe_queue()
        else:
            self.subscribe_queue(zone_id)

    def _on_queue_message(self, msg) -> None:
        changed = self.queue.apply(msg.name, msg.body)
        if self.queue.stale:
            # An edit we do not understand means our copy no longer matches the
            # Core's. Re-subscribing is the only honest repair, and it costs one
            # round trip per unknown operation rather than a permanent lie.
            zone_id = self._queue_zone_id
            if zone_id:
                self.subscribe_queue(zone_id)
            return
        if changed and self.on_queue:
            self.on_queue(self._queue_zone_id)

    # -- browse ----------------------------------------------------------
    def browse(self, hierarchy: str = "browse", **opts):
        return self.call(f"{BROWSE}/browse", {"hierarchy": hierarchy, **opts})

    def load(self, hierarchy: str = "browse", offset: int = 0, count: int = 100, **opts):
        return self.call(f"{BROWSE}/load",
                         {"hierarchy": hierarchy, "offset": offset, "count": count, **opts})

    def output_format(self) -> dict | None:
        """The format this machine's own endpoint is playing, or None.

        Only meaningful when the pinned zone IS this machine: another room is
        played by hardware we know nothing about, and reporting our numbers for
        it would be a confident lie.
        """
        local = self.local_zone_id()
        if not local or local != self.pinned_zone_id:
            return None
        return self._output.read()

    def art_palette(self, image_key: str) -> dict | None:
        """Mean luminance and a representative colour for a sleeve.

        Two problems share this answer: text over a blurred cover is unreadable
        when the cover is bright, and a spectrum analyser drawn in the theme's
        accent ignores the record it sits beside. Both want to know how light the
        artwork is and what colour it is.

        Cached by key because it is asked for on every track change, from more
        than one surface, and a 16x16 decode is still a decode.
        """
        if not image_key or not self.core:
            return None
        if image_key in self._palettes:
            return self._palettes[image_key]
        try:
            # 128px is plenty: the analysis samples down to 16x16 anyway, and a
            # smaller fetch keeps track changes instant.
            with urllib.request.urlopen(self.image_url(image_key, 128, 128),
                                        timeout=4) as r:
                data = r.read()
        except (urllib.error.URLError, OSError, ValueError):
            return None
        result = palette.analyse(data)
        if result is not None:
            # Evict the oldest rather than clearing the lot: dropping every
            # entry means the next few track changes all re-fetch and re-decode,
            # which is a stall exactly when the interface is busiest.
            while len(self._palettes) >= PALETTE_CACHE_MAX:
                self._palettes.pop(next(iter(self._palettes)))
            self._palettes[image_key] = result
        return result

    def image_url(self, image_key: str, width: int = 0, height: int = 0,
                  scale: str = "fit") -> str:
        """A URL QML can hand straight to `Image`.

        The Core serves art itself, so nothing needs to proxy it and Qt's own
        image cache does the work.
        """
        base = f"http://{self.core.ip}:{self.core.http_port}/api/image/{image_key}"
        if width and height:
            return f"{base}?scale={scale}&width={width}&height={height}&format=image/jpeg"
        return base

    # -- connection ------------------------------------------------------
    def _find_core(self) -> discovery.Core | None:
        if self.host and self.port:
            found = discovery.probe(self.host)
            if found:
                return found
            return discovery.Core(self.host, {"http_port": str(self.port),
                                              "name": self.host})
        cores = discovery.discover(host=self.host)
        return cores[0] if cores else None

    def connect(self) -> bool:
        core = self._find_core()
        if core is None or not core.http_port:
            return False
        self.core = core

        self._moo = Moo(core.ip, core.http_port, timeout=5.0)
        self._moo.request("com.roonlabs.registry:1/info")
        info = self._moo.read()
        self.core_id = (info.body or {}).get("core_id")

        reginfo = dict(REGINFO)
        token = self.tokens.get(self.core_id) if self.core_id else None
        if token:
            reginfo["token"] = token
        self._moo.request("com.roonlabs.registry:1/register", reginfo)
        try:
            reg = self._moo.read()
        except (TimeoutError, OSError) as e:
            if isinstance(e, MooError):
                raise
            # Registration does not fail when unapproved -- it simply never
            # answers. Without a stored token that silence IS the approval gate,
            # and reporting it as a connection error sends the user hunting for a
            # network problem instead of opening Roon on their phone.
            raise AwaitingApproval(
                "waiting for approval in Roon Settings > Extensions"
                f" (as {REGINFO['display_name']})") from None
        if reg.name != "Registered":
            raise MooError(f"registration refused: {reg}")

        body = reg.body or {}
        if body.get("token") and body.get("core_id"):
            self.tokens.put(body["core_id"], body["token"])

        self._request(f"{TRANSPORT}/subscribe_zones",
                      {"subscription_key": ZONES_SUBSCRIPTION_KEY},
                      stream=self._on_zone_message)
        self.connected = True
        self.awaiting_approval = None
        self.last_error = ""
        if self.on_connected:
            self.on_connected(body)
        return True

    def _on_zone_message(self, msg) -> None:
        touched = self.zones.apply(msg.name, msg.body)
        # The pinned zone is only knowable once zones have arrived, so this is
        # also where the first queue subscription is made.
        if touched:
            self._ensure_queue_subscription()
        if touched and self.on_zones:
            self.on_zones(touched)

    def _pump(self) -> None:
        """Read until the connection dies. Runs on the caller's thread."""
        while not self._stop.is_set():
            try:
                msg = self._moo.read()
            except (TimeoutError, OSError) as e:
                if isinstance(e, MooError):
                    raise
                continue                      # read timeout; the socket is fine
            except MooError:
                raise

            reqid = msg.request_id
            slot = self._pending.pop(reqid, None) if reqid is not None else None
            if slot is not None:
                slot[1] = msg
                slot[0].set()
                continue
            handler = self._streams.get(reqid)
            if handler is not None:
                handler(msg)

    def close(self) -> None:
        self.connected = False
        if self._moo is not None:
            self._moo.close()
            self._moo = None
        for slot in list(self._pending.values()):
            slot[0].set()
        self._pending.clear()
        self._streams.clear()
        # Forget the subscription rather than the queue's contents: the
        # interface keeps rendering the last known list while reconnecting, and
        # the first zone message afterwards subscribes again.
        self._queue_reqid = None
        self._queue_zone_id = None

    def stop(self) -> None:
        self._stop.set()
        self.close()

    def run_forever(self, min_backoff: float = 1.0, max_backoff: float = 30.0) -> None:
        """Stay connected. A Core rebooting should look like a pause, not a crash."""
        backoff = min_backoff
        while not self._stop.is_set():
            try:
                if self.connect():
                    backoff = min_backoff
                    self._pump()
                else:
                    raise MooError("no Core found")
            except AwaitingApproval as e:
                self.awaiting_approval = str(e)
                if self.on_awaiting_approval:
                    self.on_awaiting_approval(str(e))
                self.connected = False
                self.close()
                self._stop.wait(3.0)      # poll briskly: a human is acting now
                continue
            except (MooError, OSError) as e:
                reason = str(e) or e.__class__.__name__
                self.last_error = reason
                if self.connected and self.on_disconnected:
                    self.on_disconnected(reason)
                self.connected = False
                self.close()
                if self._stop.is_set():
                    return
                self._stop.wait(backoff)
                backoff = min(backoff * 2, max_backoff)
