# Roon for Omarchy — design context

Plugin id `quickshell.roon`. A Roon controller and local endpoint built into the
Omarchy shell, taking the chrome and the install machinery from `omarchy-tidal`
and almost none of its data model.

Not affiliated with or endorsed by Roon Labs. That line ships in the README and
in Settings, not as a footnote.

## The three constraints everything else follows from

**Roon Core does the playing.** Every Roon client is a controller against a Core
on the LAN. RAAT is closed and licensed to hardware partners, so the only way to
make this machine a zone is RoonBridge — a proprietary binary that cannot be
redistributed.

**There is no metadata API.** Browse is a generic, server-driven list machine:
`{title, subtitle, image_key, hint}` and a cursor. `now_playing` is, in full,
`seek_position`, `length`, `image_key`, and the pre-formatted display strings
`one_line` / `two_line` / `three_line`. No sample rate, no bit depth, no codec,
no signal path, and no track, album or artist IDs.

Observed on the live Core, the `three_line` convention holds exactly:
`line1` title, `line2` artist, `line3` album. `two_line` drops the album;
`one_line` is `"Title - Artist"`. Parse `three_line` and nothing else.

One undocumented gift: `now_playing.artist_image_keys` is a real array of image
keys, absent from the JSDoc. Artist photography is therefore available for the
Now Playing backdrop, which the sleeve-only design did not assume.

**Roon ships no GUI on Linux.** Only headless RoonServer and RoonBridge. That is
why this is worth building — and it is also why the setup wizard has to tell the
user to approve the extension from their phone.

## Architecture

    Quickshell QML  ──HTTP+WS──▶  omarchy-roond  ──MOO/WS──▶  Roon Core
          │                        (systemd --user)                 │
          └──────────── HTTP, /api/image/{key} ────────────────────┘

                        RoonBridge (systemd --user, as you)
                              └──▶ plug:pipewire ──▶ DAC

**Daemon is mandatory.** Discovery is SOOD over UDP broadcast, which QML cannot
do; pairing needs a persisted token; zone state arrives as pushes on a long-lived
subscription.

**Python**, vendoring `roonapi` into the repo as owned source rather than
depending on it — it has been quiet since 2023, and vendoring converts an
unmaintained dependency into code we maintain. It already implements SOOD, MOO
framing, token persistence, transport and browse. Choosing Python also lets
`palette.py`, `lyrics.py`, `images.py` and `text.py` cross over from
`omarchy-tidal` nearly verbatim.

**Transport to QML** is HTTP + WebSocket on `127.0.0.1` — the same shape as
`MopidyRpc.js` consuming Mopidy. WS carries zone state; HTTP carries browse and
control.

**Album art bypasses the daemon.** The Core serves images itself at
`http://core:port/api/image/{key}?scale=fit&width=W&height=H&format=image/jpeg`,
so QML's `Image` points straight at it and Qt's image cache does the work. The
daemon fetches only a 16x16 thumbnail, for `palette.py`. This deletes an entire
caching subsystem.

**`RoonSession` is a narrow seam** — connect, subscribe, browse, load, control.
Designed so a fake Core can drop in behind it later without a rewrite.

## Local playback

RoonBridge, installed with Roon's official self-updating installer, run **as your
user** under a `--user` unit, targeting **`plug:pipewire`**.

The failure everyone hits is that the official installer runs RoonBridge as root,
and root cannot reach a per-user PipeWire session. Running it as you fixes that.
`plug:` rather than `default:` because PipeWire's default device answers ALSA
device probing incorrectly.

`aur/roonbridge` is rejected: it sat at 2.60.1501 while `aur/roonserver` was at
2.71.1683, and a Core will not play to an out-of-date endpoint.

Exclusive ALSA is a documented manual escape hatch, **not a shipped toggle**. It
is bit-perfect and it silently kills the cava visualiser and all system sound. One
well-lit path beats two half-tested ones.

## Zones, volume and keys

**One pinned zone**, defaulting to the local one, switchable from the quick menu.
Not "whichever zone is playing" — that is chaos in a shared house.

**Volume is per-`Output`, not per-zone.** A grouped zone has N outputs with
different volume systems (dB vs 0-100 vs `incremental`, the last having no value,
min or max at all). The overlay therefore shows **per-output rows**, plus a group
+/- that fans `relative_step` out to every output. There is no synthetic absolute
group fader: averaging a dB control against a linear one is the slick thing that
is also the lying thing.

Confirmed against the live Core, with two things the JSDoc does not mention:

- **`hard_limit_min` / `hard_limit_max` / `soft_limit` are real fields.** The
  Workshop output reports `min:0 max:100` but `hard_limit_max:50, soft_limit:50` --
  a deliberately volume-limited zone. A slider drawn from `min`/`max` alone would
  let the user push it to 100 and have the Core refuse. **Clamp to `soft_limit`.**
- **An output can have no `volume` object at all.** `Network Streamer` has none.
  This was predicted; it is now observed. Render those with no fader rather than a
  disabled one.

Outputs also carry `can_group_with_output_ids`, so the grouping affordance is
available whenever v1's fence comes down.

**`source_controls[].status == "standby"` does not mean the device is asleep.**
The network streamer reports standby permanently, including while playing audible music,
and never exposes a volume object at all. So: the zone's own `state` is the sole
authority on playback, standby is at most a dim hint on the zone row, and it must
never disable a control or tell the user the device is off. An earlier draft of
this document had that exactly backwards.

**Media keys go to PipeWire**, with the local Roon zone pinned to fixed. Two
independent faders for one sound means whichever the keys don't touch becomes a
liar; this keeps the Omarchy OSD honest. Cross-room volume lives in the overlay.

**MPRIS exports the pinned zone.** `XF86AudioPlay` can therefore pause a speaker
in another room. That is correct under a pinned-zone model and it is why the bar
widget must always name the zone.

    SUPER+M         overlay
    SUPER+SHIFT+M   lyrics
    SUPER+ALT+M     zones
    SUPER+CTRL+M    Roon Radio toggle

## R2 is an overlay, and the TIDAL UX comes with it

Settled at the start of R2, after R1 deliberately left it open: **the full client
is an `entryPoints.overlay` surface, not a standalone app.**

The brief said "an app, not a plugin", and the honest price of that turned out to
be the whole reason to decide the other way. A standalone process cannot
`import qs.Ui` or `qs.Commons`: no `Color`, no `Style`, no `BorderSurface`, no
`PanelSlider`. It would need a theme adapter reading `~/.local/state/omarchy/current/`
and its own copy of every shell primitive -- paid up front, before a single
browse list appears on screen.

What settles it is that **the UX already exists**. `omarchy-tidal` ships ~5,400
lines of QML built for exactly these surfaces:

    Overlay.qml            the summoned window, its chrome and keyboard model
    views/HomeView         a tiled landing page of library roots
    views/DetailView       an album or artist page
    views/PlayerView       transport, queue, quality
    views/NowPlayingView   the full-screen player, art washes and all
    components/SetupWizard the first-run rungs, already rendered
    components/            Shelf, LibraryGrid, TrackRow, SeekBar, ArtCard,
                           QuickMenu, TiltFrame, RoundedImage, ScrollHint...
    lib/Design.js          the shared spacing and type scale

Every one of those imports `qs.Commons` or `qs.Ui`. As an overlay they port with
their theming intact; as an app they would each need rewriting against the
adapter. The daemon seam does not change either way, which is what kept the
decision open this long.

