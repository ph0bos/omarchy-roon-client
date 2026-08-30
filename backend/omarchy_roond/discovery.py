"""Finding a Roon Core, in three tiers, because multicast is not reliable.

Tier 1 is Roon's own SOOD: a query to 239.255.90.90:9003 plus per-interface
broadcast. It is what `node-roon-api/sood.js` does, and it is right when the
network cooperates.

Tier 2 exists because on the development network it does not. The Core answers a
*unicast* SOOD query on 9003 perfectly while ignoring multicast and broadcast
entirely -- the signature of a Core in a bridge-networked container, which is how
Roon is commonly run on a NAS. So when tier 1 finds nothing, probe hosts directly.
Targeted, not a flood: a blind 254-address sweep reproducibly gets no reply, so
prescan for the TCP ports a Core listens on and query only those.

Tier 3 is a host the user typed. Even then SOOD supplies the port, so the user is
never asked for one.
"""
from __future__ import annotations

import socket
import struct
import subprocess
import time
import uuid

SERVICE_ID = "00720724-5143-4a9b-abac-0e50cba674bb"
GROUP = "239.255.90.90"
PORT = 9003

# Ports a Core listens on. 9330 also serves the Display web app and is, on every
# Core seen so far, the extension API port too.
CORE_TCP_PORTS = (9330, 9200, 9100)


class Core:
    """A Core as SOOD describes it."""

    def __init__(self, ip: str, props: dict):
        self.ip = ip
        self.unique_id = props.get("unique_id") or ""
        self.name = props.get("name") or ip
        self.display_version = props.get("display_version") or ""
        self.http_port = int(props.get("http_port") or 0)
        self.props = props

    def __repr__(self) -> str:
        return f"<Core {self.name} {self.ip}:{self.http_port} {self.unique_id[:8]}>"


def _tlv(key: str, value: str) -> bytes:
    k, v = key.encode(), value.encode()
    return bytes([len(k)]) + k + struct.pack(">H", len(v)) + v


def query_message(tid: str | None = None) -> bytes:
    """A SOOD query. `_tid` must be fresh for every query.

    `sood.js:84` assigns `uuid.v4()` when the caller does not supply one, and that
    is not decoration: the Core deduplicates on `_tid` and answers a repeat with
    silence. Reusing a constant makes the first query of a process succeed and
    every one after it look like "no Core on the network" -- which is also why a
    254-address sweep that sends one identical datagram per host fails to find a
    Core sitting right there.
    """
    return (b"SOOD\x02Q" + _tlv("query_service_id", SERVICE_ID)
            + _tlv("_tid", tid or str(uuid.uuid4())))


def parse(buf: bytes) -> tuple[str | None, dict]:
    if buf[:4] != b"SOOD" or len(buf) < 6 or buf[4] != 2:
        return None, {}
    kind, i, props = chr(buf[5]), 6, {}
    while i < len(buf):
        name_len = buf[i]
        i += 1
        if name_len == 0 or i + name_len > len(buf):
            break
        name = buf[i:i + name_len].decode("utf-8", "replace")
        i += name_len
        if i + 2 > len(buf):
            break
        value_len = struct.unpack(">H", buf[i:i + 2])[0]
        i += 2
        if value_len == 0xFFFF:
            props[name] = None
            continue
        props[name] = buf[i:i + value_len].decode("utf-8", "replace")
        i += value_len
    return kind, props


def interfaces() -> list[tuple[str, int]]:
    """Non-loopback IPv4 addresses as (ip, prefix_length)."""
    found = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return found
    for line in out.splitlines():
        fields = line.split()
        if len(fields) > 3 and fields[2] == "inet":
            ip, prefix = fields[3].split("/")
            if not ip.startswith("127."):
                found.append((ip, int(prefix)))
    return found


