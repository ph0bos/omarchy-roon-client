#!/usr/bin/env python3
"""Guard the captured payloads the whole test suite is built on.

Unit tests that run against a malformed fixture can pass against nonsense, so
this checks the shapes rather than the values -- what must be present for the
daemon's assumptions to hold, and nothing about this particular library.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "spikes" / "fixtures"

REQUIRED = {
    "zones": ["zones"],
    "outputs": ["outputs"],
    "queue": ["items"],
    "browse-browse": ["items"],
    "browse-albums": ["items"],
    "browse-artists": ["items"],
    "browse-genres": ["items"],
    "browse-playlists": ["items"],
}

problems: list[str] = []


def check(name: str, keys: list[str]) -> dict | None:
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        problems.append(f"{name}.json is missing")
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        problems.append(f"{name}.json is not valid JSON: {e}")
        return None
    for key in keys:
        if key not in data:
            problems.append(f"{name}.json has no {key!r}")
    return data


for fixture, keys in REQUIRED.items():
    data = check(fixture, keys)
    if data is None:
        continue

    if fixture == "zones":
        for zone in data.get("zones", []):
            for key in ("zone_id", "display_name", "state", "outputs"):
                if key not in zone:
                    problems.append(f"zones: a zone has no {key!r}")
            np = zone.get("now_playing")
            if np is not None and "three_line" not in np:
                problems.append("zones: now_playing without three_line -- the "
                                "only track metadata the daemon has")
        if not any(z.get("now_playing") for z in data.get("zones", [])):
            problems.append("zones: no zone has now_playing, so the text tests "
                            "prove nothing")

    if fixture == "outputs":
        outs = data.get("outputs", [])
        if not any("volume" in o for o in outs):
            problems.append("outputs: none has a volume object")
        if not any("volume" not in o for o in outs):
            problems.append("outputs: none lacks a volume object, so the "
                            "no-volume-control path is untested")
        if not any((o.get("volume") or {}).get("soft_limit") is not None
                   for o in outs):
            problems.append("outputs: none has soft_limit, so the volume "
                            "clamping test proves nothing")

    if fixture.startswith("browse-"):
        for item in data.get("items", [])[:5]:
            if "title" not in item:
                problems.append(f"{fixture}: an item has no title")

if problems:
    print("fixture problems:")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)

print(f"all {len(REQUIRED)} fixtures look sane")