The port is a substitution, not a rewrite: `TidalApi.js` becomes `Roond.js` (which
R1 already has), Mopidy's RPC becomes the local API, and Tidal's flat
`{id, title, artist}` objects become browse-tree positions -- the one place the
shapes genuinely differ, because Roon has no metadata API to return objects from.

**`SetupWizard.qml` is the piece most worth having.** The first-run wizard was
chosen in R1 and never built; the rungs differ (discovery, pairing, approval,
RoonBridge, zone) but the shape -- a blocking step that polls until a human acts
elsewhere -- is the same component.

## Screens

**First-class:** Now Playing (ported `NowPlayingView`, `SeekBar`, `TiltFrame`,
theme washes via `palette.py`) · Zones · Queue (`subscribe_queue` + 
`play_from_here`) · Search · a tiled landing page of library roots plus Recently
Played and a Roon Radio toggle.

**Generic browse** for everything below a library root.

The landing page is the closest honest analogue to Tidal's personalised home that
the API can feed. The browse tree is the substrate; hand-built screens are entry
points into it, never a reconstruction of it.

**Search is a conversation, not a query.** Browse returns an item carrying
`input_prompt`; you re-browse with `opts.input`; then you load. Two round trips
minimum, no typeahead. Debounce ~350ms and run it on a dedicated
`multi_session_key`.

**Browse sessions are stateful.** The Core holds one cursor per session. Any two
surfaces browsing at once need distinct `multi_session_key`s or they will yank
each other around. Search is the case that forces this.

**Seek** interpolates locally off a monotonic clock, resyncs hard on every
`zones_seek_changed` (~1Hz), freezes on pause. `Service.qml` owns `position`, as
it does today.

**Queue** subscribes once at 100 items per pinned zone, re-subscribing only on
zone change. Built in R2 -- see *The queue, as built* below.

## Resilience

Pin the Core by **Core ID, never IP** — pairing tokens are per-Core, and Roon's
approval gate means an unpinned Core is an unapproved one.

- SOOD discovery runs continuously in the background, so an IP change is absorbed
  silently.
- Prefer a Core on `localhost` when one is found there. A *different* Core
  answering is ignored, never adopted — on a flat network, auto-adopt eventually
  connects you to a neighbour's Core.
- Tolerate the 30-120s a freshly-booted RoonServer takes to answer.
- Backoff 1s to a 30s cap. `Restart=always`, `After=network-online.target`.
- **The UI never goes blank.** Last-known zone state stays rendered, desaturated,
  with a reconnecting indicator. A Core rebooting should look like a pause, not a
  crash.

### Discovery: three tiers, because multicast is not reliable

Verified against the development Core (`the Core`, Roon 2.70 build 1671).

**Tier 1 -- standard SOOD.** Multicast to 239.255.90.90:9003 plus per-interface
broadcast, exactly as `sood.js` does: a recv socket on 9003 with membership
joined, and a send socket bound to the interface IP that *also listens*, because
the Core answers to the query's source port rather than to 9003. Fast and correct
when the network cooperates.

**Tier 2 -- unicast SOOD sweep.** When tier 1 finds nothing, send the same SOOD
query unicast to every host on the local /24 at port 9003. The development Core
**answers unicast perfectly while ignoring multicast and broadcast entirely** --
the signature of a Core in a bridge-networked container, which is how Roon is
commonly run on a NAS.

This is a much better fallback than asking the user to type an address, because
the reply is a real SOOD payload carrying everything needed to connect:

    name             the Core
    unique_id        00000000-0000-0000-0000-000000000000
    http_port        9330
    tcp_port         9150
    service_id       00720724-5143-4a9b-abac-0e50cba674bb

So a containerised Core is discovered automatically, with no user configuration
and no manual port entry.

**Every query needs a fresh `_tid`** -- see "Solved" below; a repeated tid is
answered with silence, which is what made an early blind sweep look like an empty
network.

**The sweep is targeted rather than blind.** TCP-prescan the subnet for hosts with
9330, 9200 or 9100 open, then unicast-query only those, in parallel. On the
development network that is 3 candidates out of 254, and the whole of tier 2
completes in under 2s. A handful of aimed probes beats 254 blind datagrams even
now that the blind version would work.

**Tier 3 -- manual host entry.** For Cores on another subnet or behind a router.
Ask for a host only: once the host is known, a unicast SOOD query supplies the
port, so the user is never asked for one. `ws_connect({host, port})` is the
officially supported path (`lib.js:429`).

**Firewall.** Omarchy ships `ufw` enabled with `DEFAULT_INPUT_POLICY="DROP"`.
Tier 2 works regardless, because the reply returns on an established unicast flow
that conntrack permits. Tier 1 does **not**: a reply to a multicast or broadcast
query matches no flow and is dropped. So the wizard should offer

    sudo ufw allow 9003/udp comment 'Roon discovery (SOOD)'

as an optimisation that makes tier 1 work, never as a preconditon for finding a
Core at all.

## Spike results

### The MOO stack is proven end to end

`spikes/core-handshake.py` opens a WebSocket to `ws://192.0.2.10:9330/api`,
hand-rolls RFC 6455 client framing and sends `com.roonlabs.registry:1/info` --
the one call a Core answers before any pairing or approval:

    MOO/1 COMPLETE Success
      core_id           00000000-0000-0000-0000-000000000000
      display_name      the Core
      display_version   2.70 (build 1671) production

Transport, MOO framing and the Core are all healthy. Nothing in the architecture
is blocked.

### Discovery: diagnosed

`spikes/sood-discovery.py` now mirrors `sood.js` faithfully -- per-interface send
socket bound to the interface IP with `IP_MULTICAST_IF` and TTL 1, listening on
both that socket and 9003, membership joined. Multicast and broadcast still get
nothing.

A unicast SOOD query to the Core's address gets a full, correct reply. **The
Core's SOOD service is healthy; only multicast and broadcast delivery to it is
broken.** Hence the three-tier ladder above, with the unicast sweep as the tier
that actually makes this work in the common Docker deployment.

### Two hypotheses that were wrong, and why

**"The API port is unpublished."** An early sweep found no MOO endpoint and blamed
container networking. Wrong: 9330 returned `503` because the Core was mid-restart.
The API is reachable, on the same port that serves the Display web app.

**"The firewall is the cause."** `ufw` does drop broadcast and multicast replies,
so it is *a* cause of tier 1 failing -- but adding the rule changed nothing,
because the Core was never answering those queries in the first place. The
firewall is a real issue for tier 1 and irrelevant to tier 2.

Both were caught by continuing to test rather than accepting the first plausible
story. The lesson worth keeping: **a negative result from your own probe is not
evidence until the probe is verified against the reference implementation.** Two
of the three failures here were bugs in the probe, not in the network.

### Solved: the Core deduplicates SOOD queries by `_tid`

The mystery -- a single unicast query answered reliably, the same query inside a
sweep answered never -- was ours, not the network's.

`sood.js:84` assigns `msg['_tid'] = uuid.v4()` when the caller omits one. That is
not decoration. **The Core answers the first query it sees for a given `_tid` and
ignores every repeat.** Both spikes reused a constant tid, so the first query of a
process worked and every one after it looked like "no Core on the network" -- and
a 254-address sweep sending one identical datagram per host is 254 duplicates.

Fixed by generating a fresh UUID per datagram in `discovery.query_message()`.
Discovery now finds the Core repeatably, through all three tiers.

The reference had told us, in a line we read and did not act on. Worth
remembering: when reimplementing a protocol, the incidental-looking lines are
often the protocol.

### Notifications

