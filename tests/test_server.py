"""Integration tests for the local API.

A real `ApiServer` on a real socket, driven over real HTTP and a real WebSocket
handshake -- but with a fake session in place of a Roon Core, so the whole
request/response and push path is exercised in CI with nothing on the network.

The fake implements exactly the seam `RoonSession` exposes. That is the point of
keeping the seam narrow: five verbs is a cheap thing to double.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.client import HTTPConnection

import pytest
from _fixtures import load, zones_body
from omarchy_roond.moo import MooError
from omarchy_roond.queue import QueueStore
from omarchy_roond.server import ApiServer
from omarchy_roond.zones import ZoneStore


class FakeCore:
    ip, http_port, name, display_version = "10.0.0.5", 9330, "fakecore", "2.70"


class FakeSession:
    """The RoonSession seam, doubled."""

    def __init__(self, connected: bool = True):
        self.connected = connected
        self.core = FakeCore() if connected else None
        self.core_id = "fake-core-id" if connected else None
        self.zones = ZoneStore()
        self.zones.apply("Subscribed", zones_body())
        self.queue = QueueStore()
        self.queue.reset(self.zones.all()[0]["zone_id"])
        self.queue.apply("Subscribed", load("queue"))
        self._pinned = None
        self.calls: list[tuple] = []
        self.raises: Exception | None = None
        self.on_zones = self.on_connected = None
        self.on_disconnected = self.on_awaiting_approval = None
        self.on_queue = None

    def _reply(self, verb, *args):
        self.calls.append((verb, *args))
        if self.raises:
            raise self.raises
        return type("Msg", (), {"name": "Success", "body": {"ok": True}})()

    @property
    def pinned_zone_id(self):
        if self._pinned and self._pinned in self.zones:
            return self._pinned
        zones = self.zones.all()
        return zones[0]["zone_id"] if zones else None

    def pinned_zone(self):
        zid = self.pinned_zone_id
        return self.zones.summary(zid) if zid else None

    def pin(self, zone_id):
        self._pinned = zone_id
        self.calls.append(("pin", zone_id))

    def control(self, zone_id, action):
        return self._reply("control", zone_id, action)

    def seek(self, zone_id, seconds, how="absolute"):
        return self._reply("seek", zone_id, seconds, how)

    def change_volume(self, output_id, value, how="absolute"):
        return self._reply("volume", output_id, value, how)

    def mute(self, output_id, muted):
        return self._reply("mute", output_id, muted)

    def change_settings(self, zone_id, **settings):
        return self._reply("settings", zone_id, settings)

    def play_from_here(self, zone_id, queue_item_id):
        return self._reply("play_from_here", zone_id, queue_item_id)

    def browse(self, hierarchy="browse", **opts):
        self.calls.append(("browse", hierarchy, opts))
        if self.raises:
            raise self.raises
        return type("Msg", (), {"name": "Success",
                                "body": {"action": "list",
                                         "list": {"title": "Albums", "count": 2}}})()

    def load(self, hierarchy="browse", offset=0, count=100, **opts):
        self.calls.append(("load", hierarchy, offset, count, opts))
        if self.raises:
            raise self.raises
        return type("Msg", (), {"name": "Success",
                                "body": {"items": [], "offset": offset}})()


@pytest.fixture
def api():
    session = FakeSession()
    server = ApiServer(session, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, session, server.server_address[1]
    server.shutdown()
    server.server_close()


def request(port, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    conn.request(method, path, payload, headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, (json.loads(raw) if raw else None)


# -- HTTP ------------------------------------------------------------------
def test_health(api):
    _, _, port = api
    status, body = request(port, "GET", "/health")
    assert status == 200
    assert body["ok"] is True and body["connected"] is True
    assert body["zones"] == len(zones_body()["zones"])


def test_state_publishes_the_core_image_base(api):
    """QML builds art URLs from this and talks to the Core directly."""
    _, _, port = api
    status, body = request(port, "GET", "/state")
    assert status == 200
    assert body["image_base"] == "http://10.0.0.5:9330/api/image"
    assert body["core"]["name"] == "fakecore"
    assert len(body["zones"]) == len(zones_body()["zones"])


def test_zones_and_one_zone(api):
    _, session, port = api
    _, body = request(port, "GET", "/zones")
    zone_id = body["zones"][0]["zone_id"]
    status, one = request(port, "GET", f"/zones/{zone_id}")
    assert status == 200 and one["zone_id"] == zone_id
    assert one["track"]["title"]


def test_unknown_zone_is_404(api):
    _, _, port = api
    assert request(port, "GET", "/zones/nope")[0] == 404


def test_unknown_route_is_404(api):
    _, _, port = api
    assert request(port, "GET", "/nonsense")[0] == 404
    assert request(port, "POST", "/nonsense", {})[0] == 404


def test_control_reaches_the_session(api):
    _, session, port = api
    status, body = request(port, "POST", "/control",
                           {"zone_id": "z1", "action": "playpause"})
    assert status == 200 and body["name"] == "Success"
    assert session.calls[-1] == ("control", "z1", "playpause")


def test_volume_and_seek_and_settings(api):
    _, session, port = api
    request(port, "POST", "/volume", {"output_id": "o1", "value": 42})
    assert session.calls[-1] == ("volume", "o1", 42.0, "absolute")
    request(port, "POST", "/seek", {"zone_id": "z1", "seconds": 30})
    assert session.calls[-1] == ("seek", "z1", 30.0, "absolute")
    request(port, "POST", "/settings", {"zone_id": "z1", "auto_radio": True})
    assert session.calls[-1] == ("settings", "z1", {"auto_radio": True})


def test_settings_without_any_setting_is_rejected(api):
    _, _, port = api
    status, body = request(port, "POST", "/settings", {"zone_id": "z1"})
    assert status == 400 and "no settings" in body["error"]


def test_missing_fields_are_400_not_500(api):
    _, _, port = api
    status, body = request(port, "POST", "/control", {"zone_id": "z1"})
    assert status == 400 and "action" in body["error"]


def test_browse_and_load_pass_options_through(api):
    _, session, port = api
    request(port, "POST", "/browse",
            {"hierarchy": "albums", "pop_all": True, "multi_session_key": "k"})
    assert session.calls[-1] == ("browse", "albums",
                                 {"pop_all": True, "multi_session_key": "k"})
    request(port, "POST", "/load", {"hierarchy": "albums", "offset": 10, "count": 5})
    assert session.calls[-1] == ("load", "albums", 10, 5, {})


# -- browsing --------------------------------------------------------------
def test_page_does_the_browse_and_the_load_in_one_request(api):
    """The pair is one move of a stateful cursor; two requests cannot promise
    that nothing else moved it in between."""
    _, session, port = api
    status, body = request(port, "POST", "/page",
                           {"session_key": "library", "hierarchy": "albums",
                            "item_key": "12:1", "count": 5})
    assert status == 200
    assert [c[0] for c in session.calls] == ["browse", "load"]
    assert session.calls[0][2]["multi_session_key"] == "library"
    assert session.calls[0][2]["item_key"] == "12:1"
    assert body["session_key"] == "library" and body["hierarchy"] == "albums"


def test_page_defaults_the_zone_to_the_pin(api):
    """An action item plays into a zone, and the pinned one is this machine's."""
    _, session, port = api
    request(port, "POST", "/page", {"session_key": "library"})
    assert session.calls[0][2]["zone_or_output_id"] == session.pinned_zone_id


