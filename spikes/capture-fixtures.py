#!/usr/bin/env python3
"""Reconnect with the saved token and capture real payloads as test fixtures.

Proves the silent-reconnect path (no approval second time round) and records the
shapes the UI depends on -- especially `three_line`, which is the only track
metadata Roon gives an extension.

    python3 spikes/capture-fixtures.py [host] [port]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from moo import Moo, MooError  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.0.2.10"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9330
HERE = Path(__file__).parent
OUT = HERE / "fixtures"
OUT.mkdir(exist_ok=True)

REGINFO = {
    "extension_id": "org.omarchy.roon", "display_name": "Roon for Omarchy",
    "display_version": "0.1.0", "publisher": "ph0bos",
    "email": "noreply@omarchy.local",
    "required_services": ["com.roonlabs.transport:2", "com.roonlabs.browse:1",
                          "com.roonlabs.image:1"],
    "optional_services": [], "provided_services": [],
}

tokens = json.loads((HERE / ".roon-token.json").read_text())
moo = Moo(HOST, PORT, timeout=6.0)
moo.request("com.roonlabs.registry:1/info")
info = moo.read()
core_id = (info.body or {})["core_id"]

reg = dict(REGINFO, token=tokens[core_id])
moo.request("com.roonlabs.registry:1/register", reg)
msg = moo.read()
print(f"silent reconnect: {msg}  (no approval needed)  ok={msg.name == 'Registered'}\n")

saved = {}


def save(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2))
    saved[name] = obj
    print(f"  saved fixtures/{name}.json")


def collect(reqid, want=None, limit=1, timeout=8.0):
    """Read until `limit` messages for this request id arrive.

    `want` filters by message name; None accepts any. Subscriptions answer
    "Subscribed", not "Success", which is easy to filter out by accident.
    """
    out, end = [], time.time() + timeout
    while len(out) < limit and time.time() < end:
        try:
            m = moo.read()
        except (MooError, OSError):
            break
        if m.request_id != reqid:
            continue
        if want is None or m.name in want:
            out.append(m)
        else:
            print(f"    (ignored {m})")
    return out


# --- zones ----------------------------------------------------------------
print("subscribe_zones")
rid = moo.request("com.roonlabs.transport:2/subscribe_zones", {"subscription_key": 1})
msgs = collect(rid, limit=1)
zones = []
if msgs and msgs[0].body:
    zones = msgs[0].body.get("zones", [])
    save("zones", msgs[0].body)
    print(f"  {len(zones)} zones:")
    for z in zones:
        np = z.get("now_playing") or {}
        tl = np.get("three_line") or {}
        line = " / ".join(filter(None, [tl.get("line1"), tl.get("line2"), tl.get("line3")]))
        print(f"    {z.get('display_name'):<28} {z.get('state'):<9} "
              f"outputs={len(z.get('outputs') or [])}  {line[:60]}")
else:
    print("  no zone payload")

# --- outputs (volume shapes) ---------------------------------------------
print("\nsubscribe_outputs")
rid = moo.request("com.roonlabs.transport:2/subscribe_outputs", {"subscription_key": 2})
msgs = collect(rid, limit=1)
if msgs and msgs[0].body:
    outs = msgs[0].body.get("outputs", [])
    save("outputs", msgs[0].body)
    print(f"  {len(outs)} outputs:")
    for o in outs:
        v = o.get("volume")
        vs = (f"type={v.get('type')} {v.get('min')}..{v.get('max')} "
              f"value={v.get('value')} step={v.get('step')}") if v else "NO VOLUME CONTROL"
        print(f"    {o.get('display_name'):<28} {vs}")

# --- browse root + hierarchies -------------------------------------------
for hierarchy in ("browse", "albums", "artists", "genres", "playlists"):
    print(f"\nbrowse hierarchy={hierarchy!r}")
    rid = moo.request("com.roonlabs.browse:1/browse",
                      {"hierarchy": hierarchy, "pop_all": True,
                       "multi_session_key": f"spike-{hierarchy}"})
    msgs = collect(rid, want=("Success",), limit=1)
    if not (msgs and msgs[0].body):
        print("  no response"); continue
    lst = msgs[0].body.get("list") or {}
    print(f"  list: {lst.get('title')!r} count={lst.get('count')} hint={lst.get('hint')!r}")
    rid = moo.request("com.roonlabs.browse:1/load",
                      {"hierarchy": hierarchy, "offset": 0, "count": 8,
                       "multi_session_key": f"spike-{hierarchy}"})
    msgs = collect(rid, want=("Success",), limit=1)
    if msgs and msgs[0].body:
        save(f"browse-{hierarchy}", msgs[0].body)
        for it in (msgs[0].body.get("items") or [])[:8]:
            print(f"    - {str(it.get('title'))[:34]:<34} "
                  f"hint={str(it.get('hint')):<12} "
                  f"sub={str(it.get('subtitle'))[:22]:<22} "
                  f"img={'y' if it.get('image_key') else 'n'}")

# --- queue ----------------------------------------------------------------
if zones:
    z = next((x for x in zones if x.get("state") == "playing"), zones[0])
    print(f"\nsubscribe_queue for {z.get('display_name')!r}")
    rid = moo.request("com.roonlabs.transport:2/subscribe_queue",
                      {"subscription_key": 3, "zone_or_output_id": z["zone_id"],
                       "max_item_count": 20})
    msgs = collect(rid, limit=1)
    if msgs and msgs[0].body:
        items = msgs[0].body.get("items", [])
        save("queue", msgs[0].body)
        print(f"  {len(items)} queue items")
        for it in items[:5]:
            tl = it.get("three_line") or {}
            print(f"    - {str(tl.get('line1'))[:40]:<40} {str(tl.get('line2'))[:24]}")

print(f"\ncaptured {len(saved)} fixtures into {OUT}")
moo.close()