One replaceable notification per category, so alerts never stack and recovery
*replaces* the failure. Toggleable in Settings beside "Announce each track".

| Event | Notify |
|---|---|
| Core unreachable > 10s | yes |
| Core recovered | yes, replaces the alert, 5s expiry |
| Reconnect under 10s | **no** — blips must stay silent or the alert gets ignored |
| RoonBridge down / local zone vanished | yes, distinct from Core loss, different fix |
| Extension approval revoked | yes, actionable and otherwise invisible |
| Remote zone start/stop, pause | no |

## Protocol gotchas, learned the hard way

**WebSocket messages are fragmented, and the zone payload always is.** The Core
sends a first frame with FIN=0 and the real opcode, then continuation frames
(opcode `0x0`) until FIN=1. A reader that treats each frame as a message gets
truncated JSON and **silently loses every zone update** -- browse still works
perfectly, so the bug looks like "transport is broken" rather than "framing is
broken". Reassemble on FIN.

**Subscriptions answer `Subscribed`, not `Success`.** `subscribe_zones` replies
`MOO/1 CONTINUE Subscribed`; filtering responses on `Success` drops it.

**Registration is `CONTINUE`, not `COMPLETE`.** `registry:1/register` returns
`MOO/1 CONTINUE Registered` and the request stays open, so the registry can push
further messages down it. Do not treat registration as one-shot.

**The saved token makes reconnection silent.** Re-registering with the stored
token returns `Registered` immediately with no approval prompt, which is what
makes `Restart=always` on the daemon acceptable.

## Setup wizard

Five rungs, each with a cause line, in the shape `omarchy-tidal-setup` already
has:

0. **Discovery reachable** -- `ufw` allows inbound UDP 9003, or the user has
   entered a host and port manually
1. Core found
2. Paired
3. **Extension approved in Roon Settings > Extensions**
4. RoonBridge running
5. Zone visible to the Core

Rung 0 is new, and it exists because the default Omarchy firewall breaks Roon
discovery silently. "No Core found" is the single most likely first-run outcome,
and it must never be a dead end: offer the `ufw` rule, and offer manual host+port
entry beside it.

Rung 3 is **blocking, with live polling**, and the wizard says out loud: open Roon
on your phone or another computer. It is the most confusing moment in the whole
product — a user with no Roon app on any device is stuck, and the wizard must say
so rather than showing a red tick and letting them hunt.

## Bar widget

Names the zone, always. Five distinct states: pinned playing · pinned idle ·
**pinned idle while another zone plays** (dim `> Lounge` hint, tap to re-pin) ·
Core unreachable · RoonBridge down. The last two must not look like idle, or every
support thread opens with "the widget just isn't there".

Manifest schema: `showZoneName`, `showLabel`, `maxLabelWidth`, `scrollLongLabels`,
`showOutputFormat`. `favorite` and `showQualityBadge` are deleted.

## Testing

Record real payloads from a live Core and commit them as fixtures; drive the
daemon's state machine against them offline. That covers what actually breaks:
parsing `three_line`, browse paging, `zones_seek_changed` merge logic, incremental
volume. Pure modules keep the `tests/_backend.py` load-from-disk pattern.

A full fake Core is a project of its own. `RoonSession` is shaped so one can be
added later; it has to earn it first.

## The daemon, as built

`backend/omarchy_roond/`, stdlib only:

| Module | Responsibility |
|---|---|
| `moo.py` | WebSocket + MOO framing, fragment reassembly, ping/pong |
| `discovery.py` | the three tiers, fresh `_tid` per query, targeted prescan |
| `text.py` | `three_line` parsing, volume bounds, standby -- pure, fixture-tested |
| `zones.py` | `ZoneStore`: the Subscribed/Changed/seek merge -- pure, fixture-tested |
| `session.py` | `RoonSession`: connect, register, subscribe, control, browse, reconnect |
| `wire.py` | server-side WebSocket framing (the other half of `moo.py`) |
| `server.py` | the local API: HTTP for calls, one WebSocket for pushes |
| `__main__.py` | `--serve` to run the daemon; otherwise an end-to-end exercise |

### The local API

`http://127.0.0.1:9821`, bound to loopback and unauthenticated -- the same
bargain Mopidy's HTTP frontend makes, and nothing here is reachable off-machine.

| Route | |
|---|---|
| `GET /health` | liveness, connection state, zone and client counts |
| `GET /state` | full snapshot: core, `image_base`, every zone |
| `GET /zones`, `GET /zones/<id>` | zone summaries |
| `POST /control` | `{zone_id, action}` |
| `POST /seek` | `{zone_id, seconds, how}` |
| `POST /volume` | `{output_id, value, how}` |
| `POST /settings` | `{zone_id, shuffle?, loop?, auto_radio?}` |
| `POST /browse`, `POST /load` | the browse tree, options passed through |
| `POST /page` | browse + load as one move, locked per `session_key` |
| `GET /setup` | the five first-run rungs, each with what to do about it |
| `GET /queue` | the pinned zone's queue, from the daemon's own subscription |
| `POST /play_from_here` | `{zone_id?, queue_item_id}`; the zone defaults to the pin |
| `WS /ws` | `state` on connect, then `zones` / `queue` / `connected` / `disconnected` / `awaiting_approval` |

Two deliberate absences. **There is no art route**: `/state` publishes
`image_base` and QML points `Image` straight at the Core, which is measurably
real -- a 300x300 JPEG comes back from `/api/image/<key>` in 35KB with no daemon
in the path. And **clients never send anything over the WebSocket**; it is push
only, because everything a client wants to say is a call with a reply and belongs
on HTTP.

Writes answer `503` while disconnected but reads keep working, so the interface
can always render its disconnected state instead of going blank.

**No `roonapi` after all.** The plan was to vendor it; writing the client turned
out to be less code than vendoring and adapting one would have been, and it leaves
the daemon with no third-party dependency at all. The seam is the same either way.

**`AwaitingApproval` is its own exception**, because an unapproved extension does
not fail -- registration simply never answers. Reporting that silence as a
connection error sends the user hunting for a network fault instead of opening
Roon on their phone. The reconnect loop polls every 3s while in that state,
because a human is acting right then.

### The queue, as built

One subscription, following the pinned zone, re-subscribed only when the pin
moves. `/queue` is then a read of the daemon's own memory rather than a call to
the Core, which is what lets a surface poll it as cheaply as `/zones`.

Two things this shape is protecting against:

**A subscription per zone would mean holding every room's list to render one.**
The queue is ~100 items of three display strings each. A surface that wants
another room's queue pins that room; there is no `/queue/<zone_id>`, because a
route that answers for an unsubscribed zone would have to either lie or block.

**Only `Subscribed` is verified against a live Core.** `queue.json` is a capture
of it. The `changes` operations -- `remove(index, count)` and
`insert(index, items)` -- are taken from `node-roon-api-transport` and have not
been observed here. So `QueueStore` applies what it recognises and sets `stale`
on anything it does not, stopping rather than guessing; `RoonSession` re-subscribes
when it sees the flag. One round trip per unknown operation, against a list that
would otherwise be quietly out of step with the Core forever.

`_ensure_queue_subscription` runs on the read loop's own thread, so everything in
the subscription path is fire-and-forget rather than `call()`: waiting there for
a reply that only the same thread can read is a deadlock.

`play_from_here` takes the Core's `queue_item_id` and nothing else. There is no
"play item n" -- a position is not a handle, because the list edits underneath it.

### The overlay, as built

