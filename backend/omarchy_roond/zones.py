"""The zone state the rest of the daemon reads.

Roon sends the whole world once, then deltas forever. The merge rules are taken
from `node-roon-api-transport/lib.js:354`:

    Subscribed    replace everything from `zones`
    Changed       zones_removed / zones_added / zones_changed / zones_seek_changed
    Unsubscribed  drop everything

`zones_seek_changed` is the one that is easy to get wrong. It arrives about once
a second, carries only a seek position and a queue countdown, and must *patch*
the zone in place -- treating it like `zones_changed` and replacing the zone would
throw away `now_playing` and make the interface flicker between a track and
nothing at all, once per second.

Pure, so it can be driven from captured fixtures with no Core in reach.
"""
from __future__ import annotations

from . import text


class ZoneStore:
    def __init__(self) -> None:
        self._zones: dict[str, dict] = {}

    # -- queries ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self._zones)

    def __contains__(self, zone_id: str) -> bool:
        return zone_id in self._zones

    def get(self, zone_id: str) -> dict | None:
        return self._zones.get(zone_id)

    def all(self) -> list[dict]:
        return sorted(self._zones.values(), key=lambda z: z.get("display_name") or "")

    def playing(self) -> list[dict]:
        return [z for z in self.all() if z.get("state") == "playing"]

    def summary(self, zone_id: str) -> dict | None:
        """A zone flattened into what the interface actually renders."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return None
        outputs = zone.get("outputs") or []
        return {
            "zone_id": zone_id,
            "name": zone.get("display_name") or "",
            "state": zone.get("state") or "stopped",
            "track": text.track(zone.get("now_playing")),
            "settings": zone.get("settings") or {},
            "queue_items_remaining": zone.get("queue_items_remaining") or 0,
            "queue_time_remaining": zone.get("queue_time_remaining") or 0,
            "can": {
                "play": bool(zone.get("is_play_allowed")),
                "pause": bool(zone.get("is_pause_allowed")),
                "next": bool(zone.get("is_next_allowed")),
                "previous": bool(zone.get("is_previous_allowed")),
                "seek": bool(zone.get("is_seek_allowed")),
            },
            "outputs": [
                {
                    "output_id": o.get("output_id"),
                    "name": o.get("display_name") or "",
                    "volume": o.get("volume"),
                    "bounds": text.volume_bounds(o),
                    "muted": bool((o.get("volume") or {}).get("is_muted")),
                    # An `incremental` control has no is_muted at all, so mute
                    # is a capability to check rather than assume.
                    "can_mute": (o.get("volume") or {}).get("is_muted") is not None,
                    "standby": text.is_standby(o),
                    "can_group_with": list(o.get("can_group_with_output_ids") or []),
                }
                for o in outputs
            ],
        }

    # -- merging ---------------------------------------------------------
    def apply(self, response: str, body: dict | None) -> set[str]:
        """Merge one subscription message. Returns the zone ids that changed."""
        body = body or {}

        if response == "Subscribed":
            self._zones = {z["zone_id"]: z for z in body.get("zones") or []}
            return set(self._zones)

        if response == "Unsubscribed":
            touched = set(self._zones)
            self._zones = {}
            return touched

        if response != "Changed":
            return set()

        touched: set[str] = set()

        for zone_id in body.get("zones_removed") or []:
            if self._zones.pop(zone_id, None) is not None:
                touched.add(zone_id)

        for zone in (body.get("zones_added") or []) + (body.get("zones_changed") or []):
            zone_id = zone.get("zone_id")
            if zone_id:
                self._zones[zone_id] = zone
                touched.add(zone_id)

        for seek in body.get("zones_seek_changed") or []:
            zone = self._zones.get(seek.get("zone_id"))
            if zone is None:
                # A seek tick for a zone we have not been told about yet. Dropping
                # it is correct: the zones_added that explains it is on its way.
                continue
            if zone.get("now_playing") is not None and "seek_position" in seek:
                zone["now_playing"]["seek_position"] = seek["seek_position"]
            if "queue_time_remaining" in seek:
                zone["queue_time_remaining"] = seek["queue_time_remaining"]
            touched.add(seek["zone_id"])

        return touched
