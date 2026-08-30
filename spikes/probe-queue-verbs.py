"""Does the transport service let an extension edit a queue? Ask the Core.

Sends each candidate verb with an EMPTY body. A verb that exists rejects the
body by naming the field it wanted; a verb that does not exist is refused with
no body at all. Neither touches the queue, which is the point -- this is safe to
run against a Core someone is listening to.

Run it with the daemon stopped: it registers as the same extension.

    systemctl --user stop omarchy-roond
    python spikes/probe-queue-verbs.py
    systemctl --user start omarchy-roond

Answer, against Roon 2.70: play_from_here is the only queue verb there is.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from omarchy_roond.moo import MooError  # noqa: E402
from omarchy_roond.session import RoonSession  # noqa: E402

s = RoonSession()
if not s.connect():
    print("could not connect")
    raise SystemExit(1)

import threading  # noqa: E402

threading.Thread(target=s._pump, daemon=True).start()
time.sleep(1.0)

candidates = [
    "definitely_not_a_method",     # the control: what "unknown" looks like
    "remove_from_queue",
    "move_in_queue",
    "reorder_queue",
    "clear_queue",
    "play_from_here",              # the control: a verb we know exists
]
for name in candidates:
    try:
        reply = s.call(f"com.roonlabs.transport:2/{name}", {}, timeout=6)
        print(f"{name:26} -> {reply.name}  {reply.body}")
    except MooError as e:
        print(f"{name:26} -> ERROR {e}")
s.stop()
