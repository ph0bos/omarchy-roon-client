"""Server-side WebSocket framing.

Pure functions with a published worked example to check against, so these are
cheap and they catch the things that are painful to debug over a socket.
"""
from __future__ import annotations

import io
import struct

import pytest
from _fixtures import ROOT  # noqa: F401  (prepares sys.path)

from omarchy_roond import wire


def test_accept_key_matches_rfc6455_worked_example():
    """RFC 6455 section 1.3 gives this exact pair."""
    assert wire.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_accept_key_ignores_surrounding_whitespace():
    assert wire.accept_key("  dGhlIHNhbXBsZSBub25jZQ==\n") == \
        wire.accept_key("dGhlIHNhbXBsZSBub25jZQ==")


def test_handshake_response_is_a_101():
    resp = wire.handshake_response("dGhlIHNhbXBsZSBub25jZQ==")
    assert resp.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
    assert b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n" in resp
    assert resp.endswith(b"\r\n\r\n")


@pytest.mark.parametrize("size,header_len", [(0, 2), (125, 2), (126, 4), (65535, 4),
                                             (65536, 10)])
def test_encode_picks_the_right_length_form(size, header_len):
    frame = wire.encode(b"x" * size)
    assert len(frame) == header_len + size
    assert frame[0] == 0x81                      # FIN + text


def test_server_frames_are_never_masked():
    """Masking a server frame is a protocol violation, not a style choice."""
    assert wire.encode(b"hello")[1] & 0x80 == 0


def test_unmask_round_trips():
    mask = b"\x01\x02\x03\x04"
    assert wire.unmask(wire.unmask(b"payload", mask), mask) == b"payload"


def _client_frame(payload: bytes, opcode: int = wire.TEXT, fin: bool = True) -> bytes:
    mask = b"\xaa\xbb\xcc\xdd"
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    else:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    return head + mask + wire.unmask(payload, mask)


def test_frame_reader_unmasks_a_client_frame():
    reader = wire.FrameReader(io.BytesIO(_client_frame(b"ping me")))
    assert reader.read_message() == (wire.TEXT, b"ping me")


def test_frame_reader_reassembles_fragments():
    """The bug that cost a debugging session against the Core, in reverse."""
    stream = (_client_frame(b"one ", fin=False)
              + _client_frame(b"two ", opcode=wire.CONTINUATION, fin=False)
              + _client_frame(b"three", opcode=wire.CONTINUATION, fin=True))
    reader = wire.FrameReader(io.BytesIO(stream))
    assert reader.read_message() == (wire.TEXT, b"one two three")


def test_frame_reader_handles_extended_length():
    payload = b"y" * 300
    reader = wire.FrameReader(io.BytesIO(_client_frame(payload)))
    assert reader.read_message() == (wire.TEXT, payload)


def test_unmasked_client_frame_is_rejected():
    unmasked = bytes([0x81, 0x02]) + b"hi"
    with pytest.raises(ConnectionError, match="not masked"):
        wire.FrameReader(io.BytesIO(unmasked)).read_message()


def test_truncated_stream_raises_rather_than_hanging():
    with pytest.raises(ConnectionError):
        wire.FrameReader(io.BytesIO(b"\x81")).read_message()


def test_close_frame_carries_the_code():
    frame = wire.close_frame(1001, "going away")
    assert frame[0] & 0x0F == wire.CLOSE
    assert struct.unpack(">H", frame[2:4])[0] == 1001
