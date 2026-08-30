"""A Core that isn't there, for screenshots and for UI work without a Core.

Two jobs. The first is honesty in the documentation: a screenshot of the real
thing shows the machine's hostname, the actual layout of someone's house in the
zone list, and what they happen to be listening to. Redacting that afterwards
leaves the personal values in the file's history; running against stand-in
values means they were never there.

The second is that building an interface should not require a paid subscription
and a Core on the LAN. `--demo` gives the whole surface something to render.

It implements the same seam `RoonSession` does, which is the point of keeping
that seam narrow: connect, control, browse, load, and a zone store.
"""
from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path

DEMO_IMAGE_KEY = "demo-cover"

# Deliberately invented. Generic rooms rather than a real floor plan, and music
# that does not exist rather than someone's listening history.
ZONES = [
    ("Studio", True),
    ("Lounge", False),
    ("Conservatory", False),
    ("Workshop", False),
]

TRACKS = [
    ("Parallax", "Nocturne Atlas", "Slow Light", 247),
    ("Harbour Lights", "Nocturne Atlas", "Slow Light", 198),
    ("Everything Nearby", "Field Notes", "Quiet Machines", 231),
]


class _Reply:
    def __init__(self, name="Success", body=None):
        self.name, self.body = name, body


class DemoCore:
    ip, http_port, name, display_version = "127.0.0.1", 9821, "Demo Core", "2.70 (demo)"


class DemoSession:
    def __init__(self, port: int = 9821):
        from .zones import ZoneStore

        self.port = port
        self.core = DemoCore()
        self.core.http_port = port
        self.core_id = "demo-core"
        self.connected = True
        self.notifications = True
        self.zones = ZoneStore()

        self.on_zones = None
        self.on_connected = None
        self.on_disconnected = None
        self.on_awaiting_approval = None
        self.on_pinned_changed = None

        self._tracks = itertools.cycle(TRACKS)
        self._track = next(self._tracks)
        self._state = "playing"
        self._position = 41.0
        self._volume = -18.0
        self._muted = False
        self._pinned = "demo-zone-0"
        self._stop = threading.Event()
        self.zones.apply("Subscribed", {"zones": self._build()})

    # -- the world -------------------------------------------------------
    def _build(self):
        title, artist, album, length = self._track
        out = []
        for i, (name, is_local) in enumerate(ZONES):
            zone_id = f"demo-zone-{i}"
            playing = zone_id == self._pinned and self._state == "playing"
            out.append({
                "zone_id": zone_id,
                "display_name": f"{name} (Omarchy)" if is_local else name,
                "state": "playing" if playing else "paused",
                "is_play_allowed": not playing,
                "is_pause_allowed": playing,
                "is_next_allowed": True,
                "is_previous_allowed": True,
                "is_seek_allowed": True,
                "queue_items_remaining": 12,
                "queue_time_remaining": 2400,
                "settings": {"loop": "disabled", "shuffle": False, "auto_radio": True},
                "outputs": [{
                    "output_id": f"demo-output-{i}",
                    "zone_id": zone_id,
                    "display_name": f"{name} (Omarchy)" if is_local else name,
                    "volume": {"type": "db", "min": -80, "max": 0,
                               "value": self._volume if is_local else -30,
                               "step": 1, "is_muted": self._muted if is_local else False,
                               "hard_limit_min": -80, "hard_limit_max": 0,
                               "soft_limit": 0},
                    "source_controls": [{"control_key": "1", "status": "selected",
                                         "display_name": name,
                                         "supports_standby": False}],
                }],
                "now_playing": {
                    "seek_position": int(self._position),
                    "length": length,
                    "image_key": DEMO_IMAGE_KEY,
                    "one_line": {"line1": f"{title} - {artist}"},
                    "two_line": {"line1": title, "line2": artist},
                    "three_line": {"line1": title, "line2": artist, "line3": album},
                },
            })
        return out

    def _push(self):
        self.zones.apply("Subscribed", {"zones": self._build()})
        if self.on_zones:
            self.on_zones({self._pinned})

    # -- the seam --------------------------------------------------------
    @property
    def pinned_zone_id(self):
        return self._pinned

    def pinned_zone(self):
        return self.zones.summary(self._pinned)

    def pin(self, zone_id):
        if zone_id:
            self._pinned = zone_id
        self._push()
        if self.on_pinned_changed:
            self.on_pinned_changed(self._pinned)

    def set_notifications(self, enabled):
        self.notifications = bool(enabled)

    def control(self, zone_id, action):
        if action in ("play", "playpause") and self._state != "playing":
            self._state = "playing"
        elif action in ("pause", "playpause", "stop"):
            self._state = "paused"
        if action in ("next", "previous"):
            self._track = next(self._tracks)
            self._position = 0.0
        self._push()
        return _Reply()

    def seek(self, zone_id, seconds, how="absolute"):
        self._position = max(0.0, float(seconds))
        self._push()
        return _Reply()

    def change_volume(self, output_id, value, how="absolute"):
        self._volume = float(value)
        self._push()
        return _Reply()

    def mute(self, output_id, muted):
        self._muted = bool(muted)
        self._push()
        return _Reply()

    def change_settings(self, zone_id, **settings):
        return _Reply()

    def browse(self, hierarchy="browse", **opts):
        return _Reply(body={"list": {"title": "Explore", "count": 0}})

    def load(self, hierarchy="browse", offset=0, count=100, **opts):
        return _Reply(body={"items": [], "offset": 0,
                            "list": {"title": "Explore", "count": 0}})

    def image_url(self, image_key, width=0, height=0, scale="fit"):
        return f"http://127.0.0.1:{self.port}/demo-art/{image_key}"

    def output_format(self):
        return {"encoding": "pcm", "sample_rate": 96000, "bits": 24,
                "channels": 2, "device": {"format": "S32_LE", "bits": 32},
                "sample_type": "pcm", "label": "PCM 24/96"}

    def art_palette(self, image_key):
        from . import palette
        data = demo_cover_bytes()
        return palette.analyse(data) if data else None

    # -- lifecycle -------------------------------------------------------
    def run_forever(self, *_a, **_k):
        if self.on_connected:
            self.on_connected({"display_name": "Demo Core",
                               "display_version": "2.70 (demo)",
                               "core_id": "demo-core"})
        title, artist, album, length = self._track
        while not self._stop.wait(1.0):
            if self._state == "playing":
                self._position += 1.0
                if self._position >= self._track[3]:
                    self._track = next(self._tracks)
                    self._position = 0.0
            self._push()

    def stop(self):
        self._stop.set()

    def close(self):
        pass


def demo_cover_bytes() -> bytes | None:
    path = Path(__file__).resolve().parents[2] / "assets" / "demo-cover.png"
    try:
        return path.read_bytes()
    except OSError:
        return None