Two views behind one summoned window, because a plugin only ever gets one
panel-kind entry point loaded: the shell picks `panel` over `overlay` over
`menu` and loads that one. Now playing and the queue therefore cannot be
separate surfaces -- they are views chosen by the summon payload.

    omarchy-shell roon overlay      ->  {"view":"nowPlaying"}
    omarchy-shell roon queue        ->  {"view":"queue"}

Ported from `omarchy-tidal` with the theming intact, as the overlay decision
promised: `Overlay.qml`'s structure (screen picking, the cross-fade between
views, the keyboard model), `HeaderButton`, `RoundedImage`, `SeekBar`,
`PlayerBar`, and `lib/Design.js`.

What changed in the port, and why:

**No links on the title and the artist.** Tidal's transport strip makes both a
way into their pages. Roon has no metadata API, so there is no artist object to
open -- an artist page is a position in a browse tree. Making them look
clickable would be a promise the API cannot keep. What takes their place on the
right is what Roon knows and Tidal does not: the room, and the format actually
leaving this machine.

**Seconds, not milliseconds.** Tidal's `SeekBar` works in ms because Mopidy
does; `/seek` and Roon's own verb both take seconds, so the conversion is gone
rather than doubled.

**`RoonMark` came out of the bar widget** into `components/`, so the header and
the bar wear the same mark. Two drawings of "Roon" that drifted apart would read
as two plugins.

**Which queue row is playing is a match, not a fact.** `now_playing` has no
track id to compare a `queue_item_id` against, so the row is marked by matching
the display strings. It is cosmetic: when it is wrong, a row is un-marked and
nothing else changes.

Two pieces of state the surfaces needed from the service:

**`probed`** -- false until the first answer, either way. "Not answered yet" and
"answered and it is down" look identical on a boolean, and a surface that treats
them the same shows a connection error every time the shell restarts. It is the
same trap `AwaitingApproval` models on the daemon side.

**`openSurfaces`** -- how many of the plugin's windows are on screen. The state
poll speeds up while any of them is, the queue is only fetched while one is, and
the notification card is silenced for a track a surface is already showing.

**`image_base` became a session property.** `/state` built it from the Core's
address, which is right for a real Core and wrong for `--demo`: the demo session
serves its invented sleeve from the daemon itself, and a queue row built from a
demo Core's address would ask a machine that is not there. The bar never noticed
because MPRIS hands it a finished URL.

Verified on a live Core: first summon, both views, no QML warnings in the
journal, the queue subscription bound against a real 8-zone Core and the row
rendering with art, duration and the playing marker.

### The menu, the keyboard map, and the wizard

Three surfaces that finish the window, all ported in shape from `omarchy-tidal`
and rebuilt around what Roon actually exposes.

**QuickMenu** (`M`) carries shuffle, repeat, Roon Radio, track notifications, the
keyboard map -- and the rooms. Two things worth knowing about it:

* **Shuffle, repeat and Roon Radio are properties of the ZONE, not of this
  client.** Changing one changes it for the room, and for whoever is looking at
  their phone. That is Roon's model, so the menu reads the zone's own settings
  rather than anything stored here, and re-reads after every change instead of
  guessing -- the daemon is on loopback and answers before the menu redraws.
* **The rooms belong in this menu** rather than behind a surface of their own,
  because the pin is what MPRIS, the media keys, the bar and the queue all
  follow. Switching rooms changes what the whole window is about.

**ShortcutSheet** (`?`) lists only keys this window actually handles. The Super
bindings are shown as `omarchy-shell` commands under "if you bind them", because
a plugin cannot install a keybinding and advertising one as though it were
already yours is a small lie the first keypress exposes.

**SetupWizard** -- owed since R1, where "put it in the UI" was chosen and only
the terminal `doctor` was built. The daemon computes the ladder at `GET /setup`;
the wizard renders it and polls every 2s while it is on screen, because the rung
people get stuck on is one a human is acting on *right now* on a phone.

Five rungs, in the order things must happen: Core found, paired, approved in
Roon, RoonBridge running, this machine visible as a zone. Each carries its own
`fix`, because "Approved in Roon" on its own is a diagnosis without a treatment.

Three decisions inside it are worth keeping:

**Discovery is not a rung.** It is part of the first one. With a host configured
by hand, discovery can be entirely broken and everything still works -- so
reporting it as a failure would tell someone to fix what is not their problem.
It is reported in rung 1's detail instead ("found by discovery"), and its fix
mentions the firewall.

**`blocked` is not `failed`.** An unapproved extension does not fail; nothing is
broken and someone simply has to say yes somewhere else. It is drawn as *waiting
on you*, in the accent rather than in `Color.urgent`.

**A blocked rung outranks an earlier pending one.** Pairing happens *during*
registration, so a person waiting for approval has an unfinished "paired" rung
sitting ABOVE a blocked "approved" one. Pointing at the first unfinished rung
would send them to the one whose fix reads "nothing to do" while the thing
actually stopping them sits below it. `summary()` prefers the blocked rung, and
`test_a_blocked_rung_wins_over_an_earlier_pending_one` is why.

**The daemon is rung zero, and the only one QML synthesises.** Every other rung
is computed *by* the daemon, so when it is not answering there is no ladder to
draw and the reason is the ladder.

The wizard shows only once both probes have answered -- `probed` and
`setupProbed` -- never merely because nothing has come back yet. Both are
asynchronous and the first summon after a shell restart beats them, so testing
readiness alone would open the wizard on a perfectly healthy install every time.
Verified by stopping the daemon under a live overlay: the card shrank to the
ladder, and when the daemon came back it returned by itself to the view the
summon had asked for.

### Browse and search, as built

`GET /page` is the route surfaces actually use, and it exists because of one
fact: **browse is a cursor, not a query.** The Core holds a position per
`multi_session_key`, `browse` moves it and `load` reads a window of wherever it
now is. Sending those as two HTTP requests promises nothing about what happened
in between, so `browse.py` does the pair under a lock held per session key and
serves it as one request. `test_two_requests_on_one_key_do_not_interleave` is
that guarantee written down.

`/browse` and `/load` stay exposed, and paging deliberately uses `/load`
directly: reading another window must not move the cursor, and re-sending the
`item_key` would push into the same item twice.

A browse reply is not always a list. `action: "list"` means load it; `"message"`
is the Core saying something (often an error); anything else changed an item in
place. Only the list path is verified against a live Core, so unknown actions
are passed through untouched rather than guessed at -- a surface can say "the
Core said X" honestly, where inventing a list would be a lie. Action rows send
their message to Omarchy's own OSD.

**The demo grew a library.** `--demo` now serves an invented tree -- albums,
artists, tracks, a working search -- with the same cursor semantics a Core has,
so the browse surfaces can be built and photographed without a subscription and
without anyone's listening history.

#### Two races, both found by running it rather than reading it

**A derived binding is not reliably current inside the change handler of what it
derives from.** `searching` is `query.trim() !== ""`, and on the FIRST keystroke
`onQueryChanged` still read it as false -- so it took the "query is empty"
branch, re-loaded the browse root, and the answer landed on top of the search.
On screen: you type, the header says "Search", and the browse root is listed
underneath it. The fix is to compute the value from `query` in the handler
rather than read the binding.

**Whichever answer lands last wins, even when it is not the one asked for last.**
Browse is asynchronous and a Core is not uniformly fast: a slow root load
arriving after a search, or "mile" arriving after "miles", paints an answer to a
question nobody is asking any more. Every move now takes a ticket -- a serial
bumped per request -- and only the current ticket may draw. Paging checks it
too, because appending a stale window splices another list's rows into this one.

