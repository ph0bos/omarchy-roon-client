# Roon for Omarchy

**Your Omarchy machine, as a Roon endpoint — with the zone in your bar.**
Play to this desktop from the Roon app on your phone, and see what it is playing
without a window anywhere.

![The mini player](docs/screenshots/player.gif)

*Screenshots and the animation above are taken in demo mode against invented
zones and a generated sleeve. Nothing personal was ever written to the files.*

---

## What this is

Roon ships no client for Linux. There is a headless server and a headless
bridge, and that is all — every remote is Windows, macOS, iOS or Android. The
most popular workaround on the AUR runs the **Windows app under Proton**, which
is a fair measure of how much people want this.

This takes the other path. A small daemon holds the connection to your Core and
publishes it to the desktop; the bar shows what is playing and lets you drive it.
There is no window, no Electron, and no browser engine.

**Release 1 is the endpoint and the bar.** Browsing, search and the queue live in
the daemon's API already, but the surfaces for them are R2 — you pick the music
from your phone, and this machine plays it.

## Requirements

> **A Roon subscription and a Roon Core on your network are required.** This is a
> client and an endpoint, not a source of music.

- **Omarchy 4+** with Quickshell
- **PipeWire**, with `pipewire-alsa`
- `python-gobject` — for MPRIS and the artwork palette
- `cava`, if you want the spectrum analyser
- A Roon Core reachable on the LAN

## Install

```bash
omarchy plugin add https://github.com/ph0bos/omarchy-roon-client.git
omarchy plugin enable quickshell.roon
```

Then set up the endpoint and the daemon:

```bash
./bin/omarchy-roon-endpoint install     # RoonBridge, as you, under a --user unit
./bin/omarchy-roon-endpoint firewall    # the ports RAAT actually needs
./bin/omarchy-roon-endpoint daemon      # the Roon connection, the API and MPRIS
./bin/omarchy-roon-endpoint doctor      # what is true right now
```

Approve the extension once in **Roon → Settings → Extensions** (from your phone;
there is no Roon GUI on Linux), enable this machine's output under
**Settings → Audio**, then:

```bash
./bin/omarchy-roon-endpoint pipewire    # route that output through PipeWire
```

`doctor` is read-only and is the first thing to run when anything looks wrong.

## The bar

![The bar icon](docs/screenshots/bar.png)

A level meter that moves while audio is playing, sits still when it is not, and
is struck through when the daemon is down. Click for the mini player; scroll to
skip.

![Zones](docs/screenshots/zones.png)

The mini player carries the sleeve, a live spectrum analyser, the timeline,
transport, volume with mute, and the zone at the foot. The timeline, the volume
fill and the analyser are **lit in the artwork's own colour** — measured from the
sleeve, and falling back to your theme when a cover is genuinely monochrome.

Beside the title is what is **actually coming out of this machine** — `PCM 24/96`,
`DSD64` — with the dot lit in the record's colour above CD quality. It is read
from RAATServer, so it is the format the Core is really sending this endpoint,
not a guess.

Keys, if you want them, in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + R",         "Roon",            "omarchy-shell roon player")
o.bind("SUPER + SHIFT + R", "Roon play/pause", "omarchy-shell roon playpause")
```

`omarchy-shell roon status|zone|next|previous|notifications|refresh` are there too.

## How it works

```
Roon app (phone)  ──▶  Roon Core  ──RAAT──▶  RoonBridge  ──▶  PipeWire  ──▶  DAC
                            │                                      │
                            └── MOO/WS ──▶ omarchy-roond ──▶ MPRIS ─┘
                                                 │
                                          HTTP + WS ──▶ the bar
```

**The daemon owns the one thing QML cannot do**: discovery is UDP, pairing needs
a stored token, and zone state arrives as pushes on a subscription that has to
stay open. It is stdlib-only Python with no runtime dependencies.

**The bar reads MPRIS, not the socket.** Quickshell ships no WebSocket module, and
it does not need one: track, artwork and play state arrive push-based over D-Bus
for free. HTTP is used only for what MPRIS has no vocabulary for — which zone this
is, what others exist, and mute.

**Album art never touches the daemon.** The Core serves it over plain HTTP, so QML
points `Image` straight at the Core and Qt's own cache does the work.

**Playback is gapless, and none of that is this client's doing.** RAAT streams
continuously and the Core drives it; consecutive tracks at the same format play
through without the sound card being reconfigured. Measured on a real session:
64 stream starts against 9 device setups, and every setup lined up with a format
change rather than a track change. A change of rate or depth *does* reconfigure
the device, which is a real gap — that is what Roon's resync delay setting is for.

**RoonBridge runs as you, not root.** The packaged unit is `User=root`, and root
cannot reach your PipeWire session — so a root bridge can only take the sound card
exclusively, silencing system audio. Running it as you, through `plug:pipewire`,
is also what makes the spectrum analyser possible at all: it taps the same signal
that reaches your DAC.

## Known constraints

These are Roon's, not this client's, and they are worth knowing before you file
a bug:

- **No format data over the API** — but the badge works anyway. Roon's *extension*
  API exposes no sample rate, bit depth or signal path at all. This machine is the
  endpoint though, so RAATServer is told exactly what to play and writes it down;
  the badge reads that. It therefore appears only when the pinned zone is **this**
  machine — another room is played by hardware this one knows nothing about.
- **No file format, ever.** FLAC, ALAC and AAC never reach an endpoint: **RAAT
  decodes on the Core and streams PCM.** The setup request carries sample type,
  rate, depth and channels and nothing else, which is why the badge says `PCM
  24/96` — the same thing Roon's own signal path says at this stage.
- **No track identifiers.** `now_playing` is three pre-formatted display strings
  and an image key. Everything downstream parses those.
- **No favouriting.** It lives in Roon's browse action lists, which are not
  reachable from what is playing.
- **Discovery is fragile.** Omarchy's default firewall drops the reply, and a Core
  in a bridge-networked container never sees the broadcast at all. There are three
  discovery tiers for this reason, and `doctor` will tell you which one is in play.

## Development

```bash
pytest                                   # 86 tests, no Core required
python -m omarchy_roond --serve --demo   # synthetic zones, invented music
python -m omarchy_roond --browse         # exercise a real Core from the terminal
ROON_LIVE_HOST=<core-ip> pytest tests/test_live.py
```

`--demo` exists so the interface can be built, and photographed, without a
subscription and without putting anyone's hostname or listening history in a file.

`spikes/` holds the throwaway programs that worked the protocol out, and
`spikes/fixtures/` the payloads captured from a real Core that the tests run
against.

## Not affiliated with Roon Labs

Roon is a trademark of Roon Labs LLC. This is an independent client that talks to
Roon's public extension API; it is not endorsed by, affiliated with, or supported
by Roon Labs. **RoonBridge is Roon's own software** and is installed from the AUR,
not distributed here.

## Licence

MIT — see [LICENSE](LICENSE).
