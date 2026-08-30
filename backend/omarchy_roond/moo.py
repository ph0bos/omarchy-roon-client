"""Minimal MOO-over-WebSocket client.

The wire format, verified against RoonLabs/node-roon-api:

    transport-websocket.js:13   ws://ip:port/api
    moo.js:65                   MOO/1 REQUEST <name>\\n
                                Request-Id: <n>\\n
                                [Content-Length: N\\nContent-Type: <ct>\\n]
                                \\n<body>

Responses use the same framing with a verb of REQUEST, COMPLETE or CONTINUE and
a name that is the result ("Success", "Registered", "Changed", ...).

This is deliberately the same shape the daemon's `RoonSession` seam will have --
connect, request, read -- so the spikes exercise the real boundary.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
from dataclasses import dataclass, field


@dataclass
class Message:
    verb: str                       # REQUEST | COMPLETE | CONTINUE
    name: str                       # Success | Registered | Changed | ...
    headers: dict = field(default_factory=dict)
    body: dict | None = None

    @property
    def request_id(self) -> int | None:
        v = self.headers.get("Request-Id")
        return int(v) if v is not None else None

    def __str__(self) -> str:
        return f"MOO/1 {self.verb} {self.name}"


class MooError(Exception):
    pass


class Moo:
    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.host, self.port = host, port
        self._buf = b""
        self._reqid = 0
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._handshake()

    # -- WebSocket -------------------------------------------------------
    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        self._sock.sendall(
            f"GET /api HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        while b"\r\n\r\n" not in self._buf:
            self._recv_more()
        head, _, self._buf = self._buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n")[0].decode()
        if "101" not in status:
            raise MooError(f"no websocket upgrade: {status}")

    def _recv_more(self) -> None:
        chunk = self._sock.recv(8192)
        if not chunk:
            raise MooError("connection closed")
        self._buf += chunk

    def _need(self, n: int) -> None:
        while len(self._buf) < n:
            self._recv_more()

    def _send_frame(self, payload: bytes, opcode: int = 0x2) -> None:
        n, mask = len(payload), os.urandom(4)
        if n < 126:
            hdr = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            hdr = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
        self._sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _read_frame(self) -> tuple[int, bool, bytes]:
        self._need(2)
        fin = bool(self._buf[0] & 0x80)
        opcode = self._buf[0] & 0x0F
        ln, off = self._buf[1] & 0x7F, 2
        if ln == 126:
            self._need(4); ln = struct.unpack(">H", self._buf[2:4])[0]; off = 4
        elif ln == 127:
            self._need(10); ln = struct.unpack(">Q", self._buf[2:10])[0]; off = 10
        self._need(off + ln)
        payload = self._buf[off:off + ln]
        self._buf = self._buf[off + ln:]
        return opcode, fin, payload

    def _read_message_bytes(self) -> bytes:
        """Reassemble a whole WebSocket message.

        Zone payloads are far larger than one frame, so the Core fragments them:
        a first frame with the real opcode and FIN=0, then continuation frames
        (opcode 0x0) until FIN=1. Reading frames as if each were a message
        yields truncated JSON and silently loses every zone update.
        """
        chunks: list[bytes] = []
        first_opcode = None
        while True:
            opcode, fin, payload = self._read_frame()
            if opcode == 0x9:                       # ping, may interleave
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode == 0xA:                       # pong
                continue
            if opcode == 0x8:
                raise MooError("server closed the connection")
            if opcode != 0x0:                       # start of a new message
                first_opcode = opcode
                chunks = [payload]
            else:                                   # continuation
                chunks.append(payload)
            if fin:
                if first_opcode is None:
                    raise MooError("continuation frame with no start frame")
                return b"".join(chunks)

    # -- MOO -------------------------------------------------------------
    def request(self, name: str, body: dict | None = None) -> int:
        reqid = self._reqid
        self._reqid += 1
        hdr = f"MOO/1 REQUEST {name}\nRequest-Id: {reqid}\n"
        if body is not None:
            raw = json.dumps(body).encode()
            hdr += f"Content-Length: {len(raw)}\nContent-Type: application/json\n"
            self._send_frame(hdr.encode() + b"\n" + raw)
        else:
            self._send_frame((hdr + "\n").encode())
        return reqid

    def read(self) -> Message:
        """Next MOO message, reassembling fragments and answering pings."""
        while True:
            payload = self._read_message_bytes()
            if not payload:
                continue
            head, _, raw = payload.partition(b"\n\n")
            lines = head.decode("utf-8", "replace").splitlines()
            parts = lines[0].split(" ", 2)
            verb = parts[1] if len(parts) > 1 else "?"
            name = parts[2] if len(parts) > 2 else ""
            headers = {}
            for line in lines[1:]:
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
            body = None
            if raw and headers.get("Content-Type", "").startswith("application/json"):
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
            return Message(verb, name, headers, body)

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=0x8)
        except OSError:
            pass
        self._sock.close()
