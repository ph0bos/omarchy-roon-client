from __future__ import annotations

import copy

from _fixtures import a_zone, zones_body

from omarchy_roond.zones import ZoneStore


def store() -> ZoneStore:
    s = ZoneStore()
    s.apply("Subscribed", zones_body())
    return s


def test_subscribed_replaces_everything():
    s = store()
    assert len(s) == len(zones_body()["zones"])
    s.apply("Subscribed", {"zones": [a_zone()]})
    assert len(s) == 1


def test_unsubscribed_clears_and_reports_every_zone():
    s = store()
    touched = s.apply("Unsubscribed", {})
    assert len(s) == 0
    assert len(touched) == len(zones_body()["zones"])


def test_changed_adds_removes_and_replaces():
    s = store()
    victim = a_zone()["zone_id"]
    assert s.apply("Changed", {"zones_removed": [victim]}) == {victim}
    assert victim not in s

    added = copy.deepcopy(a_zone())
    added["zone_id"] = "new-zone"
    added["display_name"] = "Shed"
    s.apply("Changed", {"zones_added": [added]})
    assert s.get("new-zone")["display_name"] == "Shed"

    renamed = copy.deepcopy(added)
    renamed["display_name"] = "Workshop"
    s.apply("Changed", {"zones_changed": [renamed]})
    assert s.get("new-zone")["display_name"] == "Workshop"


def test_seek_change_patches_and_does_not_replace_the_zone():
    """The bug this guards: treating a seek tick like `zones_changed`.

    A seek message carries only a position and a queue countdown. Replacing the
    zone with it would drop `now_playing` entirely, once a second, making the
    interface flicker between a track and nothing.
    """
    s = store()
    zone = a_zone()
    zid = zone["zone_id"]
    before = s.get(zid)["now_playing"]["three_line"]["line1"]

    touched = s.apply("Changed", {"zones_seek_changed": [
        {"zone_id": zid, "seek_position": 123, "queue_time_remaining": 456}]})

    assert touched == {zid}
    after = s.get(zid)
    assert after["now_playing"]["seek_position"] == 123
    assert after["queue_time_remaining"] == 456
    assert after["now_playing"]["three_line"]["line1"] == before


def test_seek_change_for_an_unknown_zone_is_ignored():
    s = store()
    assert s.apply("Changed", {"zones_seek_changed": [
        {"zone_id": "never-heard-of-it", "seek_position": 5}]}) == set()


def test_seek_change_on_a_stopped_zone_does_not_invent_now_playing():
    s = store()
    zone = copy.deepcopy(a_zone())
    zone["zone_id"] = "quiet"
    zone.pop("now_playing", None)
    s.apply("Changed", {"zones_added": [zone]})
    s.apply("Changed", {"zones_seek_changed": [
        {"zone_id": "quiet", "seek_position": 9}]})
    assert s.get("quiet").get("now_playing") is None


def test_unknown_response_names_are_inert():
    s = store()
    assert s.apply("Something Roon Added Later", {"zones": []}) == set()
    assert len(s) == len(zones_body()["zones"])


def test_summary_shape():
    s = store()
    zid = a_zone()["zone_id"]
    summary = s.summary(zid)
    assert set(summary) == {"zone_id", "name", "state", "track", "settings",
                            "queue_items_remaining", "queue_time_remaining",
                            "can", "outputs"}
    assert summary["track"]["title"]
    assert summary["outputs"]


def test_summary_of_a_missing_zone_is_none():
    assert store().summary("nope") is None


def test_summary_reports_mute_state_and_capability():
    s = store()
    outputs = s.summary(a_zone()["zone_id"])["outputs"]
    assert all("muted" in o and "can_mute" in o for o in outputs)


def test_an_output_without_a_volume_object_cannot_mute():
    """A Bluesound NODE exposes no volume at all, so there is nothing to mute."""
    import copy
    s = store()
    zone = copy.deepcopy(a_zone())
    zone["zone_id"] = "no-volume"
    for out in zone["outputs"]:
        out.pop("volume", None)
    s.apply("Changed", {"zones_added": [zone]})
    out = s.summary("no-volume")["outputs"][0]
    assert out["can_mute"] is False and out["muted"] is False