def test_page_without_a_session_key_is_400(api):
    """Sharing a cursor by accident is the bug this route exists to prevent."""
    _, _, port = api
    status, body = request(port, "POST", "/page", {"hierarchy": "albums"})
    assert status == 400 and "session_key" in body["error"]


def test_an_unknown_hierarchy_is_400_not_500(api):
    _, _, port = api
    status, body = request(port, "POST", "/page",
                           {"session_key": "s", "hierarchy": "everything"})
    assert status == 400 and "hierarchy" in body["error"]


# -- first-run setup -------------------------------------------------------
def test_setup_serves_the_ladder(api):
    """The wizard's whole input, so it never has to send anyone to a terminal."""
    _, session, port = api
    status, body = request(port, "GET", "/setup")
    assert status == 200
    assert [r["key"] for r in body["rungs"]] == ["core", "paired", "approved",
                                                 "bridge", "zone"]
    # This fake is connected to a Core but was never paired and has no bridge,
    # so the ladder stops at the first thing that is actually missing.
    assert body["ready"] is False
    assert body["blocked_on"] == "paired"
    assert all(r["fix"] for r in body["rungs"])


def test_setup_is_readable_while_disconnected():
    """It is most needed exactly when nothing works, so it is not a write."""
    session = FakeSession(connected=False)
    server = ApiServer(session, host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        status, body = request(port, "GET", "/setup")
        assert status == 200 and body["ready"] is False
        assert body["blocked_on"] == "core"
    finally:
        server.shutdown()
        server.server_close()


# -- the queue -------------------------------------------------------------
def test_queue_is_served_from_the_live_subscription(api):
    """A read of memory, not a round trip to the Core."""
    _, session, port = api
    status, body = request(port, "GET", "/queue")
    assert status == 200
    assert body["zone_id"] == session.zones.all()[0]["zone_id"]
    assert len(body["items"]) == len(load("queue")["items"])
    assert body["items"][0]["title"] == \
        load("queue")["items"][0]["three_line"]["line1"]
    assert session.calls == [], "serving the queue must not call the Core"


def test_play_from_here_reaches_the_session(api):
    _, session, port = api
    status, body = request(port, "POST", "/play_from_here",
                           {"zone_id": "z1", "queue_item_id": 110663})
    assert status == 200 and body["name"] == "Success"
    assert session.calls[-1] == ("play_from_here", "z1", 110663)


def test_play_from_here_defaults_to_the_pinned_zone(api):
    """/queue only ever holds the pinned zone's list, so the verb follows it."""
    _, session, port = api
    request(port, "POST", "/play_from_here", {"queue_item_id": 110663})
    assert session.calls[-1] == ("play_from_here", session.pinned_zone_id, 110663)


def test_play_from_here_without_an_item_is_400(api):
    _, _, port = api
    status, body = request(port, "POST", "/play_from_here", {"zone_id": "z1"})
    assert status == 400 and "queue_item_id" in body["error"]


def test_queue_changes_are_pushed(api):
    _, session, port = api
    sock, _, rest = ws_connect(port)
    try:
        _, rest = read_event(sock, rest)          # the initial state
        session.queue.apply("Changed", {"changes": [
            {"operation": "remove", "index": 0, "count": 1}]})
        session.on_queue(session.queue.zone_id)   # what the read loop does
        event, _ = read_event(sock, rest)
        assert event["type"] == "queue"
        assert event["zone_id"] == session.queue.zone_id
        assert len(event["items"]) == len(load("queue")["items"]) - 1
    finally:
        sock.close()


def test_no_queue_payload_is_built_when_nobody_is_listening(api):
    """Same bargain as zones: ~100 items is not a payload to build for nobody."""
    _, session, port = api
    built = {"n": 0}
    original = session.queue.summary

    def counting_summary():
        built["n"] += 1
        return original()

    session.queue.summary = counting_summary
    for _ in range(10):
        session.on_queue("z1")
    assert built["n"] == 0


def test_core_errors_become_502_not_500(api):
    _, session, port = api
    session.raises = MooError("core went away")
    status, body = request(port, "POST", "/control",
                           {"zone_id": "z", "action": "play"})
    assert status == 502 and "core went away" in body["error"]


def test_writes_are_503_while_disconnected():
    session = FakeSession(connected=False)
    server = ApiServer(session, host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        status, body = request(port, "POST", "/control",
                               {"zone_id": "z", "action": "play"})
        assert status == 503 and "not connected" in body["error"]
        # Reads still work, so the interface can render its disconnected state.
        assert request(port, "GET", "/state")[1]["connected"] is False
    finally:
        server.shutdown()
        server.server_close()


# -- WebSocket -------------------------------------------------------------
def ws_connect(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(
        b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        b"Sec-WebSocket-Version: 13\r\n\r\n")
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    head, _, rest = buf.partition(b"\r\n\r\n")
    return sock, head.decode(), rest


def read_event(sock, rest=b""):
    sock.settimeout(5)
    while True:
        if len(rest) >= 2:
            length, offset = rest[1] & 0x7F, 2
            if length == 126:
                length, offset = int.from_bytes(rest[2:4], "big"), 4
            if len(rest) >= offset + length:
                payload, rest = rest[offset:offset + length], rest[offset + length:]
                return json.loads(payload), rest
        rest += sock.recv(65536)


def test_websocket_handshake_and_initial_state(api):
    """A new client is drawn from cold, so it gets the world immediately."""
    _, _, port = api
    sock, head, rest = ws_connect(port)
    try:
        assert "101 Switching Protocols" in head
        assert "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in head
        event, _ = read_event(sock, rest)
        assert event["type"] == "state"
        assert len(event["zones"]) == len(zones_body()["zones"])
    finally:
        sock.close()


def test_websocket_handshake_without_a_key_is_rejected(api):
    _, _, port = api
    status, body = request(port, "GET", "/ws")
    assert status == 400 and "handshake" in body["error"]


def test_zone_changes_are_pushed(api):
    server, session, port = api
    sock, _, rest = ws_connect(port)
    try:
        _, rest = read_event(sock, rest)          # the initial state
        zone_id = session.zones.all()[0]["zone_id"]
        session.zones.apply("Changed", {"zones_seek_changed": [
            {"zone_id": zone_id, "seek_position": 99}]})
        session.on_zones({zone_id})               # what the read loop does
        event, _ = read_event(sock, rest)
        assert event["type"] == "zones"
        assert event["changed"] == [zone_id]
        pushed = next(z for z in event["zones"] if z["zone_id"] == zone_id)
        assert pushed["track"]["seek_position"] == 99
    finally:
        sock.close()


def test_disconnect_is_pushed(api):
    server, session, port = api
    sock, _, rest = ws_connect(port)
    try:
        _, rest = read_event(sock, rest)
        session.on_disconnected("core went away")
        event, _ = read_event(sock, rest)
        assert event == {"type": "disconnected", "reason": "core went away"}
    finally:
        sock.close()


def test_awaiting_approval_is_pushed(api):
    """Rung 3 of the wizard reaches the interface as its own event."""
    server, session, port = api
    sock, _, rest = ws_connect(port)
    try:
        _, rest = read_event(sock, rest)
        session.on_awaiting_approval("approve in Roon Settings")
        event, _ = read_event(sock, rest)
        assert event["type"] == "awaiting_approval"
    finally:
        sock.close()


def test_a_dead_client_does_not_stall_the_hub(api):
    """A client that vanishes must not block the Roon read loop."""
    server, session, port = api
    sock, _, rest = ws_connect(port)
    read_event(sock, rest)
    sock.close()
    time.sleep(0.1)
    for _ in range(3):
        session.on_zones({"whatever"})            # must not raise
    assert request(port, "GET", "/health")[0] == 200


# -- the pinned zone -------------------------------------------------------
def test_state_publishes_the_pinned_zone(api):
    """MPRIS, the media keys and the bar widget all follow this one zone."""
    _, session, port = api
    _, body = request(port, "GET", "/state")
    assert body["pinned_zone_id"] == session.zones.all()[0]["zone_id"]


def test_pin_changes_the_zone(api):
    _, session, port = api
    target = session.zones.all()[2]["zone_id"]
    status, body = request(port, "POST", "/pin", {"zone_id": target})
    assert status == 200 and body["pinned_zone_id"] == target
    assert session.calls[-1] == ("pin", target)


def test_pinning_an_unknown_zone_is_404(api):
    _, _, port = api
    assert request(port, "POST", "/pin", {"zone_id": "nope"})[0] == 404


def test_pin_null_falls_back_to_the_default(api):
    """Un-pinning returns to the default zone; it never leaves nothing pinned."""
    _, session, port = api
    status, body = request(port, "POST", "/pin", {"zone_id": None})
    assert status == 200
    assert body["pinned_zone_id"] == session.zones.all()[0]["zone_id"]


def test_mute_reaches_the_session(api):
    _, session, port = api
    status, body = request(port, "POST", "/mute",
                           {"output_id": "o1", "muted": True})
    assert status == 200 and body["name"] == "Success"
    assert session.calls[-1] == ("mute", "o1", True)


def test_unmute_is_explicit_not_a_missing_flag(api):
    """`muted` defaults to True, so unmuting has to say so."""
    _, session, port = api
    request(port, "POST", "/mute", {"output_id": "o1", "muted": False})
    assert session.calls[-1] == ("mute", "o1", False)
    request(port, "POST", "/mute", {"output_id": "o1"})
    assert session.calls[-1] == ("mute", "o1", True)


def test_mute_without_an_output_is_400(api):
    _, _, port = api
    status, body = request(port, "POST", "/mute", {"muted": True})
    assert status == 400 and "output_id" in body["error"]


def test_no_payload_is_built_when_nobody_is_listening(api):
    """Zone pushes arrive ~1/s while playing and cost ~100x the merge that
    produced them. With no WebSocket client that work is pure waste, and the
    steady state IS no client: QML reads state over MPRIS and a slow poll."""
    server, session, port = api
    built = {"n": 0}
    original = session.zones.summary

    def counting_summary(zone_id):
        built["n"] += 1
        return original(zone_id)

    session.zones.summary = counting_summary
    for _ in range(20):
        session.on_zones({"z"})
    assert built["n"] == 0, "summaries built with no clients attached"


def test_payload_is_built_once_a_client_attaches(api):
    server, session, port = api
    sock, _, rest = ws_connect(port)
    try:
        read_event(sock, rest)
        built = {"n": 0}
        original = session.zones.summary

        def counting_summary(zone_id):
            built["n"] += 1
            return original(zone_id)

        session.zones.summary = counting_summary
        session.on_zones({"z"})
        assert built["n"] == len(session.zones)
    finally:
        sock.close()
