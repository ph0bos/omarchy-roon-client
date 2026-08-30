"""MPRIS mapping. Pure enough to test without a bus or a Core.

`MprisPlayer` only needs GLib once it is started; the mapping functions are
plain Python over the same zone summaries the API serves.
"""
from __future__ import annotations

import pytest
from _fixtures import zones_body

from omarchy_roond.mpris import LOOP_FROM_MPRIS, LOOP_TO_MPRIS, MprisPlayer
from omarchy_roond.zones import ZoneStore


class FakeSession:
    def __init__(self, zone_id=None):
        self.zones = ZoneStore()
        self.zones.apply("Subscribed", zones_body())
        self._zone_id = zone_id or self.zones.all()[0]["zone_id"]
        self.core = None

    def pinned_zone(self):
        return self.zones.summary(self._zone_id)


def player(zone_id=None) -> MprisPlayer:
    return MprisPlayer(FakeSession(zone_id))


def test_full_db_volume_is_not_reported_as_silence():
    """A dB control reads 0 at FULL volume, and 0 is falsy.

    Defaulting with `or` fires on exactly the value that means loudest, so the
    bar and the OSD show muted while music plays. This is the regression that
    bug produced against a real RoonBridge zone.
    """
    p = player()
    zone = p.session.zones.summary(p.session._zone_id)
    zone["outputs"][0]["volume"] = {"type": "db", "min": -80, "max": 0,
                                    "value": 0, "soft_limit": 0}
    zone["outputs"][0]["bounds"] = (-80.0, 0.0)
    assert p._volume(zone) == pytest.approx(1.0)


@pytest.mark.parametrize("value,expected", [(-80, 0.0), (-40, 0.5), (0, 1.0)])
def test_db_volume_maps_across_the_range(value, expected):
    p = player()
    zone = p.session.zones.summary(p.session._zone_id)
    zone["outputs"][0]["volume"] = {"type": "db", "min": -80, "max": 0,
                                    "value": value}
    zone["outputs"][0]["bounds"] = (-80.0, 0.0)
    assert p._volume(zone) == pytest.approx(expected)


def test_volume_is_zero_when_there_is_no_fader():
    p = player()
    zone = p.session.zones.summary(p.session._zone_id)
    for out in zone["outputs"]:
        out["volume"], out["bounds"] = None, None
    assert p._volume(zone) == 0.0


def test_volume_of_no_zone_is_zero():
    assert player()._volume(None) == 0.0


def test_loop_mapping_round_trips():
    for roon, mpris in LOOP_TO_MPRIS.items():
        assert LOOP_FROM_MPRIS[mpris] == roon


def test_position_is_microseconds_and_clamped_to_length():
    p = player()
    zone = p.session.zones.summary(p.session._zone_id)
    p._anchor_pos = 10.0
    p._anchor_playing = False
    assert p._position_us(zone) == 10_000_000

    p._anchor_pos = zone["track"]["length"] + 500
    assert p._position_us(zone) == zone["track"]["length"] * 1_000_000


def test_position_of_no_zone_is_zero():
    assert player()._position_us(None) == 0
