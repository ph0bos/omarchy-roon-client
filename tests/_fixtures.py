"""Payloads captured from a real Core, so the merge logic can be tested offline.

The daemon's hardest code is the part that folds Roon's deltas into a zone map,
and it is exactly the part that cannot be exercised without a Core. Recording
real payloads once and replaying them is cheaper than emulating a Core, and it
catches the things an emulator written from the same misunderstanding would not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "spikes" / "fixtures"
sys.path.insert(0, str(ROOT / "backend"))


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def zones_body() -> dict:
    return load("zones")


def a_zone(state: str | None = None) -> dict:
    zones = zones_body()["zones"]
    if state:
        return next(z for z in zones if z.get("state") == state)
    return zones[0]