Neither was visible in a unit test or a code read; both were obvious within
seconds of typing into the real thing against a real Core. That is the argument
for `--demo` and for actually running it.

#### What an artist page is

There is still no metadata API, so an artist page is a position in the tree, and
that is exactly how it renders: searching "miles" and pressing Enter on the top
hit lands on `Play Artist` plus his albums, which IS the artist page. Back is
`pop_levels: 1` rather than a remembered URL, and inside a search it pops within
the results rather than abandoning the search -- being thrown back to the
library root from an album you reached by searching loses the search you were
working in.

### A grid, a page, and three small lies caught by looking

**A list of records is a wall of covers; a list of menu entries is a list.**
Which one a browse position is gets decided from the data rather than from the
list's title -- the titles are the user's library and arrive in every language
Roon supports. If most rows carry artwork, the artwork is the content and a grid
shows more of it per screen. Tracks inside an album carry none (they inherit the
sleeve), so an album's own page stays a list, which is what it should be.
Action items get no vote: "Play Album" says nothing about the shape of the page
it sits at the top of.

**The page's artwork is on the list, not the rows.** An album page's
`list.image_key` is the sleeve and an artist page's is their photograph, so a
banner of art, title, subtitle and count is the whole difference between "a
position in a tree" and "a page". It costs nothing -- the Core is already
serving the image.

**An action is a verb, not a record.** Drawn as an art card, "Play Artist" is a
big empty tile that reads as artwork that failed to load. It gets the shape of a
button instead: same cell, same grid, obviously not a sleeve.

Three things this session got wrong and only screenshots caught:

* Every repeat of a track in the queue claimed to be playing. Matching display
  strings is the only way to guess which row is current -- there is no track id
  -- but marking *every* match says one track is playing in four places. Only
  the first match is marked now; Roon's queue starts at what is playing.
* `--demo` opened the first-run wizard over a working demo, because the ladder
  asked systemd about a bridge the demo does not use. A session can now answer
  the ladder itself, and the demo does. The wizard is the one surface that must
  never cry wolf.
* The banner said "5 Albums" and "6 items" in the same breath. Roon's own
  subtitle is usually the count already, so ours only speaks when nothing else
  has.

### The layout: a sidebar, and artwork that takes the window

Reviewed against Apple Music and TIDAL, the first pass was wrong in one
structural way and several small ones.

**Navigation was a mode, not a place.** Three unlabelled glyphs in the header
toggled whole views. Nothing said where you were, and nothing said what else
existed -- the shape of the library was invisible until you went looking for it.
Both references answer this the same way: a sidebar, permanently on screen.

**The library's roots were buried.** Reaching the albums meant walking Explore ->
Library -> Albums: three moves to a place the protocol will take you in one,
because Roon lets you browse a *hierarchy* directly. The sidebar is now exactly
that list -- Albums, Artists, Genres, Composers, Playlists, Live radio -- and
each entry is one `pop_all` browse into its hierarchy.

**The room was in a menu.** Everything in this window is scoped to the pinned
zone: the queue, the transport, the media keys, the bar. It belongs at the foot
of the sidebar, where Apple Music keeps the same control, not two clicks inside
a popover.

**Now playing wasted the window.** A 1020x760 card held one centred sleeve. In
TIDAL the now-playing face takes the whole surface, so it does here: the sidebar
slides away, the artwork fills the card, and the transport strip stays because
that is what you reach for from there. Leaving it puts you back where you were
-- three levels into a record if that is where you left -- which is why `goTo`
distinguishes *choosing* a place from *returning* to one.

Two bugs fell out of doing it:

**A `Row` ignores its children's anchors.** The mark and the wordmark were
anchored to a shared baseline inside a Row, so the anchor did nothing and the
mark sat low and left of the word for the whole of R2 so far. Laid out by hand
they line up. This is the second time the same trap has cost time -- the first
was in `SetupWizard` -- and it is worth remembering as: *inside a Row or Column,
you do not get to say where a child goes.*

**A page can outlive the Core it came from.** Swapping the daemon underneath a
running shell left the browse view showing the previous Core's albums: every
`item_key` on screen belonged to a browse session that no longer existed, so the
rows rendered and clicking one went nowhere. The view now reloads when the
daemon comes back. Caught by accident, while taking screenshots against `--demo`
-- which is also why the README screenshots are verified against the *data*, not
just eyeballed.

### Wearing the record: colour, contrast and motion

The daemon has measured the sleeve since R1 -- `/palette` returns a
representative colour and a luminance -- but the interface only used it for a
dot on the quality badge. It now wears it properly, on the same terms
`omarchy-tidal` does.

**The colour is lifted, not discarded.** A colour taken from artwork often lands
within a couple of percent of the panel it is drawn on, and WCAG asks 3:1 of
anything carrying meaning. Falling back to the theme's accent there throws the
record away for the sake of a little luminance; `Design.contrastLightness` walks
the same HUE up (or down, on a light theme) until it passes, so the identity and
the legibility both survive. Only when no lightness of that hue would do does the
theme take over.

It is computed once, in the service, as `artAccentReadable` -- so the playhead,
the analyser, the queue's marker and the quality dot are demonstrably wearing the
same record rather than four surfaces each doing their own arithmetic.

**The wash is measured.** A white cover lifts the blurred backdrop until muted
metadata vanishes into it, so the scrim over the artwork is a function of the
sleeve's luminance rather than one number chosen against one album.

**`TiltFrame` came across unchanged.** It is presentation with nothing
service-specific in it: the sleeve leans toward the pointer, a pool of light
follows it, and the far side falls away. It leans quickly and returns slowly,
because snapping back is what makes this kind of effect feel cheap. It does not
listen for the pointer itself -- two overlapping hover areas means only the
topmost hears anything -- so the view feeds it the coordinates it already has.

**A record arrives rather than being swapped.** On a track change the sleeve
fades and scales in, and the words follow one `Design.stagger` behind: letting
the object move first and the text follow reads as one thing making room for
another, where moving both at once reads as the panel wobbling. Both are driven
off `artUrl`, because MPRIS pushes that at the instant the track changes while
the polled state is seconds behind.

### A landing page built only from what exists

Apple Music and TIDAL open on an algorithmic home: jump back in, recently
played, made for you. **None of that is reachable from a Roon extension.** The
browse root an extension sees is Library, Playlists, My Live Radio, Genres and
Settings; there is no recently-played list, no recently-added, and no ordering
but the Core's own. Verified against a live Core rather than assumed -- the
Library node contains exactly Search, Artists, Albums, Tracks, Composers, Tags.

So Home is what is true instead:

* **What is playing**, given the top of the page. On a client you mostly drive
  from your phone, that IS the news.
* **Roon Radio**, which is the one control that decides what happens when the
  queue runs dry -- and a property of the ROOM, so turning it on here turns it
  on for whoever else is listening.
* **Your playlists** as a list, not a shelf: Roon returns no artwork for them,
  and a row of blank tiles is worse than a row of names.
* **Genres** as chips, because there are twenty and they are a word each.
* **Albums**, labelled "Albums". A shelf called "Jump back in" filled with
  records beginning with a digit is the kind of lie an interface never recovers
  from.

**Positions travel, not keys.** Each shelf browses on its own session key, and
an `item_key` is only valid in the session that produced it -- so clicking a
card sends the *hierarchy and the index*, and the library view re-browses that
hierarchy and opens the row at that position. Proven end to end: clicking the
third album card lands on exactly what `/page` reports as index 2.

