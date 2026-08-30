"""The queue store's merge rules, and the one subscription that feeds it.

Two things are being protected here. The first is the merge itself, driven from
`spikes/fixtures/queue.json` -- a real `Subscribed` payload, so the display-line
parsing is tested against what a Core actually sends. The second is the
subscription discipline: exactly one queue subscription, following the pinned
zone, re-subscribed only when the pin moves. A queue that re-subscribes on every
zone message would issue one round trip per second per playing zone.
"""
from __future__ import annotations

import pytest
from _fixtures import a_zone, load, zones_body
from omarchy_roond.queue import QueueStore
from omarchy_roond.session import QUEUE_SUBSCRIPTION_KEY, RoonSession


def queue_body() -> dict:
    return load("queue")


def an_item(queue_item_id: int = 999) -> dict:
    return {"queue_item_id": queue_item_id, "length": 100,
            "three_line": {"line1": "Inserted", "line2": "Someone",
                           "line3": "An Album"}}


# -- the merge -------------------------------------------------------------
def test_subscribed_replaces_everything():
    store = QueueStore()
    store.apply("Subscribed", {"items": [an_item()]})
    assert store.apply("Subscribed", queue_body()) is True
    assert len(store) == len(queue_body()["items"])
    assert store.all()[0]["queue_item_id"] == queue_body()["items"][0]["queue_item_id"]


def test_summary_parses_the_display_lines():
    """Queue items carry `three_line` exactly as `now_playing` does."""
    store = QueueStore()
    store.reset("z1")
    store.apply("Subscribed", queue_body())
    summary = store.summary()
    assert summary["zone_id"] == "z1"
    first, raw = summary["items"][0], queue_body()["items"][0]
    assert first["title"] == raw["three_line"]["line1"]
    assert first["artist"] == raw["three_line"]["line2"]
    assert first["album"] == raw["three_line"]["line3"]
    assert first["queue_item_id"] == raw["queue_item_id"]
    assert first["length"] == raw["length"]
    assert first["image_key"] == raw["image_key"]


def test_remove_takes_a_run_out_of_the_middle():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    before = [i["queue_item_id"] for i in store.all()]
    assert store.apply("Changed", {"changes": [
        {"operation": "remove", "index": 2, "count": 3}]}) is True
    assert [i["queue_item_id"] for i in store.all()] == before[:2] + before[5:]


def test_insert_puts_items_at_an_index():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    before = [i["queue_item_id"] for i in store.all()]
    assert store.apply("Changed", {"changes": [
        {"operation": "insert", "index": 1, "items": [an_item(42)]}]}) is True
    assert [i["queue_item_id"] for i in store.all()] == \
        before[:1] + [42] + before[1:]


def test_changes_apply_in_order():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    before = [i["queue_item_id"] for i in store.all()]
    store.apply("Changed", {"changes": [
        {"operation": "remove", "index": 0, "count": 1},
        {"operation": "insert", "index": 0, "items": [an_item(7)]},
    ]})
    assert [i["queue_item_id"] for i in store.all()] == [7] + before[1:]


def test_an_unknown_operation_goes_stale_rather_than_guessing():
    """Only `Subscribed` is verified against a live Core; the edits are not.

    A list quietly out of step with the Core is worse than one that re-fetches,
    so an operation we do not recognise stops the merge and raises the flag the
    session re-subscribes on.
    """
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    before = [i["queue_item_id"] for i in store.all()]
    store.apply("Changed", {"changes": [
        {"operation": "reorder_or_whatever", "index": 0},
        {"operation": "remove", "index": 0, "count": 4},
    ]})
    assert store.stale is True
    assert [i["queue_item_id"] for i in store.all()] == before, \
        "changes after an unknown operation were applied anyway"


def test_unsubscribed_empties_the_list():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    assert store.apply("Unsubscribed", None) is True
    assert len(store) == 0 and store.all() == []


def test_an_empty_change_list_is_not_a_change():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    assert store.apply("Changed", {"changes": []}) is False
    assert store.apply("Changed", {"changes": [
        {"operation": "remove", "index": 0, "count": 0}]}) is False


