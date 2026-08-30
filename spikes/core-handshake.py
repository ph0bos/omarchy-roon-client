#!/usr/bin/env python3
"""Prove the MOO stack end to end without discovery.

Opens a WebSocket to ws://HOST:PORT/api and sends
`com.roonlabs.registry:1/info`, which the Core answers before any pairing or
approval. A COMPLETE Success here means transport, framing and the Core are all
good, and only discovery is broken.

Wire format verified against RoonLabs/node-roon-api:
  moo.js:65               "MOO/1 REQUEST <name>\\nRequest-Id: N\\n...\\n\\n<body>"
  transport-websocket.js  ws://ip:port/api
"""
import base64, json, os, socket, struct, sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.0.2.10"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9330


def ws_handshake(s, host, port):
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /api HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            raise ConnectionError("closed during handshake")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode()
    if "101" not in status:
        raise ConnectionError(f"no upgrade: {status}")
    return status, rest


def ws_send(s, payload):
    """Client frames must be masked (RFC 6455)."""
    n, mask = len(payload), os.urandom(4)
    if n < 126:
        hdr = bytes([0x82, 0x80 | n])
    elif n < 65536:
        hdr = bytes([0x82, 0x80 | 126]) + struct.pack(">H", n)
    else:
        hdr = bytes([0x82, 0x80 | 127]) + struct.pack(">Q", n)
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def ws_recv(s, buf=b""):
    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = s.recv(4096)
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
    need(2)
    ln = buf[1] & 0x7F
    off = 2
    if ln == 126:
        need(4); ln = struct.unpack(">H", buf[2:4])[0]; off = 4
    elif ln == 127:
        need(10); ln = struct.unpack(">Q", buf[2:10])[0]; off = 10
    need(off + ln)
    payload, buf = buf[off:off + ln], buf[off + ln:]
    return payload, buf


def moo_request(name, reqid, body=None):
    hdr = f"MOO/1 REQUEST {name}\nRequest-Id: {reqid}\n"
    if body is not None:
        raw = json.dumps(body).encode()
        hdr += f"Content-Length: {len(raw)}\nContent-Type: application/json\n"
        return hdr.encode() + b"\n" + raw
    return (hdr + "\n").encode()


print(f"connecting to ws://{HOST}:{PORT}/api")
s = socket.socket(); s.settimeout(10)
s.connect((HOST, PORT))
status, leftover = ws_handshake(s, HOST, PORT)
print(f"  {status}")

print("\n-> MOO/1 REQUEST com.roonlabs.registry:1/info")
ws_send(s, moo_request("com.roonlabs.registry:1/info", 0))

payload, leftover = ws_recv(s, leftover)
head, _, body = payload.partition(b"\n\n")
print("\n<- headers")
for line in head.decode("utf-8", "replace").splitlines():
    print(f"     {line}")
if body:
    print("\n<- body")
    try:
        for k, v in sorted(json.loads(body).items()):
            print(f"     {k:<22} {v}")
    except Exception:
        print("    ", body[:400])

ok = b"Success" in head
print("\nRESULT:", "MOO round-trip OK — transport and Core are healthy"
      if ok else "unexpected response")
s.close()
sys.exit(0 if ok else 1)
