"""The first-run ladder, in each state someone can actually be stuck in.

The wizard is the one surface a new user meets before anything works, so its
input has to be right when nothing else is: no Core, no approval, no bridge. All
five rungs are computed from what the daemon already knows, and the systemd
lookup is injected so this runs anywhere.
"""
from __future__ import annotations

from omarchy_roond import setup


class FakeTokens:
    def __init__(self, tokens=None):
        self._tokens = tokens or {}

    def get(self, core_id):
        return self._tokens.get(core_id)


class FakeCore:
    ip, http_port, name = "10.0.0.5", 9330, "the Core"


class FakeSession:
    """A daemon in whatever state the test needs."""

    def __init__(self, **state):
        self.core = None
        self.core_id = None
        self.connected = False
        self.awaiting_approval = None
        self.last_error = ""
        self.host = None
        self.tokens = FakeTokens()
        self._local_zone = None
        for key, value in state.items():
            setattr(self, key, value)

    def local_zone_id(self):
        return self._local_zone


def by_key(ladder):
    return {r["key"]: r for r in ladder}


def a_working_session():
    return FakeSession(core=FakeCore(), core_id="core-1", connected=True,
                       tokens=FakeTokens({"core-1": "t"}), _local_zone="z1")


# -- the ladder ------------------------------------------------------------
def test_the_rungs_are_in_the_order_things_must_happen():
    ladder = setup.rungs(FakeSession(), bridge=False)
    assert [r["key"] for r in ladder] == ["core", "paired", "approved",
                                          "bridge", "zone"]


def test_a_fresh_install_has_nothing_done_and_blames_nobody():
    ladder = by_key(setup.rungs(FakeSession(), bridge=False))
    assert all(r["state"] == setup.PENDING for r in ladder.values())
    # Pending, not blocked: nobody has been asked for anything yet.
    assert all(r["state"] != setup.BLOCKED for r in ladder.values())
    assert "udp/9003" in ladder["core"]["fix"]


def test_every_rung_says_what_to_do_about_itself():
    """"Approved in Roon" on its own is a diagnosis without a treatment."""
    for rung in setup.rungs(FakeSession(), bridge=False):
        assert rung["fix"], f"{rung['key']} has no fix"
        assert rung["title"]


def test_awaiting_approval_is_blocked_not_failed():
    """Nothing is broken -- someone has to say yes on another device."""
    session = FakeSession(core=FakeCore(), core_id="core-1",
                          tokens=FakeTokens({"core-1": "t"}),
                          awaiting_approval="waiting for approval in Roon")
    ladder = by_key(setup.rungs(session, bridge=True))
    assert ladder["approved"]["state"] == setup.BLOCKED
    assert "waiting for approval" in ladder["approved"]["detail"]
    assert "Settings > Extensions" in ladder["approved"]["fix"]
    # And the rungs before it are done, so it is clear where the ladder stops.
    assert ladder["core"]["state"] == setup.OK
    assert ladder["paired"]["state"] == setup.OK


def test_pairing_needs_a_token_for_this_core():
    """A token for a different Core is not a pairing with this one."""
    session = FakeSession(core=FakeCore(), core_id="core-1",
                          tokens=FakeTokens({"another-core": "t"}))
    assert by_key(setup.rungs(session, bridge=False))["paired"]["state"] == setup.PENDING


def test_a_found_core_says_which_one_and_how():
    ladder = by_key(setup.rungs(a_working_session(), bridge=True))
    assert "the Core" in ladder["core"]["detail"]
    assert "discovery" in ladder["core"]["detail"]


def test_a_manual_host_is_not_credited_to_discovery():
    """With a host configured by hand, discovery can be broken and unimportant."""
    session = a_working_session()
    session.host = "10.0.0.5"
    ladder = by_key(setup.rungs(session, bridge=True))
    assert "discovery" not in ladder["core"]["detail"]


def test_a_host_that_did_not_answer_says_so():
    session = FakeSession(host="10.0.0.9")
    assert "10.0.0.9" in by_key(setup.rungs(session, bridge=False))["core"]["detail"]


def test_the_bridge_rung_follows_systemd():
    session = a_working_session()
    assert by_key(setup.rungs(session, bridge=True))["bridge"]["state"] == setup.OK
    down = by_key(setup.rungs(session, bridge=False))["bridge"]
    assert down["state"] == setup.PENDING
    assert "omarchy-roon-bridge" in down["detail"]


def test_a_session_without_a_local_zone_lookup_falls_back_to_the_pin():
    """The demo session has no hostname matching to do, but it has a zone."""
    class Demo:
        core, core_id, connected = FakeCore(), "demo", True
        pinned_zone_id = "demo-zone-0"
        tokens = FakeTokens({"demo": "t"})

    assert by_key(setup.rungs(Demo(), bridge=True))["zone"]["state"] == setup.OK


# -- the summary -----------------------------------------------------------
def test_summary_points_at_the_first_thing_in_the_way():
    session = FakeSession(core=FakeCore(), core_id="core-1",
                          tokens=FakeTokens({"core-1": "t"}),
                          awaiting_approval="waiting")
    result = setup.summary(session, bridge=True)
    assert result["ready"] is False
    assert result["blocked_on"] == "approved"


def test_a_blocked_rung_wins_over_an_earlier_pending_one():
    """The approval gate is exactly this case, and it is easy to get wrong.

    Pairing happens DURING registration, so someone waiting for approval has an
    unfinished "paired" rung ABOVE a blocked "approved" one. Pointing at the
    first unfinished rung would send them to the one whose fix reads "nothing to
    do" while the thing actually stopping them sits below it.
    """
    session = FakeSession(core=FakeCore(), core_id="core-1",
                          awaiting_approval="waiting for approval in Roon")
    result = setup.summary(session, bridge=False)
    ladder = by_key(result["rungs"])
    assert ladder["paired"]["state"] == setup.PENDING
    assert ladder["approved"]["state"] == setup.BLOCKED
    assert result["blocked_on"] == "approved"


def test_summary_is_ready_only_when_every_rung_is_done():
    result = setup.summary(a_working_session(), bridge=True)
    assert result["ready"] is True and result["blocked_on"] is None
    assert len(result["rungs"]) == 5


def test_a_missing_systemd_reports_not_running_rather_than_raising(monkeypatch):
    """No user session to ask is not a crash; it is "we cannot see one"."""
    setup._bridge_cache = (0.0, False)

    def boom(*a, **k):
        raise OSError("no systemctl here")

    monkeypatch.setattr(setup.subprocess, "run", boom)
    assert setup.bridge_active() is False
    setup._bridge_cache = (0.0, False)
