#!/usr/bin/env python3
"""Register as a Roon extension and capture the pairing token.

Registration is the step Mopidy never had: the Core will not hand over a token
until a human approves the extension in Roon Settings > Extensions. Run this,
approve it there, and the token lands in spikes/.roon-token.json.

    python3 spikes/register.py [host] [port]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from moo import Moo, MooError  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.0.2.10"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9330
TOKENS = Path(__file__).parent / ".roon-token.json"

REGINFO = {
    "extension_id":      "org.omarchy.roon",
    "display_name":      "Roon for Omarchy",
    "display_version":   "0.1.0",
    "publisher":         "ph0bos",
    "email":             "noreply@omarchy.local",
    "website":           "https://github.com/ph0bos/omarchy-roon-client",
    "required_services": ["com.roonlabs.transport:2",
                          "com.roonlabs.browse:1",
                          "com.roonlabs.image:1"],
    "optional_services": [],
    "provided_services": [],
}

saved = json.loads(TOKENS.read_text()) if TOKENS.exists() else {}

print(f"connecting to ws://{HOST}:{PORT}/api", flush=True)
moo = Moo(HOST, PORT, timeout=5.0)

moo.request("com.roonlabs.registry:1/info")
info = moo.read()
core_id = (info.body or {}).get("core_id")
print(f"  {info}  core_id={core_id}", flush=True)
print(f"  {(info.body or {}).get('display_name')} "
      f"{(info.body or {}).get('display_version')}\n", flush=True)

reginfo = dict(REGINFO)
if core_id in saved:
    reginfo["token"] = saved[core_id]
    print("reusing saved token\n", flush=True)

print("-> com.roonlabs.registry:1/register", flush=True)
print(f"   as {reginfo['display_name']} ({reginfo['extension_id']})\n", flush=True)
moo.request("com.roonlabs.registry:1/register", reginfo)

print("=" * 62, flush=True)
print(" APPROVE IT NOW:  Roon app -> Settings -> Extensions -> Enable", flush=True)
print(" (no Roon GUI on Linux, so use your phone or another computer)", flush=True)
print("=" * 62 + "\n", flush=True)

deadline = time.time() + 240
while time.time() < deadline:
    try:
        msg = moo.read()
    except MooError as e:
        print(f"connection: {e}", flush=True)
        break
    except OSError:
        continue  # read timeout; keep waiting for approval

    print(f"<- {msg}", flush=True)
    if msg.name == "Registered":
        b = msg.body or {}
        token = b.get("token")
        print("\n" + "=" * 62, flush=True)
        print(" REGISTERED", flush=True)
        print("=" * 62, flush=True)
        for k in ("core_id", "display_name", "display_version"):
            print(f"  {k:<20} {b.get(k)}", flush=True)
        print(f"  {'token':<20} {str(token)[:16]}... ({len(str(token))} chars)", flush=True)
        prov = b.get("provided_services") or []
        print(f"  {'provided_services':<20} {len(prov)}", flush=True)
        for s in prov:
            print(f"      {s}", flush=True)
        saved[b.get("core_id")] = token
        TOKENS.write_text(json.dumps(saved, indent=2))
        print(f"\ntoken saved to {TOKENS}", flush=True)
        moo.close()
        sys.exit(0)
    if msg.body:
        print(f"   {json.dumps(msg.body)[:300]}", flush=True)

print("\nTIMED OUT waiting for approval.", flush=True)
moo.close()
sys.exit(1)
