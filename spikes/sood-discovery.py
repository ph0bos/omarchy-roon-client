#!/usr/bin/env python3
"""SOOD discovery spike: can this machine see a Roon Core?

Framing verified against RoonLabs/node-roon-api/sood.js:
    "SOOD" + 0x02 + 'Q' + TLVs (1-byte name len, 2-byte BE value len)

Replies are received on BOTH the 9003 socket and the sending socket, because
sood.js registers a 'message' handler on send_sock too -- the Core answers to the
query's source port, not to 9003.
Read-only. Delete once the daemon has real discovery.
"""
import select, socket, struct, subprocess, sys, time

SERVICE = "00720724-5143-4a9b-abac-0e50cba674bb"
GROUP, PORT = "239.255.90.90", 9003


def tlv(k, v):
    kb, vb = k.encode(), v.encode()
    return bytes([len(kb)]) + kb + struct.pack(">H", len(vb)) + vb


def parse(buf):
    if buf[:4] != b"SOOD" or len(buf) < 6 or buf[4] != 2:
        return None, {}
    kind, i, out = chr(buf[5]), 6, {}
    while i < len(buf):
        ln = buf[i]; i += 1
        if ln == 0 or i + ln > len(buf):
            break
        name = buf[i:i + ln].decode("utf-8", "replace"); i += ln
        if i + 2 > len(buf):
            break
        vl = struct.unpack(">H", buf[i:i + 2])[0]; i += 2
        if vl == 0xFFFF:
            out[name] = None; continue
        out[name] = buf[i:i + vl].decode("utf-8", "replace"); i += vl
    return kind, out


def ifaces():
    out = []
    try:
        raw = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in raw.splitlines():
            f = line.split()
            if len(f) > 3 and f[2] == "inet":
                ip, plen = f[3].split("/")
                if not ip.startswith("127."):
                    out.append((f[1], ip, int(plen)))
    except Exception as e:
        print("  (interface enumeration failed:", e, ")")
    return out


def bcast(ip, plen):
    n = struct.unpack(">I", socket.inet_aton(ip))[0]
    m = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
    return socket.inet_ntoa(struct.pack(">I", (n & m) | (~m & 0xFFFFFFFF)))


nics = ifaces()
print("interfaces:")
for n, ip, p in nics:
    print(f"  {n:<12} {ip}/{p}  broadcast {bcast(ip, p)}")
if not nics:
    print("  none"); sys.exit(2)

# Mirror node-roon-api/sood.js exactly: per interface, a recv_sock bound to 9003
# with multicast membership, AND a send_sock bound to (iface_ip, 0) which also
# listens -- the Core replies to the query's source port, not to 9003.
socks = {}

rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
except (AttributeError, OSError):
    pass
try:
    rx.bind(("0.0.0.0", PORT))
    socks[rx] = f"recv 0.0.0.0:{PORT}"
    print(f"\nrecv socket bound to 0.0.0.0:{PORT}")
except OSError as e:
    print(f"\ncannot bind {PORT}: {e}")
for _, ip, _ in nics:
    try:
        rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                      socket.inet_aton(GROUP) + socket.inet_aton(ip))
        print(f"  joined {GROUP} on {ip}")
    except OSError as e:
        print(f"  join FAILED on {ip}: {e}")

senders = []
for name, ip, plen in nics:
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    tx.bind((ip, 0))
    socks[tx] = f"send {ip}:{tx.getsockname()[1]}"
    senders.append((tx, ip, plen))
    print(f"  send socket on {ip}:{tx.getsockname()[1]} (also listening)")

msg = b"SOOD\x02Q" + tlv("query_service_id", SERVICE) + tlv("_tid", "omarchy-spike")

print("\nsending SOOD query:")
for tx, ip, plen in senders:
    for dest in [(GROUP, PORT), ("255.255.255.255", PORT), (bcast(ip, plen), PORT)]:
        try:
            tx.sendto(msg, dest)
            print(f"  ok    {ip} -> {dest[0]}:{dest[1]}")
        except OSError as e:
            print(f"  FAIL  {ip} -> {dest[0]}:{dest[1]}  {e}")

print("\nwaiting 8s on all sockets ...")
seen, t0 = {}, time.time()
while time.time() - t0 < 8:
    ready, _, _ = select.select(list(socks), [], [], 1.0)
    for sk in ready:
        try:
            data, addr = sk.recvfrom(8192)
        except OSError:
            continue
        kind, fields = parse(data)
        if kind == "Q":
            continue  # our own query, looped back
        if addr[0] not in seen:
            seen[addr[0]] = (kind, fields)
            print(f"  <- {addr[0]}:{addr[1]} on [{socks[sk]}] type={kind!r}")

if not seen:
    print("\nno reply to multicast/broadcast -- falling back to a unicast sweep")
    print("(a Core in a bridge-networked container never sees the broadcast,")
    print(" but answers a unicast SOOD query on 9003 perfectly well)\n")
    # A dedicated socket: unreachable hosts return ICMP port-unreachable, and
    # those pending errors surface on recvfrom. Keep them off the multicast
    # sockets, and report them rather than swallowing them.
    sw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sw.bind((nics[0][1], 0))
    sw.setblocking(False)

    for _, ip, plen in nics:
        net = struct.unpack(">I", socket.inet_aton(ip))[0] & ((0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF)
        hosts = [socket.inet_ntoa(struct.pack(">I", net + h))
                 for h in range(1, 2 ** (32 - plen) - 1)]
        sent = 0
        for h in hosts:
            try:
                sw.sendto(msg, (h, PORT)); sent += 1
            except OSError:
                pass          # pending ICMP from a previous host; keep going
            time.sleep(0.002)  # gentle, and lets replies interleave
        print(f"  swept {sent}/{len(hosts)} hosts on {ip}/{plen}")

    errs = 0
    t1 = time.time()
    while time.time() - t1 < 6:
        ready, _, _ = select.select([sw], [], [], 0.5)
        for sk in ready:
            try:
                data, addr = sk.recvfrom(8192)
            except ConnectionRefusedError:
                errs += 1; continue   # ICMP unreachable from a dead host
            except OSError:
                errs += 1; continue
            kind, fields = parse(data)
            if kind == "Q":
                continue
            if addr[0] not in seen:
                seen[addr[0]] = (kind, fields)
                print(f"  <- {addr[0]}:{addr[1]} type={kind!r}")
    if errs:
        print(f"  ({errs} ICMP unreachable from empty addresses, expected)")

print()
if not seen:
    print("RESULT: no Roon Core answered, multicast or unicast.")
    sys.exit(1)
for ip, (kind, fields) in seen.items():
    print(f"RESULT: Core at {ip}  (SOOD type {kind!r})")
    for k, v in sorted(fields.items()):
        print(f"    {k:<26} {v}")
print(f"\ncores_found {len(seen)}")
