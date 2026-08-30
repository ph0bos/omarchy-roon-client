"""A Core that isn't there, for screenshots and for UI work without a Core.

Two jobs. The first is honesty in the documentation: a screenshot of the real
thing shows the machine's hostname, the actual layout of someone's house in the
zone list, and what they happen to be listening to. Redacting that afterwards
leaves the personal values in the file's history; running against stand-in
values means they were never there.

The second is that building an interface should not require a paid subscription
and a Core on the LAN. `--demo` gives the whole surface something to render.

It implements the same seam `RoonSession` does, which is the point of keeping
that seam narrow: connect, control, browse, load, a zone store and a queue.
"""
from __future__ import annotations

import itertools
import threading
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

# An invented library, so the browse surfaces can be built and photographed
# without a subscription and without anyone's listening history. Shaped exactly
# like a Core's: a tree of {title, subtitle, image_key, item_key, hint}, where a
# "list" pushes deeper and an "action" plays something.
ALBUMS = [
    ("Slow Light", "Nocturne Atlas", 9),
    ("Quiet Machines", "Field Notes", 7),
    ("Ardent Hours", "Winter Count", 11),
]

DEMO_TREE = {
    # item_key -> (list title, [items])
    "root": ("Explore", [
        ("demo:library", "Library", None, "list"),
        ("demo:albums", "Albums", "%d albums" % len(ALBUMS), "list"),
        ("demo:artists", "Artists", "%d artists" % len(ALBUMS), "list"),
        ("demo:radio", "My Live Radio", None, "list"),
    ]),
    "demo:library": ("Library", [
        ("demo:albums", "Albums", None, "list"),
        ("demo:artists", "Artists", None, "list"),
    ]),
    "demo:radio": ("My Live Radio", [
        ("demo:station-0", "Coastal Shipping FM", "Ambient", "action"),
        ("demo:station-1", "Night Works Radio", "Electronic", "action"),
    ]),
}


class _Reply:
    def __init__(self, name="Success", body=None):
        self.name, self.body = name, body


class DemoCore:
    ip, http_port, name, display_version = "127.0.0.1", 9821, "Demo Core", "2.70 (demo)"