### The queue cannot be edited, and that is the Core's answer

Reorder and remove are not missing from this client; they are missing from the
API. Asked directly, with an empty body so that nothing could act:

    definitely_not_a_method  -> InvalidRequest, no body      (does not exist)
    remove_from_queue        -> InvalidRequest, no body      (does not exist)
    move_in_queue            -> InvalidRequest, no body      (does not exist)
    reorder_queue            -> InvalidRequest, no body      (does not exist)
    clear_queue              -> InvalidRequest, no body      (does not exist)
    play_from_here           -> InvalidRequest: "missing required string field:
                                zone_or_output_id"           (exists)

A verb that exists rejects the body by naming what it wanted; a verb that does
not exist is refused with nothing at all. `play_from_here` is the only queue
verb the transport service has, which is why it is the only thing a queue row
does. Anything else -- reordering, removing, clearing -- has to happen in Roon's
own app.

**Up next** is the compensation: the queue is already live for the queue view,
so the now-playing page shows the next nine beside the record when there is
room for them, each one a `play_from_here` away.

### Proven end to end against a live Core

Discovery through all three tiers; register; silent reconnect with a stored token;
7 zones with correct `soft_limit` clamping (Workshop reads `0-50`, limited from 100)
and standby detection (network streamer, no volume object); browse across every hierarchy;
`control` returning `Success` with the state transition observed; and seek ticks
arriving at 1Hz. Confirmed audibly on the local endpoint, and again on a network streamer in another
office -- which is how the standby misreading above was caught.

## Testing

Three layers, because they catch different things and cost different amounts.

**Unit** -- pure functions, no sockets: `three_line` parsing, volume bounds and
`soft_limit` clamping, standby, the zone merge, and WebSocket framing checked
against RFC 6455's own worked example. Milliseconds.

**Integration** -- a real `ApiServer` on a real socket, driven over real HTTP and
a real WebSocket handshake, with a fake session in place of a Core. Covers
routing, error mapping (`400` vs `503` vs `502`, never `500`), the push fan-out,
and a client that vanishes mid-broadcast without stalling the Roon read loop.
This is what the narrow seam bought: five verbs is a cheap thing to double.

**Live** -- `tests/test_live.py`, skipped unless `ROON_LIVE_HOST` is set. The only
layer that can catch Roon changing something, so it exists; read-only, so it never
starts playback in anyone's house. It pins the `_tid` regression explicitly, since
that failure looks exactly like an empty network.

    ROON_LIVE_HOST=192.0.2.10 pytest tests/test_live.py

**Fixture guard** -- `scripts/check-fixtures.py`. Tests running against a
malformed fixture can pass against nonsense, so CI checks the shapes the daemon
depends on: that some zone has `now_playing.three_line`, that some output has a
`volume` and some output has none, that some output carries `soft_limit`. Without
those, three of the tests prove nothing while still passing.

**CI** -- `.github/workflows/ci.yml`: ruff on one job, pytest across 3.12 and 3.13
on another, the fixture guard on a third, JUnit XML uploaded. No dependency
install step beyond pytest, because the daemon has no runtime dependencies.

## Fixtures

Captured from the live Core by `spikes/capture-fixtures.py`, which reconnects
with the saved token and writes `spikes/fixtures/*.json`:

| Fixture | What it pins down |
|---|---|
| `zones.json` | 7 zones, `three_line` shapes, per-zone `settings`, queue counters |
| `outputs.json` | volume systems, `soft_limit`, an output with no volume at all |
| `queue.json` | 11 queue items with `three_line` and `queue_item_id` |
| `browse-browse.json` | the `Explore` root: Library, Playlists, My Live Radio, Genres, TIDAL, Settings |
| `browse-albums.json` | 2589 albums; `subtitle` carries the artist |
| `browse-artists.json` | 866 artists; `subtitle` carries "N Albums" |
| `browse-genres.json` | 21 genres; `subtitle` carries "N Artists, M Albums" |
| `browse-playlists.json` | 16 playlists; `subtitle` carries "N Tracks" |

The `subtitle` conventions matter: they are what makes the tiled landing page
readable without a metadata API. Every list gives a usable second line for free.

`.roon-token.json` is gitignored -- it is a credential for the Core.

## Status

**R1 is running on this machine.** RoonBridge installed as `you` under a
`--user` unit, routed through `plug:pipewire`, appearing in Roon as
`Studio (Omarchy)` and playing. The daemon runs as its own `--user` unit,
publishes MPRIS, and Omarchy's Media bar widget picks it up. `doctor` is all
green.

Both units are installed by `bin/omarchy-roon-endpoint`: `install`, `firewall`,
`pipewire`, `daemon`.

## Releases

**R1 -- endpoint + bar widget.** This machine becomes a selectable Roon zone, and
a bar widget shows what is playing on it with basic transport. Everything is
driven from a phone or another Roon control device; there is no browsing UI here
yet. That is a genuinely useful product on day one: Roon ships no Linux endpoint
UI at all, and the hard part -- being an endpoint -- is a wrapper, not a rewrite.

**R2 -- the full client.** Now Playing, Zones, Queue, Search, browse, lyrics. The
daemon already serves all of it.

## The bar widget

A **tray-sized icon in the right cluster**, next to Audio, that opens a mini
player on click. Not an inline label: an endpoint is something you glance at and
occasionally poke, not a running commentary that shoves the clock sideways every
few minutes. The glyph carries the state -- playing, idle, daemon down -- and
everything else is one click away.

Built on the shell's `Panel` base rather than `BarWidget`, because that is the
shell's own pattern for "icon in the cluster that opens something": Bluetooth,
Network, Audio and Display are all Panels, and inheriting it gets the popup's
anchoring, keyboard handling and popout-switching for free.

The mini player holds: sleeve and track, the **zone name and state**, transport,
a volume slider, the zone list with the pinned one marked (click to re-pin), and
the announce-each-track toggle.

**IPC ownership.** `Panel` normally registers its own handler, but the service
already owns the `roon` target -- and a service is a singleton where a bar widget
is instantiated once per monitor, and a target permits only one handler. So the
panel sets `manageIpc: false` and listens for a `toggleRequested` signal on the
service instead. `omarchy-shell roon player` opens it.

### The icon

A **level meter**: four bars that rise and fall while music plays and settle into
a static waveform when it does not, struck through when the daemon is down.
Motion is the honest way to say "sound is coming out of this machine right now",
which is the one thing a glance at an endpoint wants to know.

Two earlier attempts were worse. A Nerd Font glyph was unreadable next to the
speaker and monitor either side of it. A "Roon signal path" mark -- source,
transport, endpoint -- was conceptually neat and visually weak at 16px.

**Never name a property `x`, `y`, `width`, `height` or `scale` in a QML
component.** They are FINAL on `QQuickItem`, and shadowing one makes the entire
widget fail to load with nothing in the journal but
`Cannot override FINAL property` -- no icon, no error on screen, and the rest of
the bar carries on as though the widget were simply not configured.

### The icon (earlier note)

Drawn in QML rather than shipped as an SVG, so it follows the theme with no
colour-overlay shader: a rounded app tile with a lowercase "r", **filled while
playing and outlined while idle** -- the same filled/outline language the rest of
the bar uses for state. Daemon down draws a slash instead.

A Nerd Font glyph was the first attempt and was wrong: the widgets either side
are already a speaker and a monitor, so a third generic media glyph is
unreadable at a glance, and none of them say *Roon*. Roon's own wordmark is
lowercase, and an "r" is the most detail that survives at bar size.

