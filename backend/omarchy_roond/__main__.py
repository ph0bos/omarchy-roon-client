"""End-to-end exercise of the daemon's Roon side.

    python -m omarchy_roond                 discover, connect, stream zone changes
    python -m omarchy_roond --host 1.2.3.4  skip discovery
    python -m omarchy_roond --browse        walk the browse root and each hierarchy
    python -m omarchy_roond --control "Lounge:playpause"

Prints what the interface would render, so the wiring can be judged before any
QML exists.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from . import discovery
from .session import RoonSession

BOLD, DIM, GREEN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def clock(seconds: float) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(session: RoonSession) -> None:
    print(f"\n{BOLD}zones{RESET}  ({len(session.zones)})")
    for zone in session.zones.all():
        s = session.zones.summary(zone["zone_id"])
        state = s["state"]
        colour = GREEN if state == "playing" else (YELLOW if state == "paused" else DIM)
        track = s["track"]
        pos = f"{clock(track['seek_position'])}/{clock(track['length'])}" if track["length"] else ""
        line = f"{track['title']} · {track['artist']}" if track["title"] else "—"
        print(f"  {colour}{state:<8}{RESET} {BOLD}{s['name']:<28}{RESET} "
              f"{line[:52]:<52} {DIM}{pos}{RESET}")
        for out in s["outputs"]:
            if out["standby"]:
                vol = f"{DIM}standby{RESET}"
            elif out["bounds"]:
                lo, hi = out["bounds"]
                vol = f"vol {out['volume']['value']:g} of {lo:g}–{hi:g}"
                if hi < out["volume"]["max"]:
                    vol += f" {YELLOW}(limited from {out['volume']['max']:g}){RESET}"
            else:
                vol = f"{DIM}no volume control{RESET}"
            print(f"           {DIM}└{RESET} {out['name']:<26} {vol}")


def serve(args) -> int:
    """Run the daemon proper: one Roon session, one local API for QML."""
    from .mpris import MprisPlayer
    from .notify import Notifier
    from .server import ApiServer

    if args.demo:
        # Screenshots of the real thing show a hostname, the layout of someone's
        # house in the zone list, and their listening history. Running against
        # stand-in values means none of that is ever written to a file.
        from .demo import DemoSession
        session = DemoSession(port=args.api_port)
    else:
        session = RoonSession(host=args.host, port=args.port)
    api = ApiServer(session, port=args.api_port, verbose=args.verbose)

    # MPRIS is what gives the endpoint a bar presence: Omarchy already ships a
    # generic MPRIS bar widget and routes media keys through it, so publishing
    # one player is the whole of R1's UI. It chains onto the server's own zone
    # callback rather than replacing it.
    player = MprisPlayer(session)
    notifier = Notifier(session, enabled=session.notifications)
    api.notifier = notifier

    mpris_ok = player.start()
    notify_ok = notifier.start()
    if not mpris_ok:
        print(f"{YELLOW}no MPRIS:{RESET} {player.error or 'unknown reason'}")
    if not notify_ok:
        print(f"{YELLOW}no notifications:{RESET} {notifier.error or 'unknown reason'}")

    # One zone push feeds all three surfaces: WebSocket clients, the MPRIS
    # player, and the track announcement.
    push_to_clients = session.on_zones

    def on_zones(touched):
        push_to_clients(touched)
        if mpris_ok:
            player.publish()
        if notify_ok:
            notifier.on_zones(touched)

    session.on_zones = on_zones

    # The session owns the callbacks the server registered; the CLI must not
    # steal them, so log through the hub's events rather than reassigning.
    threading.Thread(target=session.run_forever, daemon=True).start()
    print(f"{BOLD}omarchy-roond{RESET} listening on {GREEN}{api.url}{RESET}")
    print(f"  {DIM}GET  /health /state /zones /zones/<id>{RESET}")
    print(f"  {DIM}POST /control /seek /volume /settings /browse /load{RESET}")
    print(f"  {DIM}POST /pin /notifications{RESET}")
    print(f"  {DIM}WS   /ws{RESET}")
    if notify_ok:
        state = "on" if session.notifications else "off"
        print(f"  {DIM}track notifications: {state}{RESET}")
    if player.error is None:
        print(f"  {DIM}MPRIS {BOLD}org.mpris.MediaPlayer2.omarchy_roon{RESET}"
              f"{DIM} — the Omarchy bar picks this up{RESET}")
    try:
        api.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        player.stop()
        session.stop()
        api.server_close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="omarchy_roond")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--browse", action="store_true")
    ap.add_argument("--control", metavar="ZONE:ACTION")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--serve", action="store_true",
                    help="run the local API for QML instead of exiting")
    ap.add_argument("--api-port", dest="api_port", type=int, default=9821)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="synthetic zones and artwork; no Core, nothing personal")
    args = ap.parse_args()

    if args.serve:
        return serve(args)

    print(f"{BOLD}discovery{RESET}")
    t0 = time.time()
    cores = discovery.discover(host=args.host)
    print(f"  {len(cores)} core(s) in {time.time() - t0:.1f}s")
    for c in cores:
        print(f"    {GREEN}{c.name}{RESET} at {c.ip}:{c.http_port}  "
              f"{DIM}{c.display_version} {c.unique_id}{RESET}")
    if not cores and not args.host:
        print(f"  {RED}no Core found{RESET}")
        return 1

    session = RoonSession(host=args.host, port=args.port)
    ready = threading.Event()
    session.on_connected = lambda body: (
        print(f"\n{BOLD}connected{RESET} to {GREEN}{body.get('display_name')}{RESET} "
              f"{DIM}{body.get('display_version')}{RESET}"), ready.set())
    session.on_disconnected = lambda why: print(f"{RED}disconnected:{RESET} {why}")
    session.on_awaiting_approval = lambda why: print(f"{YELLOW}approval needed:{RESET} {why}")

    changes = {"n": 0}

    def on_zones(touched):
        changes["n"] += 1
        if changes["n"] == 1:
            render(session)

    session.on_zones = on_zones

    thread = threading.Thread(target=session.run_forever, daemon=True)
    thread.start()
    if not ready.wait(25):
        print(f"{RED}could not connect{RESET}  "
              f"{DIM}(if this is a first run, approve 'Roon for Omarchy' in "
              f"Roon Settings > Extensions){RESET}")
        return 1
    time.sleep(1.5)

    if args.browse:
        print(f"\n{BOLD}browse{RESET}")
        for hierarchy in ("browse", "albums", "artists", "genres", "playlists"):
            session.browse(hierarchy=hierarchy, pop_all=True,
                           multi_session_key=f"cli-{hierarchy}")
            page = session.load(hierarchy=hierarchy, count=3,
                                multi_session_key=f"cli-{hierarchy}")
            body = page.body or {}
            lst = body.get("list") or {}
            print(f"  {BOLD}{hierarchy:<10}{RESET} {lst.get('title'):<12} "
                  f"{DIM}{lst.get('count')} items{RESET}")
            for item in (body.get("items") or [])[:3]:
                art = "🖼" if item.get("image_key") else " "
                print(f"      {art} {str(item.get('title'))[:38]:<38} "
                      f"{DIM}{str(item.get('subtitle') or '')[:26]}{RESET}")

    if args.control:
        name, _, action = args.control.partition(":")
        zone = next((z for z in session.zones.all()
                     if (z.get("display_name") or "").lower() == name.lower()), None)
        if zone is None:
            print(f"{RED}no zone named {name!r}{RESET}")
        else:
            print(f"\n{BOLD}control{RESET} {name} -> {action}")
            before = session.zones.summary(zone["zone_id"])["state"]
            reply = session.control(zone["zone_id"], action)
            time.sleep(1.5)
            after = session.zones.summary(zone["zone_id"])["state"]
            ok = (GREEN + "state changed" + RESET if before != after
                  else YELLOW + "state unchanged" + RESET)
            print(f"  {reply}  {before} -> {after}  {ok}")

    print(f"\n{BOLD}streaming{RESET} for {args.seconds:g}s "
          f"{DIM}(seek ticks and zone changes){RESET}")
    seen = changes["n"]
    end = time.time() + args.seconds
    while time.time() < end:
        time.sleep(1.0)
        if changes["n"] != seen:
            playing = session.zones.playing()
            if playing:
                s = session.zones.summary(playing[0]["zone_id"])
                print(f"  {GREEN}▸{RESET} {s['name']:<24} "
                      f"{s['track']['title'][:34]:<34} "
                      f"{clock(s['track']['seek_position'])}/{clock(s['track']['length'])}")
            seen = changes["n"]

    print(f"\n{BOLD}total{RESET} {changes['n']} zone messages in {args.seconds:g}s")
    session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
