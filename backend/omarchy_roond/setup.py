"""The rungs between a fresh install and sound in the room.

`bin/omarchy-roon-endpoint doctor` already answers "what is true right now", but
only in a terminal, and the person who most needs it is the person who has not
opened one. This is the same ladder, computed from what the daemon already knows
and served over HTTP so a surface can render it.

The order is the order things must happen in, and each rung says what to do
about itself: "Approved in Roon" on its own is a diagnosis without a treatment.

    1. Core found         the network can see a Core, and it answered
    2. Paired             a token is stored, so reconnects are silent
    3. Approved in Roon   someone has to say yes, on a phone   <- blocks
    4. RoonBridge running this machine is an endpoint at all
    5. Zone visible       the Core can see that endpoint

Rung 3 is the one that traps people. An unapproved extension does not fail --
registration simply never answers -- so it is reported as `blocked` rather than
`failed`: nothing is broken, someone just has to act somewhere else. The daemon's
reconnect loop polls every 3s while in that state, because a human is acting
right then.

Discovery is deliberately not a rung of its own. It is a rung of the first one:
with a host configured by hand, discovery can be entirely broken and everything
still works, so reporting it as a failure would be telling someone to fix
something that is not their problem. It is reported alongside rung 1 instead.
"""
from __future__ import annotations

import subprocess
import time

BRIDGE_UNIT = "omarchy-roon-bridge"

# States a rung can be in:
#   ok       done, nothing to do
#   blocked  waiting on a person, somewhere else
#   pending  not there yet, and not something anyone has been asked for
OK, BLOCKED, PENDING = "ok", "blocked", "pending"

_bridge_cache: tuple[float, bool] = (0.0, False)
_BRIDGE_TTL = 2.0


def bridge_active() -> bool:
    """Is RoonBridge running as this user?

    Cached briefly: the wizard polls, and each answer is a fork and an exec.
    """
    global _bridge_cache
    now = time.monotonic()
    when, value = _bridge_cache
    if now - when < _BRIDGE_TTL:
        return value
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", BRIDGE_UNIT],
            timeout=2, check=False)
        value = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # No systemd, or no user session to ask. Reporting "not running" is the
        # honest answer: we cannot see one.
        value = False
    _bridge_cache = (now, value)
    return value


def rungs(session, bridge=None) -> list[dict]:
    """The ladder, as the interface should draw it.

    `bridge` is injectable so this can be exercised without a systemd session.
    """
    is_bridge_up = bridge_active() if bridge is None else bool(bridge)

    core = getattr(session, "core", None)
    connected = bool(getattr(session, "connected", False))
    core_id = getattr(session, "core_id", None)
    awaiting = getattr(session, "awaiting_approval", None)
    last_error = getattr(session, "last_error", "") or ""
    manual_host = getattr(session, "host", None)

    tokens = getattr(session, "tokens", None)
    paired = bool(core_id and tokens and tokens.get(core_id))

    # A session with no local_zone_id (the demo one) still knows which zone is
    # pinned, and that is the same question at one remove: is there a zone here.
    local_zone = None
    if hasattr(session, "local_zone_id"):
        local_zone = session.local_zone_id()
    elif getattr(session, "pinned_zone_id", None):
        local_zone = session.pinned_zone_id

    found = core is not None
    core_detail = ""
    if found:
        core_detail = f"{core.name} at {core.ip}"
        if not manual_host:
            core_detail += " (found by discovery)"
    elif manual_host:
        core_detail = f"{manual_host} did not answer"
    elif last_error:
        core_detail = last_error

    return [
        {
            "key": "core",
            "title": "Roon Core found",
            "state": OK if found else PENDING,
            "detail": core_detail,
            "fix": "Discovery needs udp/9003, and Omarchy's firewall drops it by "
                   "default. Run: omarchy-roon-endpoint firewall — or start the "
                   "daemon with --host if your Core is in a container.",
        },
        {
            "key": "paired",
            "title": "Paired with the Core",
            "state": OK if paired else PENDING,
            "detail": "A token is stored, so reconnecting is silent" if paired else "",
            "fix": "Pairing happens by itself once the Core answers. Nothing to do.",
        },
        {
            "key": "approved",
            # The one people get stuck on, so it says where to click.
            "title": "Approved in Roon",
            "state": OK if connected else (BLOCKED if awaiting else PENDING),
            "detail": (awaiting or "") if not connected else "Connected",
            "fix": "Open Roon on your phone or another computer, go to "
                   "Settings > Extensions, and enable \"Roon for Omarchy\". "
                   "Roon ships no interface for Linux, so this cannot be done "
                   "from this machine.",
        },
        {
            "key": "bridge",
            "title": "RoonBridge running",
            "state": OK if is_bridge_up else PENDING,
            "detail": "" if is_bridge_up else f"{BRIDGE_UNIT}.service is not active",
            "fix": "Run: omarchy-roon-endpoint start — or omarchy-roon-endpoint "
                   "install if this machine has never been set up as an endpoint.",
        },
        {
            "key": "zone",
            "title": "This machine visible as a zone",
            "state": OK if local_zone else PENDING,
            "detail": "" if local_zone else "No zone here yet",
            "fix": "In Roon: Settings > Audio, find this machine and Enable it. "
                   "A bridge that has just started can take a minute to appear.",
        },
    ]


def summary(session, bridge=None) -> dict:
    """What `/setup` serves: the ladder, and the rung to point at."""
    # A session may answer for itself. `--demo` does: it has no Core to pair
    # with and no bridge of its own, so computing the ladder from a real
    # machine's systemd would open the wizard over a demo that is working
    # perfectly -- and the wizard is the one surface that must never cry wolf.
    own = getattr(session, "setup_summary", None)
    if callable(own):
        return own()

    ladder = rungs(session, bridge=bridge)
    unfinished = [r for r in ladder if r["state"] != OK]

    # A blocked rung wins over an earlier pending one, and the approval gate is
    # exactly why. Pairing happens DURING registration, so someone waiting for
    # approval has an unfinished "paired" rung above a blocked "approved" one --
    # and "first unfinished" would point them at the one rung whose fix reads
    # "nothing to do" while the thing actually stopping them sits below it.
    blocked = [r for r in unfinished if r["state"] == BLOCKED]
    target = blocked[0] if blocked else (unfinished[0] if unfinished else None)

    return {
        "ready": not unfinished,
        "blocked_on": target["key"] if target else None,
        "rungs": ladder,
    }