def _broadcast(ip: str, prefix: int) -> str:
    n = struct.unpack(">I", socket.inet_aton(ip))[0]
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return socket.inet_ntoa(struct.pack(">I", (n & mask) | (~mask & 0xFFFFFFFF)))


def _hosts(ip: str, prefix: int, limit: int = 512) -> list[str]:
    if prefix < 22:               # bigger than a /22 is not worth sweeping
        return []
    n = struct.unpack(">I", socket.inet_aton(ip))[0]
    net = n & ((0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF)
    size = min(2 ** (32 - prefix) - 1, limit)
    return [socket.inet_ntoa(struct.pack(">I", net + h)) for h in range(1, size)]


def _listen(sock: socket.socket, seen: dict, deadline: float,
            stop_after: int = 0) -> None:
    """Collect SOOD replies until the deadline, or until `stop_after` cores."""
    while time.time() < deadline:
        sock.settimeout(max(0.05, deadline - time.time()))
        try:
            data, addr = sock.recvfrom(8192)
        except (TimeoutError, OSError):
            continue
        kind, props = parse(data)
        if kind == "R" and props.get("service_id") == SERVICE_ID:
            seen.setdefault(addr[0], Core(addr[0], props))
            if stop_after and len(seen) >= stop_after:
                return


def broadcast_discover(timeout: float = 3.0) -> list[Core]:
    """Tier 1. Standard SOOD over multicast and broadcast."""
    nics = interfaces()
    if not nics:
        return []

    seen: dict[str, Core] = {}
    socks = []

    # Replies come back to the query's source port, so the sending socket must
    # listen too -- sood.js registers a 'message' handler on send_sock for exactly
    # this reason, and missing it makes discovery look broken when it is not.
    for ip, prefix in nics:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            sock.bind((ip, 0))
        except OSError:
            sock.close()
            continue
        for dest in ((GROUP, PORT), ("255.255.255.255", PORT), (_broadcast(ip, prefix), PORT)):
            try:
                sock.sendto(query_message(), dest)   # fresh _tid per datagram
            except OSError:
                pass
        socks.append(sock)

    deadline = time.time() + timeout
    for sock in socks:
        _listen(sock, seen, deadline)
        sock.close()
    return list(seen.values())


def probe(ip: str, timeout: float = 2.0) -> Core | None:
    """Unicast SOOD to one host. The reply carries the API port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query_message(), (ip, PORT))
        seen: dict[str, Core] = {}
        _listen(sock, seen, time.time() + timeout, stop_after=1)
        return seen.get(ip)
    except OSError:
        return None
    finally:
        sock.close()


def _has_core_ports(ip: str, timeout: float = 0.3) -> bool:
    for port in CORE_TCP_PORTS:
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            if sock.connect_ex((ip, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            sock.close()
    return False


def targeted_discover(timeout: float = 2.0) -> list[Core]:
    """Tier 2. TCP-prescan the local subnet, then unicast SOOD the candidates."""
    from concurrent.futures import ThreadPoolExecutor

    candidates: list[str] = []
    for ip, prefix in interfaces():
        hosts = _hosts(ip, prefix)
        if not hosts:
            continue
        with ThreadPoolExecutor(max_workers=128) as pool:
            candidates += [h for h, ok in zip(hosts, pool.map(_has_core_ports, hosts)) if ok]

    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(candidates))) as pool:
        found = pool.map(lambda ip: probe(ip, timeout=timeout), candidates)
    return [c for c in found if c]


def discover(host: str | None = None, timeout: float = 3.0) -> list[Core]:
    """All three tiers, cheapest first. Prefers a Core on this machine."""
    if host:
        core = probe(host, timeout=timeout)
        return [core] if core else []

    cores = broadcast_discover(timeout=timeout)
    if not cores:
        cores = targeted_discover()

    # A Core on localhost is this machine's own, and is always the right default.
    local = {ip for ip, _ in interfaces()} | {"127.0.0.1"}
    cores.sort(key=lambda c: (c.ip not in local, c.name))
    return cores
