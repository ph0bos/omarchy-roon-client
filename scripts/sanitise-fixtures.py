#!/usr/bin/env python3
"""Scrub captured fixtures of anything personal, keeping what the tests need.

Payloads captured from a real Core carry the names of the rooms in someone's
house, their music library and what they were listening to. None of that belongs
in a public repository, and redacting after the fact leaves it in the history.

What must survive is every *structural* property the tests assert on -- an output
with a `soft_limit` below its maximum, an output with no volume object at all, a
`now_playing` with a `three_line` -- because those are the cases the fixtures
exist to pin. So this renames rather than regenerates, and identifies the special
outputs by their properties rather than by their names.

    python3 scripts/sanitise-fixtures.py [--check]

`--check` exits non-zero if anything still looks personal, which is what CI runs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "spikes" / "fixtures"

ROOMS = ["Lounge", "Study", "Loft", "Conservatory", "Terrace", "Cellar", "Hallway"]
LIMITED_ROOM = "Workshop"          # the volume-limited output
NO_VOLUME_ROOM = "Network Streamer"  # the output with no volume control

TRACKS = [
    ("Parallax", "Nocturne Atlas", "Slow Light"),
    ("Harbour Lights", "Nocturne Atlas", "Slow Light"),
    ("Everything Nearby", "Field Notes", "Quiet Machines"),
    ("Low Tide", "Field Notes", "Quiet Machines"),
    ("Winter Count", "Ardent Hours", "The Long Way Round"),
    ("Signal Fire", "Ardent Hours", "The Long Way Round"),
    ("Paper Cranes", "Marble Arch", "Interiors"),
    ("Sixth Sense", "Marble Arch", "Interiors"),
    ("Meridian", "Coastal Static", "Blue Hour"),
    ("Undertow", "Coastal Static", "Blue Hour"),
    ("Slow Traffic", "The Ninth Wave", "Northerly"),
    ("Glasshouse", "The Ninth Wave", "Northerly"),
]
ARTISTS = ["Nocturne Atlas", "Field Notes", "Ardent Hours", "Marble Arch",
           "Coastal Static", "The Ninth Wave", "Vellum", "Halflight"]
GENRES = ["Ambient", "Post-Rock", "Electronic", "Jazz", "Classical",
          "Folk", "Downtempo", "Shoegaze"]
PLAYLISTS = ["Late Evening", "Long Drive", "Focus", "Sunday Morning",
             "Rainy Window", "Reference", "New This Month", "Slow Start"]


def fake_key(seed: str) -> str:
    return hashlib.sha1(f"fixture:{seed}".encode()).hexdigest()[:32]


def name_zones(zones: list[dict]) -> dict[str, str]:
    """Map each real name to a synthetic one, pinned by property not by name."""
    mapping: dict[str, str] = {}
    plain = iter(ROOMS)
    for zone in zones:
        outputs = zone.get("outputs") or []
        volume = (outputs[0].get("volume") if outputs else None) or {}
        if not outputs or "volume" not in outputs[0]:
            new = NO_VOLUME_ROOM
        elif volume.get("soft_limit") is not None and \
                volume.get("max") is not None and \
                volume["soft_limit"] < volume["max"]:
            new = LIMITED_ROOM
        else:
            new = next(plain)
        mapping[zone.get("display_name", "")] = new
        for out in outputs:
            mapping[out.get("display_name", "")] = new
    return mapping


def scrub_now_playing(np: dict, index: int) -> None:
    title, artist, album = TRACKS[index % len(TRACKS)]
    if "three_line" in np:
        np["three_line"] = {"line1": title, "line2": artist, "line3": album}
    if "two_line" in np:
        np["two_line"] = {"line1": title, "line2": artist}
    if "one_line" in np:
        np["one_line"] = {"line1": f"{title} - {artist}"}
    if np.get("image_key"):
        np["image_key"] = fake_key(f"{album}/{title}")
    if np.get("artist_image_keys"):
        np["artist_image_keys"] = [fake_key(artist)]


def main(check: bool) -> int:
    zones_path = FIXTURES / "zones.json"
    zones = json.loads(zones_path.read_text())
    mapping = name_zones(zones["zones"])

    for i, zone in enumerate(zones["zones"]):
        zone["display_name"] = mapping.get(zone["display_name"], f"Zone {i}")
        for out in zone.get("outputs") or []:
            out["display_name"] = mapping.get(out["display_name"], zone["display_name"])
            for control in out.get("source_controls") or []:
                control["display_name"] = out["display_name"]
        if zone.get("now_playing"):
            scrub_now_playing(zone["now_playing"], i)
    write(zones_path, zones, check)

    outputs_path = FIXTURES / "outputs.json"
    outputs = json.loads(outputs_path.read_text())
    for out in outputs["outputs"]:
        out["display_name"] = mapping.get(out["display_name"], "Output")
        for control in out.get("source_controls") or []:
            control["display_name"] = out["display_name"]
    write(outputs_path, outputs, check)

    queue_path = FIXTURES / "queue.json"
    queue = json.loads(queue_path.read_text())
    for i, item in enumerate(queue.get("items") or []):
        scrub_now_playing(item, i)
    write(queue_path, queue, check)

    swaps = {"browse-albums": (TRACKS, "album"), "browse-artists": (ARTISTS, "artist"),
             "browse-genres": (GENRES, "genre"), "browse-playlists": (PLAYLISTS, "playlist")}
    for name, (pool, kind) in swaps.items():
        path = FIXTURES / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for i, item in enumerate(data.get("items") or []):
            if kind == "album":
                title, artist, album = pool[i % len(pool)]
                item["title"] = album if i % 2 else f"{album} (Deluxe)"
                item["subtitle"] = artist
            else:
                item["title"] = pool[i % len(pool)]
            if item.get("image_key"):
                item["image_key"] = fake_key(f"{name}/{i}")
        write(path, data, check)

    print("fixtures are free of personal detail")
    return 0


def write(path: Path, data, check: bool) -> None:
    text = json.dumps(data, indent=2) + "\n"
    if check:
        if path.read_text() != text:
            print(f"::error::{path.name} still contains unscrubbed values")
            raise SystemExit(1)
        return
    path.write_text(text)
    print(f"  scrubbed {path.name}")


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
