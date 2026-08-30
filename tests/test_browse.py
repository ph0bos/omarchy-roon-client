"""Browsing: the cursor rules, and what happens when two surfaces share a wire.

The browse API is stateful in a way that does not survive being treated as
request/response. Everything here is about that: a page is two calls, they must
happen together, and the reply is not always a list.
"""
from __future__ import annotations

import threading
import time

import pytest
from _fixtures import load
from omarchy_roond import browse


class Reply:
    def __init__(self, body):
        self.name, self.body = "Success", body


class FakeSession:
    """A Core that answers browse and load, and records the order it was asked."""

    def __init__(self, browse_body=None, load_body=None, delay=0.0):
        self.calls: list[tuple] = []
        self.browse_body = browse_body if browse_body is not None else {
            "action": "list", "list": load("browse-albums")["list"]}
        self.load_body = load_body if load_body is not None else load("browse-albums")
        self.delay = delay
        self.pinned_zone_id = "z1"

    def browse(self, hierarchy="browse", **opts):
        self.calls.append(("browse", hierarchy, opts))
        if self.delay:
            time.sleep(self.delay)
        return Reply(self.browse_body)

    def load(self, hierarchy="browse", offset=0, count=100, **opts):
        self.calls.append(("load", hierarchy, offset, count, opts))
        return Reply(self.load_body)


@pytest.fixture
def keys():
    return browse.SessionKeys()


# -- one move of the cursor ------------------------------------------------
def test_a_page_is_a_browse_then_a_load(keys):
    session = FakeSession()
    result = browse.page(session, keys, "surface-1", hierarchy="albums")
    assert [c[0] for c in session.calls] == ["browse", "load"]
    assert result["action"] == "list"
    assert result["list"]["title"] == "Albums"
    assert len(result["items"]) == len(load("browse-albums")["items"])
    assert result["items"][0]["item_key"]


def test_both_halves_carry_the_same_session_key(keys):
    """The load reads wherever THAT cursor is; a mismatched key reads another."""
    session = FakeSession()
    browse.page(session, keys, "search-surface", hierarchy="albums")
    assert session.calls[0][2]["multi_session_key"] == "search-surface"
    assert session.calls[1][4]["multi_session_key"] == "search-surface"


def test_pushing_into_an_item_passes_its_key(keys):
    session = FakeSession()
    browse.page(session, keys, "s", hierarchy="albums", item_key="12:1")
    assert session.calls[0][2]["item_key"] == "12:1"


def test_search_sends_what_was_typed(keys):
    """Search is a conversation: browse the prompt item again with the input."""
    session = FakeSession()
    browse.page(session, keys, "s", hierarchy="search", item_key="9:0",
                input="nocturne")
    assert session.calls[0][2]["input"] == "nocturne"


def test_pop_all_starts_from_the_top(keys):
    session = FakeSession()
    browse.page(session, keys, "s", hierarchy="artists", pop_all=True)
    assert session.calls[0][2]["pop_all"] is True


def test_a_zone_travels_with_the_browse(keys):
    """"Play Now" acts on the zone the session was told about."""
    session = FakeSession()
    browse.page(session, keys, "s", zone_id="z9")
    assert session.calls[0][2]["zone_or_output_id"] == "z9"


def test_a_window_is_asked_for_by_offset_and_count(keys):
    session = FakeSession()
    browse.page(session, keys, "s", hierarchy="albums", offset=200, count=50)
    assert session.calls[1][2] == 200 and session.calls[1][3] == 50


def test_the_offset_reported_is_the_core_s_own(keys):
    """A list shorter than the window ends where the Core says, not where we asked."""
    session = FakeSession(load_body={"items": [], "offset": 17})
    assert browse.page(session, keys, "s", offset=999)["offset"] == 17


# -- replies that are not lists --------------------------------------------
def test_a_message_reply_is_not_loaded(keys):
    """There is no list to read, and loading would move a cursor that did not."""
    session = FakeSession(browse_body={"action": "message", "message": "Not found",
                                       "is_error": True})
    result = browse.page(session, keys, "s")
    assert [c[0] for c in session.calls] == ["browse"]
    assert result["action"] == "message"
    assert result["message"] == "Not found" and result["is_error"] is True
    assert result["items"] == [] and result["list"] is None


def test_an_unknown_action_is_passed_through_rather_than_guessed(keys):
    """Only the list path is verified against a live Core; the rest are honest."""
    session = FakeSession(browse_body={"action": "replace_item",
                                       "item": {"title": "Favourited"}})
    result = browse.page(session, keys, "s")
    assert result["action"] == "replace_item"
    assert result["item"]["title"] == "Favourited"
    assert [c[0] for c in session.calls] == ["browse"]


# -- the cursor is stateful, and that is the whole problem ------------------
def test_two_requests_on_one_key_do_not_interleave(keys):
    """HTTP gives no ordering between two requests; the cursor demands it.

    Without the lock the calls arrive browse, browse, load, load -- and the
    second browse has moved the cursor before the first request reads it, so
    one caller gets the other's page.
    """
    session = FakeSession(delay=0.05)
    threads = [threading.Thread(target=browse.page,
                               args=(session, keys, "shared"),
                               kwargs={"hierarchy": "albums"})
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    order = [c[0] for c in session.calls]
    assert order == ["browse", "load", "browse", "load"], order


def test_different_keys_are_free_to_overlap(keys):
    """Search must not wait behind a library page; that is why keys exist."""
    session = FakeSession(delay=0.05)
    started = time.monotonic()
    threads = [threading.Thread(target=browse.page,
                               args=(session, keys, f"surface-{i}"))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started
    assert elapsed < 0.15, f"serialised across distinct keys ({elapsed:.2f}s)"


# -- guards ----------------------------------------------------------------
def test_an_unknown_hierarchy_is_refused(keys):
    with pytest.raises(ValueError, match="unknown hierarchy"):
        browse.page(FakeSession(), keys, "s", hierarchy="everything")


def test_the_window_is_clamped_to_something_a_core_will_answer(keys):
    session = FakeSession()
    browse.page(session, keys, "s", offset=-5, count=10_000)
    assert session.calls[1][2] == 0
    assert session.calls[1][3] == browse.MAX_COUNT