### The quality badge, which turned out to be possible after all

Round three of the design concluded the badge was dead: Roon's extension API
exposes no sample rate, bit depth, codec or signal path, and that is still true.
The conclusion was wrong because it only considered the *controller* half of what
this is. **This machine is also the endpoint**, and RAATServer -- running right
here -- is told precisely what to play:

    {"request":"setup","format":{"sample_type":"pcm","sample_rate":96000,
                                 "bits_per_sample":24,"channels":2}}
    alsa output setup: format is pcm 96000/24/2

`endpoint.py` reads that back from the log, tailing only the last 256 KB and
re-parsing solely when the mtime moves. The badge shows only when the pinned zone
is this machine, because another room is played by hardware this one knows
nothing about.

**There is still no file format, and there cannot be.** RAAT decodes on the Core
and streams PCM; FLAC, ALAC and AAC are resolved long before the endpoint sees
anything. So the badge reads `PCM 24/96` -- which is exactly how Roon words this
node of its own signal path -- and `DSD64` by its multiple of the CD rate.

### Gapless, confirmed rather than assumed

64 stream starts against 9 device setups on a real session, with every setup
lining up with a format change rather than a track change. Consecutive same-format
tracks stream through without the ALSA device being reconfigured. It is RAAT and
the Core doing it; nothing in this stack participates. A rate or depth change does
reconfigure the device, which is a genuine gap and what Roon's resync delay exists
for.

### The visualiser and the record's own colour

`palette.py` came across from omarchy-tidal **unchanged** -- the only module that
did -- because it depends on nothing but image bytes, and Roon serves those from
the Core exactly as TIDAL did. Exposed as `GET /palette/<image_key>`, cached per
key, and driven from MPRIS's `artUrl` so it lands the instant the track changes
rather than four seconds later on the state poll. A monochrome cover honestly
reports no colour, and the panel falls back to the theme accent rather than
tinting everything a washed-out grey.

`bin/omarchy-roon-cava` and `Visualizer.qml` came across too. cava taps
PipeWire's **default sink monitor** -- the same signal reaching the DAC -- so it
follows whatever is audible. **This only works because the bridge is routed
through `plug:pipewire`**; an exclusive-mode bridge would draw a flat line. A
decision made for system-sound coexistence turned out to be the one that made a
real spectrum analyser possible.

The timeline, the volume fill and the play button all take the sleeve's colour,
so the player belongs to the album rather than to the chrome.

### The zone picker is deliberately quiet

Roon's own apps keep it as a speaker and a name at the foot of the player, not a
form control. A full-width dropdown made choosing a room look like the main thing
you came to do, when almost always you came to press pause. It is a muted line
that expands in place, and collapses again when the panel closes.

### Notifications are suppressed while the panel is open

A card announcing the track, drawn on top of the player already showing the
track, is pure duplication -- and on a right-cluster panel it lands directly over
it. The panel sets a **transient** `suppress` flag (never persisted, so it cannot
leave announcements off for good) while it is open.

The subtlety: suppression still updates the notifier's bookkeeping, so closing
the panel does not then announce a track that changed while it was open. The user
watched that change happen; announcing it afterwards is stale.

### A gotcha that costs an hour if you hit it cold

**`Ui/Panel` is a bare `Item` with no size of its own**, and the bar sizes every
slot from `implicitWidth`. A Panel-based widget that does not set

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

occupies **zero pixels**: it is present in the layout, loads without a single
warning, answers IPC correctly -- and is invisible and unclickable. Nothing in
the logs says so. Every first-party Panel sets those two lines; `BarWidget`-based
widgets do not need them, which is exactly why it is easy to miss when moving
from one base to the other.

Related: `dimmed` on a `WidgetButton` lowers opacity far enough on some themes to
read as "not there". The glyph already distinguishes playing from idle, so it is
not worth the ambiguity.

### The original inline-label version

`manifest.json` + `qml/`, plugin id `quickshell.roon`, kinds `service` and
`bar-widget`. Enabled with `omarchy plugin enable quickshell.roon`, which places
it in the bar automatically.

**Why a dedicated widget when Omarchy ships a generic MPRIS one.** Two reasons,
both discovered rather than assumed:

1. `omarchy.media` selects among *every* player on the bus and offers cycling
   between them. With `mopidy` and `playerctld` also present there is no
   guarantee it is showing Roon. This widget binds to
   `org.mpris.MediaPlayer2.omarchy_roon` **specifically** -- the same trick the
   TIDAL plugin uses to pin itself to mopidy.
2. MPRIS has no vocabulary for rooms, so a generic widget cannot tell you *which
   zone* it is showing. Since the media keys act on that room from this keyboard,
   the zone name is not decoration.

**Two sources, chosen for what each is good at.** MPRIS carries track, art and
play state -- push-based over D-Bus, instant, free. The daemon's HTTP API is
polled every 4s for what MPRIS cannot express: the zone name, the zone list, and
pinning. **Quickshell ships no WebSocket module and `qt6-websockets` is not
installed**, so the daemon's `/ws` is unreachable from QML -- which matters less
than it sounds, because everything time-sensitive already arrives over MPRIS.

The widget never hides. An idle endpoint is still worth seeing, because someone
may start playing to it from a phone at any moment; collapsing to nothing would
make it look broken exactly when it is working and waiting.

Click plays/pauses, scroll skips, middle click cycles zones. IPC:
`omarchy-shell roon status|zone|playpause|next|previous|notifications|refresh`.

## Track notifications

`backend/omarchy_roond/notify.py`. The record goes on screen as playback moves
on, through the desktop's own notification daemon, each one replacing the last
rather than stacking a card per song.

The guards are the feature. Announce on every zone push and you get one card per
second while music plays, one on every pause, and one for whatever happened to be
playing when the daemon started -- which is the difference between something
people keep and something they turn off. So: never on the first update, only on
an actual track change, only while playing. Toggle with `POST /notifications`.

Art has to be a local file -- notification daemons do not fetch `http://` for
`image-path` -- so the sleeve is cached to `~/.cache/omarchy-roon/art` first, and
the notification goes out without art rather than late if that fails.

## MPRIS: what the surfaces are built on

Omarchy 4 ships `omarchy.media` -- a **generic MPRIS bar widget** with
now-playing and transport -- and the shell already routes media keys and the
volume OSD through MPRIS. So publishing one MPRIS player gives the endpoint a
bar presence, working media keys and an OSD **without a line of QML**. R1 needs
no plugin and no app.

`backend/omarchy_roond/mpris.py`, bus name
`org.mpris.MediaPlayer2.omarchy_roon`. Needs `python-gobject`, already a pacman
package and already a dependency wherever the TIDAL backend runs; if it is
missing the daemon says so and carries on without a bar presence rather than
refusing to start.

Four seams worth naming:

* **MPRIS is one player; Roon is many zones.** The pinned zone stands in for
  "this machine's music". There is no MPRIS vocabulary for rooms, so the zone
  name rides in `Identity` -- the bus reads `Roon — Lounge`. A client cannot
  *switch* zones through MPRIS, which is the one thing a dedicated bar widget
  would add later, if it ever earns its place.
* **Roon has no track ids.** `mpris:trackid` must be an object path that changes
  with the track or clients will not notice a new song, so it is synthesised from
  a counter keyed on title/artist/album.
* **Art is a plain Core URL**, which is exactly what `mpris:artUrl` wants -- no
  proxy, no temp files.