class DemoSession:
    def __init__(self, port: int = 9821):
        from .queue import QueueStore
        from .zones import ZoneStore

        self.port = port
        self.core = DemoCore()
        self.core.http_port = port
        self.core_id = "demo-core"
        # There is no Core to fetch art from, so the daemon serves the invented
        # sleeve itself and publishes that as the base every surface builds on.
        self.image_base = f"http://127.0.0.1:{port}/demo-art"
        self.connected = True
        self.notifications = True
        self.zones = ZoneStore()
        self.queue = QueueStore()

        self.on_zones = None
        self.on_connected = None
        self.on_disconnected = None
        self.on_awaiting_approval = None
        self.on_pinned_changed = None
        self.on_queue = None

        self._tracks = itertools.cycle(TRACKS)
        self._track = next(self._tracks)
        self._state = "playing"
        self._position = 41.0
        self._volume = -18.0
        self._muted = False
        self._pinned = "demo-zone-0"
        # One browse position per multi_session_key, exactly as a Core keeps it.
        self._cursors: dict[str, str] = {}
        self._stop = threading.Event()
        self.zones.apply("Subscribed", {"zones": self._build()})
        self.subscribe_queue(self._pinned)

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

    def _queue_items(self):
        """Twelve invented tracks, matching the `queue_items_remaining` above."""
        items = []
        for i in range(12):
            title, artist, album, length = TRACKS[i % len(TRACKS)]
            items.append({
                "queue_item_id": 1000 + i,
                "length": length,
                "image_key": DEMO_IMAGE_KEY,
                "one_line": {"line1": f"{title} - {artist}"},
                "two_line": {"line1": title, "line2": artist},
                "three_line": {"line1": title, "line2": artist, "line3": album},
            })
        return items

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
        self.subscribe_queue(self._pinned)
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

    def subscribe_queue(self, zone_id, max_item_count=100):
        self.queue.reset(zone_id)
        self.queue.apply("Subscribed", {"items": self._queue_items()[:max_item_count]})
        if self.on_queue:
            self.on_queue(zone_id)

    def unsubscribe_queue(self):
        self.queue.reset(None)

    def play_from_here(self, zone_id, queue_item_id):
        """Start from a queue item, and drop what came before it.

        The demo queue shrinks the way a real one does, so a surface that
        re-reads after playing from the middle sees a shorter list rather than
        the same one.
        """
        index = next((i for i, item in enumerate(self.queue.all())
                      if item.get("queue_item_id") == queue_item_id), None)
        if index is None:
            return _Reply("InvalidRequest", {"message": "no such queue item"})
        self.queue.apply("Changed",
                         {"changes": [{"operation": "remove",
                                       "index": 0, "count": index}]})
        title, artist, album, length = TRACKS[index % len(TRACKS)]
        self._track = (title, artist, album, length)
        self._position = 0.0
        self._state = "playing"
        if self.on_queue:
            self.on_queue(zone_id)
        self._push()
        return _Reply()

    # -- browsing --------------------------------------------------------
    #
    # The same stateful cursor a real Core keeps: one position per
    # `multi_session_key`, moved by browse and read by load. Getting this
    # honestly wrong-shaped would make the demo useless for building the browse
    # surfaces, which is the whole reason it exists.

    def _album_items(self):
        return [(f"demo:album-{i}", title, artist, "list")
                for i, (title, artist, _n) in enumerate(ALBUMS)]

    def _artist_items(self):
        return [(f"demo:artist-{i}", artist, f"{n} albums", "list")
                for i, (_t, artist, n) in enumerate(ALBUMS)]

    def _track_items(self, album_index):
        title, artist, _n = ALBUMS[album_index % len(ALBUMS)]
        return [(f"demo:play-{album_index}-{i}", track, artist, "action")
                for i, (track, _a, _al, _len) in enumerate(TRACKS)]

    def _node(self, item_key):
        """(title, items) for a position in the invented tree."""
        if item_key in DEMO_TREE:
            return DEMO_TREE[item_key]
        if item_key == "demo:albums":
            return "Albums", self._album_items()
        if item_key == "demo:artists":
            return "Artists", self._artist_items()
        if item_key and item_key.startswith("demo:album-"):
            index = int(item_key.rsplit("-", 1)[1])
            return ALBUMS[index % len(ALBUMS)][0], self._track_items(index)
        if item_key and item_key.startswith("demo:artist-"):
            index = int(item_key.rsplit("-", 1)[1])
            title, artist, _n = ALBUMS[index % len(ALBUMS)]
            return artist, [(f"demo:album-{index}", title, artist, "list")]
        return DEMO_TREE["root"]

    def browse(self, hierarchy="browse", **opts):
        key = opts.get("multi_session_key") or "default"
        item_key = opts.get("item_key")

        if hierarchy == "search":
            typed = opts.get("input")
            if typed is None:
                # The Core answers a search hierarchy with a prompt item, and
                # you browse it again carrying what was typed.
                self._cursors[key] = "demo:search-prompt"
                return _Reply(body={"action": "list",
                                    "list": {"title": "Search", "count": 1,
                                             "level": 0}})
            self._cursors[key] = f"demo:search:{typed}"
            return _Reply(body={"action": "list",
                                "list": {"title": f"Results for {typed}",
                                         "count": len(self._search(typed)),
                                         "level": 1}})

        if hierarchy in ("albums", "artists") and not item_key:
            item_key = f"demo:{hierarchy}"
        if opts.get("pop_all") and not item_key:
            item_key = "root"
        if item_key and item_key.startswith("demo:play-"):
            # An action item plays; there is no list to read afterwards.
            self._track = next(self._tracks)
            self._position = 0.0
            self._state = "playing"
            self._push()
            return _Reply(body={"action": "message", "message": "Playing",
                                "is_error": False})

        position = item_key or self._cursors.get(key) or "root"
        self._cursors[key] = position
        title, items = self._node(position)
        return _Reply(body={"action": "list",
                            "list": {"title": title, "count": len(items),
                                     "level": 0 if position == "root" else 1,
                                     "subtitle": None, "image_key": None}})

    def _search(self, typed):
        needle = str(typed).lower()
        hits = [(k, t, s, h) for (k, t, s, h) in
                self._album_items() + self._artist_items()
                if needle in t.lower() or (s and needle in s.lower())]
        return hits

    def load(self, hierarchy="browse", offset=0, count=100, **opts):
        key = opts.get("multi_session_key") or "default"
        position = self._cursors.get(key) or "root"

        if position == "demo:search-prompt":
            items = [("demo:search-input", "Search", "Type to search", "action")]
            title = "Search"
        elif position.startswith("demo:search:"):
            items = self._search(position[len("demo:search:"):])
            title = "Results"
        else:
            title, items = self._node(position)

        window = items[offset:offset + count]
        return _Reply(body={
            "offset": offset,
            "list": {"title": title, "count": len(items), "level": 0,
                     "subtitle": None, "image_key": None},
            "items": [{"title": t, "subtitle": s, "item_key": k, "hint": h,
                       "image_key": DEMO_IMAGE_KEY if h == "list" else None}
                      for (k, t, s, h) in window],
        })

    def setup_summary(self):
        """There is nothing to set up: the Core is invented and so is the zone.

        Computing the real ladder here would ask systemd about a bridge this
        session does not use, and open the first-run wizard over a demo that is
        working perfectly.
        """
        from . import setup
        titles = ["Roon Core found", "Paired with the Core", "Approved in Roon",
                  "RoonBridge running", "This machine visible as a zone"]
        keys = ["core", "paired", "approved", "bridge", "zone"]
        return {
            "ready": True,
            "blocked_on": None,
            "rungs": [{"key": k, "title": t, "state": setup.OK,
                       "detail": "demo", "fix": ""}
                      for k, t in zip(keys, titles, strict=True)],
        }

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
