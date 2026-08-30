"""Server-side WebSocket framing.

`moo.py` speaks the client half of RFC 6455 to reach the Core. This is the other
half: the daemon is the server, QML is the client. The rules invert -- frames the
daemon sends must be unmasked, frames it receives must be masked, and a client
that fails to mask is protocol-violating and gets closed.

Small enough to own, and owning it keeps the daemon dependency-free. The pieces
that can be wrong in subtle ways -- the accept-key digest, extended lengths,
unmasking, fragmentation -- are pure functions, and tested as such.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

TEXT, BINARY, CLOSE, PING, PONG, CONTINUATION = 0x1, 0x2, 0x8, 0x9, 0xA, 0x0


def accept_key(client_key: str) -> str:
    """The `Sec-WebSocket-Accept` value for a client's `Sec-WebSocket-Key`."""
    digest = hashlib.sha1((client_key.strip() + GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def handshake_response(client_key: str) -> bytes:
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n\r\n"
    ).encode()


def encode(payload: bytes, opcode: int = TEXT, fin: bool = True) -> bytes:
    """A server frame. Never masked -- masking a server frame is a violation."""
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


def unmask(payload: bytes, mask: bytes) -> bytes:
    return bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class FrameReader:
    """Reads client frames off a blocking file object, reassembling fragments."""

    def __init__(self, rfile):
        self.rfile = rfile

    def _exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                raise ConnectionError("client closed")
            buf += chunk
        return buf

    def read_frame(self) -> tuple[int, bool, bytes]:
        b0, b1 = self._exact(2)
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._exact(8))[0]
        if not masked:
            # RFC 6455 6.1: a client MUST mask. An unmasked client frame is a
            # protocol error, not something to tolerate.
            raise ConnectionError("client frame was not masked")
        mask = self._exact(4)
        return opcode, fin, unmask(self._exact(length), mask) if length else b""

    def read_message(self) -> tuple[int, bytes]:
        """A whole message, following continuation frames to FIN."""
        chunks: list[bytes] = []
        first = None
        while True:
            opcode, fin, payload = self.read_frame()
            if opcode in (PING, PONG, CLOSE):
                return opcode, payload
            if opcode != CONTINUATION:
                first, chunks = opcode, [payload]
            else:
                chunks.append(payload)
            if fin:
                if first is None:
                    raise ConnectionError("continuation with no start frame")
                return first, b"".join(chunks)


def close_frame(code: int = 1000, reason: str = "") -> bytes:
    return encode(struct.pack(">H", code) + reason.encode(), opcode=CLOSE)


def ping_frame() -> bytes:
    return encode(os.urandom(4), opcode=PING)
