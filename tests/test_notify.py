"""Track announcements. The guards matter more than the sending.

A notifier that fires on every zone push would produce one card per second while
music plays, one on every pause, and one for whatever happened to be playing when
the daemon started. Each of those is the difference between a feature people keep
and one they turn off, so they are what is tested here.
"""
from __future__ import annotations

import copy

from _fixtures import zones_body

from omarchy_roond.notify import Notifier
from omarchy_roond.zones import ZoneStore


class FakeSession:
    def __init__(self):
        self.zones = ZoneStore()
        self.zones.apply("Subscribed", zones_body())
        self._zone_id = self.zones.all()[0]["zone_id"]
        self.core = None

    def pinned_zone(self):
        return self.zones.summary(self._zone_id)

    def image_url(self, *_a, **_k):
        return ""


def notifier(enabled=True):
    n = Notifier(FakeSession(), enabled=enabled)
    n._conn = object()                 # pretend the bus is there
    n.announced = []
    n._announce = lambda zone, track: n.announced.append(track["title"])
    return n


def set_track(n, title, state="playing"):
    zone = n.session.zones.get(n.session._zone_id)
    zone["state"] = state
    zone["now_playing"] = copy.deepcopy(zone.get("now_playing") or {})
    zone["now_playing"].setdefault("three_line", {})
    zone["now_playing"]["three_line"] = {"line1": title, "line2": "An Artist",
                                         "line3": "An Album"}


def test_first_update_is_never_announced():
    """A daemon restart must not pop a card for what was already playing."""
    n = notifier()
    set_track(n, "Whatever Was Already On")
    n.on_zones()
    assert n.announced == []


def test_a_track_change_is_announced():
    n = notifier()
    set_track(n, "First")
    n.on_zones()                       # priming
    set_track(n, "Second")
    n.on_zones()
    assert n.announced == ["Second"]


def test_repeated_pushes_for_the_same_track_are_silent():
    """The seek tick arrives about once a second; it must not announce."""
    n = notifier()
    set_track(n, "First")
    n.on_zones()
    set_track(n, "Second")
    n.on_zones()
    for _ in range(10):
        n.on_zones()
    assert n.announced == ["Second"]


def test_pausing_does_not_announce():
    n = notifier()
    set_track(n, "First")
    n.on_zones()
    set_track(n, "First", state="paused")
    n.on_zones()
    assert n.announced == []


def test_a_track_change_while_paused_is_not_announced():
    """Queueing something up without playing it should stay quiet."""
    n = notifier()
    set_track(n, "First")
    n.on_zones()
    set_track(n, "Second", state="paused")
    n.on_zones()
    assert n.announced == []


def test_disabled_notifier_says_nothing():
    n = notifier(enabled=False)
    set_track(n, "First")
    n.on_zones()
    set_track(n, "Second")
    n.on_zones()
    assert n.announced == []


def test_enabling_mid_song_announces_the_next_track_not_this_one():
    """Turning notifications on should not pop a card for what you are already
    looking at. The first push after enabling primes; the next change speaks."""
    n = notifier(enabled=False)
    set_track(n, "First")
    n.on_zones()

    n.enabled = True
    set_track(n, "Second")
    n.on_zones()
    assert n.announced == []            # primes on Second, stays quiet

    set_track(n, "Third")
    n.on_zones()
    assert n.announced == ["Third"]


def test_no_bus_is_survivable():
    n = notifier()
    n._conn = None
    set_track(n, "First")
    n.on_zones()
    set_track(n, "Second")
    n.on_zones()
    assert n.announced == []


def test_suppressed_notifier_stays_silent():
    """While a surface showing the track is open, the card is pure duplication."""
    n = notifier()
    set_track(n, "First")
    n.on_zones()
    n.suppressed = True
    set_track(n, "Second")
    n.on_zones()
    assert n.announced == []


def test_unsuppressing_does_not_announce_what_changed_while_open():
    """The user watched that change happen; announcing it afterwards is stale."""
    n = notifier()
    set_track(n, "First")
    n.on_zones()

    n.suppressed = True
    set_track(n, "Second")
    n.on_zones()

    n.suppressed = False
    n.on_zones()                       # same track, now visible again
    assert n.announced == []

    set_track(n, "Third")
    n.on_zones()
    assert n.announced == ["Third"]
