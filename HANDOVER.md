# Handover: the full Roon client (R2)

R1 is shipped and listed-pending. This is what the next person needs to know to
build the client without rediscovering anything.

Read `CONTEXT.md` first — it is the design log and holds the *why* behind every
decision below. This file is the *what next*.

---

## Where things stand

| | |
|---|---|
| Repo | https://github.com/ph0bos/omarchy-roon-client |
| Released | v0.1.1, CI green (7 jobs), marketplace submission [#3618](https://github.com/omacom/omarchy-plugin-marketplace/issues/3618) awaiting maintainer capability review |
| Shipped | endpoint (RoonBridge as user, via PipeWire), daemon, bar icon + mini player, MPRIS, notifications, quality badge, spectrum analyser |
| Tests | 103 + 7 live (opt-in), fixtures scrubbed, CI enforces the scrub |

## What R2 is

The full client: **browse, search, queue, artist and album views** — the surfaces
R1 deliberately fenced out because you drive playback from your phone.

The daemon already speaks everything needed for this. R2 is mostly interface.

**Shipped so far:** the queue end to end (daemon subscription, `/queue`,
`play_from_here`), the overlay that renders it, a now-playing view with the
analyser, the quick menu, the keyboard map, the first-run wizard on `/setup`,
and browse + search on `/page`. What is left is presentation rather than
protocol: a grid where a list is the wrong shape, and album and artist headers.

## Settled: it is an overlay, and the TIDAL UX ports into it

**R2 is an `entryPoints.overlay` surface, not a standalone app.** One more entry
in `manifest.json`, summoned with a keybinding, with `qs.Ui` and `qs.Commons`
available — so the theme is simply correct and nothing needs a theme adapter.

What settled it: `~/Projects/omarchy-tidal` already holds ~5,400 lines of QML for
exactly these surfaces (`Overlay.qml`, `HomeView`, `DetailView`, `PlayerView`,
`NowPlayingView`, `SetupWizard`, and the component library), and every one of
them imports `qs.Commons` or `qs.Ui`. As an overlay they port with their theming
intact; as an app each would be a rewrite against a theme adapter first.

The port is a substitution, not a rewrite: `TidalApi.js` → `Roond.js` (R1 has
it), Mopidy RPC → the local API. The one shape that genuinely differs is the
data: Tidal returns `{id, title, artist}` objects, Roon returns positions in a
browse tree. See *R2 is an overlay* in `CONTEXT.md`.

## Still outstanding from R1

~~**The first-run setup wizard was chosen and never built.**~~ **Built.** The
daemon computes the ladder at `GET /setup` and `qml/components/SetupWizard.qml`
renders it, polling every 2s while on screen. See *The menu, the keyboard map,
and the wizard* in `CONTEXT.md` for the three decisions inside it — the one
worth carrying is that a `blocked` rung outranks an earlier `pending` one,
because pairing happens during registration and "first unfinished" points at the
wrong step. The
decision was: put it in the UI so a new user never opens a terminal.

    0. discovery reachable (ufw allows udp/9003, or a host was entered)
    1. Core found
    2. paired
    3. extension approved in Roon → Settings → Extensions  ← blocking, poll it
    4. RoonBridge running
    5. zone visible to the Core

Rung 3 is the one that traps people: an unapproved extension does not fail, it
simply never answers. `AwaitingApproval` in `session.py` already models this and
the daemon pushes an `awaiting_approval` event; nothing renders it yet.

## Gaps in the daemon R2 will hit immediately

- ~~No queue route.~~ **Done.** `queue.py` holds the merge, `RoonSession` keeps
  one subscription following the pinned zone at 100 items, and the API gained
  `GET /queue`, `POST /play_from_here` and a `queue` WebSocket event. `/queue`
  reads the daemon's own memory, so it is as cheap as `/zones`, and `--demo`
  serves a queue too. **The one thing to know:** only the `Subscribed` payload is
  verified against a live Core — the `changes` operations come from
  `node-roon-api-transport`, so an operation `QueueStore` does not recognise sets
  `stale` and the session re-subscribes rather than guessing. If a live Core ever
  shows a third operation, that is where to add it.
- ~~No browse session management.~~ **Done.** `browse.py` owns a lock per
  `multi_session_key` and `POST /page` is the browse+load pair as one move.
  Two rules survive: every surface passes its OWN key, and paging uses `/load`
  so it does not move the cursor.

## Constraints that will bite

**Browse is a stateful cursor, one per `multi_session_key`.** Two surfaces
browsing at once without distinct keys yank each other around. Search is the case
that forces it; it needs its own key, always.

**There is no metadata API.** `now_playing` is three pre-formatted display
strings and an image key — no track, album or artist ids. Browse returns
`{title, subtitle, image_key, hint}` and a cursor. Every "artist page" is a
position in a server-driven tree, not an object you can fetch.

**Search is a conversation.** Browse returns an item carrying `input_prompt`; you
re-browse with `opts.input`; then you load. Two round trips minimum, no typeahead.
Debounce ~350ms.

**Quickshell ships no WebSocket module** and `qt6-websockets` is not installed, so
QML cannot use the daemon's `/ws`. Reactive playback state comes over MPRIS; HTTP
is for everything MPRIS cannot express. As an overlay, that settles it: playback state
comes over MPRIS, and everything MPRIS cannot express is an HTTP call.

**Art comes from the Core**, not the daemon: `<image_base>/<key>?scale=fit&width=…`.
`image_base` is in `/state`.

**Browse hierarchies** are `browse`, `playlists`, `internet_radio`, `albums`,
`artists`, `genres`, `composers`, `search`. Jumping straight into one avoids
walking the tree.

## Gotchas that cost real time this session

- **Never name a QML property `x`, `y`, `width`, `height` or `scale`.** They are
  FINAL on `QQuickItem`; shadowing one makes the whole widget fail to load with
  nothing but `Cannot override FINAL property` in the journal. No error on screen.
- **`Ui/Panel` has no size of its own.** A Panel-based widget must set
  `implicitWidth`/`implicitHeight` or it occupies zero pixels: invisible,
  unclickable, and silent.
- **A QML `color` cannot be compared to a string.** `c !== "transparent"` is a
  type mismatch that is always true.
- **SOOD deduplicates on `_tid`.** Reuse one and every query after the first is
  answered with silence, which looks exactly like an empty network.
- **PyGObject's D-Bus vtable takes five args for a property getter**, not six —
  no trailing `GError`. Get it wrong and the bus name is claimed, introspection
  is perfect, and every read returns "Unable to retrieve property".
- **The plugin is symlinked into `~/.config/omarchy/plugins/`.** Hot-reload does
  not always pick changes up; `omarchy restart shell` is the reliable way, and
  a stale shell is why an "impossible" bug will not reproduce.

## Working on it

```bash
python -m omarchy_roond --serve --demo   # synthetic zones, no Core, no subscription
python -m omarchy_roond --browse         # exercise a real Core from the terminal
pytest                                    # 103 tests, no Core
ROON_LIVE_HOST=<core-ip> pytest tests/test_live.py
./bin/omarchy-roon-endpoint doctor        # read-only; first thing when anything breaks
```

**`--demo` is how the UI gets built and photographed.** It serves invented zones,
invented tracks and a generated sleeve, so no subscription is needed and nothing
personal reaches a screenshot. Screenshots for the README are taken this way, on
the `osaka-jade` theme; restore the theme afterwards.

**ruff is not packaged on this machine.** Fetch the standalone binary or CI will
be the first thing to see a lint error:

```bash
curl -sSL https://github.com/astral-sh/ruff/releases/latest/download/ruff-x86_64-unknown-linux-gnu.tar.gz | tar -xz
```

**Never commit anything captured from a real Core without scrubbing it.**
`scripts/sanitise-fixtures.py` does it reproducibly and CI enforces `--check`.
Room names are a floor plan; a library is a listening history.

## Suggested order

1. ~~Settle app vs overlay.~~ Overlay.
2. ~~Add the queue to the daemon.~~ Done.
3. ~~Port `Overlay.qml` and the component library across.~~ **Done.** The
   overlay ships with four views -- now playing, the library, the queue and
   first-run -- on the ported chrome, transport strip and component library.
   See *The overlay, as built* in `CONTEXT.md`. README screenshots are taken,
   under `--demo` on `osaka-jade`, as the working notes describe.
4. ~~Build the first-run wizard.~~ **Done**, along with the quick menu (`M`:
   modes, Roon Radio, notifications, rooms) and the keyboard map (`?`).
5. ~~Browse navigation, with one `multi_session_key` per surface.~~ **Done** —
   as `POST /page`, which does the browse+load pair under a lock per session
   key. Surfaces must never call `/browse` and `/load` themselves.
6. ~~Search on its own session key, debounced.~~ **Done**, 350ms, in the
   library view's own field.
7. ~~Artist and album views~~ **Done.** They are the browse tree — searching
   and pushing into a result lands on the artist page, because that is all an
   artist page is. A wall of covers now draws as a grid (`ArtCard`), a track
   list stays a list, and both album and artist pages wear the artwork Roon
   puts on the list object.

The layout is a sidebar down the left with the library's roots, a page beside
it, and one transport strip along the bottom — Apple Music's and TIDAL's shape,
not the header-tabs the first pass had. Now playing takes the whole window. See
*The layout* in `CONTEXT.md`.

`ArtCard` is ported. What is still unported from `omarchy-tidal` is `Shelf`,
`LibraryGrid`, `ScrollHint`, `TiltFrame` and `HomeView` — the furniture for a
*landing page* of library roots, recently played and a Roon Radio toggle, which
is the obvious next surface and the one thing the browse tree cannot give you
for free.
