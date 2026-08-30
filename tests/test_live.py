"""Live tests against a real Roon Core. Opt-in, never run in CI.

    ROON_LIVE_HOST=192.0.2.10 pytest tests/test_live.py -v

These are the only tests that can catch a protocol change on Roon's side, so they
exist -- but they need a Core, a paired token and a network, none of which a CI
runner has. They are read-only: nothing here starts playback in someone's house.
"""
from __future__ import annotations

import os
import threading
import time

import pytest
from _fixtures import ROOT  # noqa: F401
from omarchy_roond import discovery
from omarchy_roond.session import RoonSession

HOST = os.environ.get("ROON_LIVE_HOST")

pytestmark = pytest.mark.skipif(
    not HOST, reason="set ROON_LIVE_HOST to run live tests against a Core")


@pytest.fixture(scope="module")
def session():
    s = RoonSession(host=HOST)
    ready = threading.Event()
    s.on_connected = lambda body: ready.set()
    threading.Thread(target=s.run_forever, daemon=True).start()
    assert ready.wait(30), "could not connect (is the extension approved?)"
    time.sleep(1.5)
    yield s
    s.stop()


def test_discovery_is_repeatable():
    """Guards the `_tid` bug: a constant tid makes every query after the first
    silently fail, which looks exactly like an empty network."""
    for _ in range(3):
        assert discovery.probe(HOST) is not None


def test_discovery_reports_the_api_port():
    core = discovery.probe(HOST)
    assert core.http_port > 0
    assert core.unique_id


def test_connects_and_registers_silently(session):
    """A stored token means no second approval, which is what makes
    Restart=always acceptable on the unit."""
    assert session.connected
    assert session.core_id


def test_zones_arrive_and_parse(session):
    assert len(session.zones) > 0
    for zone in session.zones.all():
        summary = session.zones.summary(zone["zone_id"])
        assert summary["name"]
        assert summary["state"] in ("playing", "paused", "loading", "stopped")


def test_browse_root_and_a_hierarchy(session):
    session.browse("browse", pop_all=True, multi_session_key="test-root")
    page = session.load("browse", count=10, multi_session_key="test-root")
    titles = [i["title"] for i in page.body["items"]]
    assert titles, "browse root came back empty"

    session.browse("albums", pop_all=True, multi_session_key="test-albums")
    albums = session.load("albums", count=5, multi_session_key="test-albums")
    assert albums.body["list"]["count"] > 0


def test_separate_session_keys_do_not_disturb_each_other(session):
    """The multi_session_key gotcha, proven rather than assumed."""
    session.browse("albums", pop_all=True, multi_session_key="a")
    session.browse("artists", pop_all=True, multi_session_key="b")
    a = session.load("albums", count=1, multi_session_key="a")
    b = session.load("artists", count=1, multi_session_key="b")
    assert a.body["list"]["title"] != b.body["list"]["title"]


def test_image_urls_point_at_the_core(session):
    zone = next((z for z in session.zones.all()
                 if (z.get("now_playing") or {}).get("image_key")), None)
    if zone is None:
        pytest.skip("no zone has artwork right now")
    key = zone["now_playing"]["image_key"]
    url = session.image_url(key, 300, 300)
    assert url.startswith(f"http://{session.core.ip}:{session.core.http_port}/api/image/")
    assert "width=300" in url
