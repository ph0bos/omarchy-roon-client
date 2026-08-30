"""The daemon's local API: what QML actually talks to.

HTTP for requests, one WebSocket for pushes. The split matters: browse and
control are call-and-response and belong on HTTP, while zone state arrives
unbidden from the Core and has to be pushed. This is the same shape
`MopidyRpc.js` consumed in the TIDAL plugin, so the QML side is familiar ground.

Album art is deliberately absent. The Core serves it directly, so `/state`
publishes `image_base` and QML points `Image` straight at the Core -- no proxy,
no cache to write, and Qt's own image cache does the work.

Bound to 127.0.0.1. Nothing here authenticates, because nothing here is
reachable from off the machine; that is the same bargain Mopidy's HTTP frontend
makes.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import wire
from .moo import MooError

MAX_BODY = 1 << 20


class Hub:
    """Fan-out to every connected WebSocket client.

    A client that has gone away must not stall the Roon read loop, so a failed
    write drops that client rather than raising.
    """

    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = threading.Lock()

    def add(self, client) -> None:
        with self._lock:
            self._clients.add(client)

    def remove(self, client) -> None:
        with self._lock:
            self._clients.discard(client)

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, event: dict) -> None:
        frame = wire.encode(json.dumps(event).encode())
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.send_raw(frame)
            except OSError:
                self.remove(client)


class Client:
    """One WebSocket connection, with a lock so broadcasts cannot interleave."""

    def __init__(self, wfile):
        self.wfile = wfile
        self._lock = threading.Lock()

    def send_raw(self, frame: bytes) -> None:
        with self._lock:
            self.wfile.write(frame)
            self.wfile.flush()


def snapshot(session) -> dict:
    """Everything the interface needs to draw itself from cold."""
    core = session.core
    return {
        "connected": session.connected,
        "core": None if core is None else {
            "id": session.core_id,
            "name": core.name,
            "ip": core.ip,
            "port": core.http_port,
            "version": core.display_version,
        },
        # QML builds art URLs itself: <image_base>/<key>?scale=fit&width=..&height=..
        "image_base": None if core is None else
        f"http://{core.ip}:{core.http_port}/api/image",
        # Which zone stands for "this machine" -- what MPRIS, the media keys and
        # the bar widget all follow.
        "pinned_zone_id": session.pinned_zone_id,
        "notifications": getattr(session, "notifications", False),
        # Present only when the pinned zone is this machine's own endpoint.
        "output_format": (session.output_format()
                          if hasattr(session, "output_format") else None),
        "zones": [session.zones.summary(z["zone_id"]) for z in session.zones.all()],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "omarchy-roond"

    # Quiet by default: one line per request drowns journalctl once zone updates
    # start flowing.
    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------
    @property
    def session(self):
        return self.server.session

    def _json(self, payload, status: int = 200) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _require(self, body: dict, *keys):
        missing = [k for k in keys if not body.get(k)]
        if missing:
            raise KeyError(", ".join(missing))
        return [body[k] for k in keys]

    # -- routes ----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/ws":
            return self._websocket()
        if path == "/health":
            return self._json({
                "ok": True,
                "connected": self.session.connected,
                "zones": len(self.session.zones),
                "clients": self.server.hub.count(),
            })
        if path == "/state":
            return self._json(snapshot(self.session))
        if path == "/zones":
            return self._json({"zones": snapshot(self.session)["zones"]})
        if path.startswith("/demo-art/"):
            from .demo import demo_cover_bytes
            data = demo_cover_bytes()
            if not data:
                return self._error(404, "no demo cover")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(data)
            return None
        if path.startswith("/palette/"):
            # Deliberately its own route rather than part of /state: the first
            # look at a sleeve costs a fetch and a decode, and /state is polled.
            # Surfaces ask for this once per track change and it is cached after.
            key = path[len("/palette/"):]
            result = self.session.art_palette(key)
            return self._json(result if result else {"color": None, "luma": 0.0,
                                                     "isLight": False})
        if path.startswith("/zones/"):
            summary = self.session.zones.summary(path[len("/zones/"):])
            return self._json(summary) if summary else self._error(404, "no such zone")
        return self._error(404, "no such route")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            body = self._body()
        except ValueError as e:
            return self._error(400, f"bad body: {e}")

        if not self.session.connected:
            return self._error(503, "not connected to a Core")

        try:
            if path == "/notifications":
                notifier = self.server.notifier
                # `suppress` is transient and not persisted: it exists so a
                # surface that already shows the track can silence the duplicate
                # card while it is open.
                if "suppress" in body:
                    if notifier is not None:
                        notifier.suppressed = bool(body["suppress"])
                    return self._json({
                        "notifications": self.session.notifications,
                        "suppressed": bool(body["suppress"]),
                    })
                if "enabled" not in body:
                    return self._error(400, "missing: enabled or suppress")
                self.session.set_notifications(bool(body["enabled"]))
                if notifier is not None:
                    notifier.enabled = self.session.notifications
                return self._json({"notifications": self.session.notifications})
            if path == "/pin":
                zone_id = body.get("zone_id")     # null un-pins, back to local
                if zone_id and zone_id not in self.session.zones:
                    return self._error(404, "no such zone")
                self.session.pin(zone_id)
                return self._json({"pinned_zone_id": self.session.pinned_zone_id})
            if path == "/control":
                zone_id, action = self._require(body, "zone_id", "action")
                reply = self.session.control(zone_id, action)
            elif path == "/seek":
                (zone_id,) = self._require(body, "zone_id")
                reply = self.session.seek(zone_id, float(body.get("seconds", 0)),
                                          body.get("how", "absolute"))
            elif path == "/volume":
                output_id, value = self._require(body, "output_id", "value")
                reply = self.session.change_volume(output_id, float(value),
                                                   body.get("how", "absolute"))
            elif path == "/mute":
                (output_id,) = self._require(body, "output_id")
                reply = self.session.mute(output_id, bool(body.get("muted", True)))
            elif path == "/settings":
                (zone_id,) = self._require(body, "zone_id")
                settings = {k: body[k] for k in ("shuffle", "loop", "auto_radio")
                            if k in body}
                if not settings:
                    return self._error(400, "no settings given")
                reply = self.session.change_settings(zone_id, **settings)
            elif path == "/browse":
                opts = {k: v for k, v in body.items() if k != "hierarchy"}
                reply = self.session.browse(body.get("hierarchy", "browse"), **opts)
            elif path == "/load":
                opts = {k: v for k, v in body.items()
                        if k not in ("hierarchy", "offset", "count")}
                reply = self.session.load(body.get("hierarchy", "browse"),
                                          int(body.get("offset", 0)),
                                          int(body.get("count", 100)), **opts)
            else:
                return self._error(404, "no such route")
        except KeyError as e:
            return self._error(400, f"missing: {e.args[0]}")
        except (TypeError, ValueError) as e:
            return self._error(400, str(e))
        except MooError as e:
            return self._error(502, str(e))

        return self._json({"name": reply.name, "body": reply.body})

    # -- websocket -------------------------------------------------------
    def _websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or (self.headers.get("Upgrade") or "").lower() != "websocket":
            return self._error(400, "not a websocket handshake")

        self.wfile.write(wire.handshake_response(key))
        self.wfile.flush()

        client = Client(self.wfile)
        self.server.hub.add(client)
        # A new client is drawn from cold, so hand it the world immediately
        # rather than leaving it blank until the next zone change.
        #
        # Any failure here must close the socket. The 101 has already gone out,
        # so a client that gets neither a frame nor a close waits forever -- a
        # hung UI with no error anywhere, which is worse than a refused upgrade.
        try:
            client.send_raw(wire.encode(json.dumps(
                {"type": "state", **snapshot(self.session)}).encode()))
        except Exception:                                        # noqa: BLE001
            self.server.hub.remove(client)
            try:
                self.wfile.write(wire.close_frame(1011, "internal error"))
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True
            return

        reader = wire.FrameReader(self.rfile)
        try:
            while True:
                opcode, payload = reader.read_message()
                if opcode == wire.CLOSE:
                    break
                if opcode == wire.PING:
                    client.send_raw(wire.encode(payload, opcode=wire.PONG))
                # Clients have nothing to say; everything they need is on HTTP.
        except (ConnectionError, OSError):
            pass
        finally:
            self.server.hub.remove(client)
            self.close_connection = True


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, session, host: str = "127.0.0.1", port: int = 9821,
                 verbose: bool = False):
        super().__init__((host, port), Handler)
        self.session = session
        self.hub = Hub()
        self.notifier = None
        self.verbose = verbose
        self._wire_session()

    def _wire_session(self) -> None:
        session = self.session

        def on_zones(touched):
            # Zone pushes arrive about once a second while anything is playing,
            # and building the payload costs ~100x the merge that produced it.
            # With no WebSocket client attached that work is pure waste -- and
            # the steady state IS no client, because QML reads zone state over
            # MPRIS and a slow poll rather than the socket.
            if self.hub.count() == 0:
                return
            self.hub.broadcast({
                "type": "zones",
                "changed": sorted(touched),
                "zones": [session.zones.summary(z["zone_id"])
                          for z in session.zones.all()],
            })

        session.on_zones = on_zones
        session.on_connected = lambda body: self.hub.broadcast(
            {"type": "connected", **snapshot(session)})
        session.on_disconnected = lambda why: self.hub.broadcast(
            {"type": "disconnected", "reason": why})
        session.on_awaiting_approval = lambda why: self.hub.broadcast(
            {"type": "awaiting_approval", "reason": why})

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"