def test_reset_points_at_a_new_zone_holding_nothing():
    store = QueueStore()
    store.apply("Subscribed", queue_body())
    store.stale = True
    store.reset("z2")
    assert store.zone_id == "z2" and len(store) == 0 and store.stale is False


# -- the subscription ------------------------------------------------------
class FakeMoo:
    """Records requests. A subscription is a send; nothing here waits."""

    def __init__(self):
        self.sent: list[tuple] = []
        self._next = 1

    def request(self, name, body=None):
        self.sent.append((name, body))
        reqid, self._next = self._next, self._next + 1
        return reqid

    def close(self):
        pass


class Msg:
    def __init__(self, name, body):
        self.name, self.body = name, body


@pytest.fixture
def session(tmp_path):
    s = RoonSession()
    s._config_path = tmp_path / "config.json"
    s._moo = FakeMoo()
    s.connected = True
    # An explicit pin, so the test does not depend on this machine's hostname
    # matching a zone name.
    s._pinned_zone_id = a_zone()["zone_id"]
    return s


def subscribes(moo) -> list[dict]:
    return [body for name, body in moo.sent if name.endswith("/subscribe_queue")]


def zone_message() -> Msg:
    return Msg("Subscribed", zones_body())


def test_the_first_zone_message_subscribes_to_the_pinned_queue(session):
    session._on_zone_message(zone_message())
    assert subscribes(session._moo) == [{
        "subscription_key": QUEUE_SUBSCRIPTION_KEY,
        "zone_or_output_id": session.pinned_zone_id,
        "max_item_count": 100,
    }]


def test_further_zone_messages_do_not_resubscribe(session):
    """Zone messages arrive ~1/s while anything is playing."""
    for _ in range(5):
        session._on_zone_message(zone_message())
    assert len(subscribes(session._moo)) == 1


def test_the_queue_follows_the_pin(session):
    session._on_zone_message(zone_message())
    other = zones_body()["zones"][2]["zone_id"]
    session.pin(other)
    names = [name.rsplit("/", 1)[1] for name, _ in session._moo.sent]
    assert names[-2:] == ["unsubscribe_queue", "subscribe_queue"]
    assert subscribes(session._moo)[-1]["zone_or_output_id"] == other
    assert session.queue.zone_id == other


def test_a_stale_queue_resubscribes(session):
    session._on_zone_message(zone_message())
    session.queue.apply("Subscribed", queue_body())
    session._on_queue_message(Msg("Changed", {"changes": [
        {"operation": "something_new", "index": 0}]}))
    assert len(subscribes(session._moo)) == 2
    assert session.queue.stale is False, "resubscribing must clear the flag"
    assert len(session.queue) == 0, "the list is empty until the Core answers"


def test_a_queue_change_reaches_the_callback_once(session):
    seen = []
    session.on_queue = seen.append
    session._on_zone_message(zone_message())
    reqid = session._queue_reqid
    session._streams[reqid](Msg("Subscribed", queue_body()))
    session._streams[reqid](Msg("Changed", {"changes": []}))
    assert seen == [session.pinned_zone_id]


def test_a_reconnect_subscribes_again(session):
    session._on_zone_message(zone_message())
    session.close()
    session.connected = True
    session._moo = FakeMoo()
    session._on_zone_message(zone_message())
    assert len(subscribes(session._moo)) == 1, "reconnect left the queue unsubscribed"


def test_nothing_is_sent_while_disconnected(session):
    session.connected = False
    session.pin(zones_body()["zones"][1]["zone_id"])
    assert session._moo.sent == []


def test_play_from_here_sends_the_queue_item_id(session):
    """There is no "play item n": the Core's own item id is the only handle."""
    sent = {}
    session.call = lambda name, body: sent.update(name=name, body=body)
    session.play_from_here("z1", 110663)
    assert sent["name"] == "com.roonlabs.transport:2/play_from_here"
    assert sent["body"] == {"zone_or_output_id": "z1", "queue_item_id": 110663}