* **Position is polled by clients but pushed by Roon at ~1Hz.** Interpolating
  from a monotonic anchor between ticks is what makes a progress bar move rather
  than step.

Verified on the live bus: every property readable, metadata complete with a Core
art URL, and `playerctl` lists it alongside mopidy.

### The pinned zone

One zone stands for this machine. The default is the zone this machine plays to,
found by matching the hostname against zone and output names (RoonBridge names
its outputs after the host); failing that, the first zone. An explicit pin is
persisted to `config.json` and exposed as `POST /pin`.

Following whichever zone happens to be playing was rejected: the bar widget would
change rooms under you whenever someone elsewhere in the house pressed play.

## The endpoint

`bin/omarchy-roon-endpoint` -- `doctor` (default, read-only), `install`,
`firewall`, `start`/`stop`/`restart`/`logs`, `uninstall`.

**It wraps `aur/roonbridge`; it does not reimplement it.** The package already
downloads and packages Roon's binaries and pacman tracks them. Writing another
downloader would duplicate that for nothing.

What the package does *not* do, and nothing else does either, is the three things
this script exists for:

1. **Run RoonBridge as you, not root.** The packaged unit is `User=root`, and root
   cannot reach a per-user PipeWire session -- so a root bridge can only take a
   raw ALSA device exclusively, silencing system audio and the visualiser. We
   disable and mask the packaged unit and install a `--user` one instead.
2. **Point RAATServer at `plug:pipewire`**, not `default`. PipeWire's default
   device answers ALSA hardware probing incorrectly; the plug layer wraps it so
   probing succeeds.
3. **Open the ports RAAT needs** -- `9200/tcp`, `30000-65535/tcp`, and critically
   **`30000-65535/udp` for clock sync**. Miss the UDP range and streams die about
   a second in, silently, presenting as random track skipping rather than as a
   firewall problem. Omarchy ships `ufw` default-deny, so every user hits this.

One more thing the packaging gets wrong for our purposes: **`/opt/RoonBridge` must
be writable by the user running it.** RoonBridge self-updates by unpacking into
its own directory (`start.sh --update`), and root ownership makes that fail
silently until the Core refuses an out-of-date endpoint. `install` takes
ownership; `doctor` re-checks it, because a pacman upgrade resets it.

### Three bugs worth remembering

**Falsy zero in a dB volume.** `volume.get("value") or minimum` looks harmless
until a dB control sits at **0 dB, which is full volume and is falsy**, so the
default fires on exactly the value meaning "loudest" and MPRIS reports silence.
Caught only because the real endpoint reported `Volume 0` while audibly playing.
Pinned by a regression test.


**PyGObject's D-Bus vtable arity.** `register_object`'s get-property callback
takes `(conn, sender, path, iface, prop)` -- no trailing `GError`, unlike the C
API. Get it wrong and it fails in the most misleading way available: the bus name
is claimed, introspection is perfect, and *every* property read returns "Unable
to retrieve property".

**A throw after the WebSocket handshake hangs the client forever.** The 101 has
already gone out, so a client that then gets neither a frame nor a close just
waits -- a hung UI with no error anywhere. Any failure building the initial
snapshot now sends a close frame and drops the connection.

### A correction

An earlier draft rejected `aur/roonbridge` as dangerously stale, comparing its
2.60.1501 against the Core's 2.71. That was wrong. Roon's own *production*
download is **also 2.60 (build 1501)** -- 2.60 is the bootstrap, and `start.sh`
has an `--update` path because the bridge updates itself from the Core after
first contact. The package is current. The reason to bypass its systemd unit is
root-versus-user, not staleness.

## v1 fence

**Ships:** Now Playing, Zones, Queue, Search, library-roots landing page, generic
browse, lyrics, MPRIS, bar widget, setup wizard.

**Does not ship:** zone grouping/ungrouping, transfer-zone, Internet Radio,
Composers/Tags/Bookmarks, the `settings` hierarchy, multi-Core, History.

Grouping and transfer-zone are a few API calls each; the UI for "which outputs, in
what order, whose queue survives" is where the time goes.

## What dies coming from omarchy-tidal

| Feature | Fate |
|---|---|
| Quality badge (24/192) | **Dead as designed.** Roon exposes no format data. Reborn as an *output* badge read from PipeWire at the sink — more honest than the source-tier badge ever was, local zone only |
| Personalised home page | **Dead.** No metadata API. Replaced by the library-roots landing page |
| Artist / album pages | **Dead as bespoke screens.** Roon's browse tree renders them |
| Favourite (`SUPER+ALT+M`) | **Dead.** No API — favouriting lives in browse action lists, unreachable from `now_playing`. Key repurposed to Zones |
| Structured metadata | **Gone.** `three_line.line1/2/3` and a convention |
| Lyrics | Survives, degraded. No track IDs, so fuzzy match on artist + title with a +/-2s duration gate. Empty beats wrong |
| Cava visualiser | Survives **only** because of the PipeWire routing choice |
| `palette.py`, `Design.js`, chrome, wizard machinery | Survive intact — the real inheritance |

Gained in exchange: multi-zone, a real queue, per-output volume, Roon Radio, and
Roon's own metadata quality.

## Prior art on Linux

Worth reading before building. `roon-tui`, `roon-cli`, `roon-kit`,
`roon-mpris-multizone-git` (multi-zone MPRIS via media keys),
`roon-now-playing-git` (a waybar module), and `roon-proton` — the official Windows
Roon app under Proton/umu-launcher on XWayland, actively maintained. That last one
is the honest measure of demand: people will run Windows in a compatibility layer
to get a real Roon GUI. It is not a competitor on native shell integration, but it
proves the appetite.

## Spike results

### The MOO stack is proven end to end

`spikes/core-handshake.py` opens a WebSocket to `ws://192.0.2.10:9330/api`,
hand-rolls RFC 6455 client framing and sends `com.roonlabs.registry:1/info` --
the one call a Core answers before any pairing or approval. It came back:

    MOO/1 COMPLETE Success
      core_id           00000000-0000-0000-0000-000000000000
      display_name      the Core
      display_version   2.70 (build 1671) production

Transport, MOO framing and the Core are all healthy. Nothing in the architecture
above is blocked.

**The API port on this Core is 9330 -- the same port that serves the Display web
app.** `node-roon-api` always reads `http_port` from the SOOD reply, so this is
not guaranteed, but 9330 is the right first guess for manual entry and for a LAN
sweep, before falling back to probing every open port for a WebSocket upgrade at
`/api`.

### Discovery is still broken, and it is the firewall

`spikes/sood-discovery.py` sends a SOOD query whose framing is verified byte-for-
byte against `sood.js`, receives on port 9003 with multicast membership joined as
the reference does, and sends to the multicast group plus every interface
broadcast address. **No Core answers.**

Cause: Omarchy ships `ufw` enabled with `DEFAULT_INPUT_POLICY="DROP"` and no rule
for 9003, so the inbound reply is dropped before it arrives. Discovery cannot work
on a default Omarchy install. This is a shipping-blocker for every user, not a
quirk of this machine.

### A hypothesis that was wrong

An earlier sweep found no MOO endpoint on the Core and concluded the API port was
unpublished by a bridge-networked container. That was wrong -- port 9330 returned
`503` because the Core was mid-restart. The API is reachable. Container networking
may still break *multicast* for Cores in Docker, which is a real reason to keep
manual entry as a first-class path, but it is not this Core's problem.

The value of the spike stands: it found the firewall blocker before a line of the
daemon was written, and the wizard grew rung 0 as a result.
