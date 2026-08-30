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

## Decide this first

**Standalone app, or an Omarchy `overlay` plugin surface?** R1 answered "both,
with the daemon as the seam", and it does not matter until now. It matters here.

- **Overlay plugin** (what `omarchy-tidal` does): one more `entryPoints.overlay`
  in `manifest.json`, summoned with a keybinding. Gets `qs.Ui` and `qs.Commons`
  for free, so every component already written keeps working, and the theme is
  simply correct.
- **Standalone app**: its own window, its own process. **Cannot `import qs.Ui`** —
  no `Color`, no `Style`, no `BorderSurface`, no `PanelSlider`. It needs a theme
  adapter that reads Omarchy's active theme (`~/.local/state/omarchy/current/`)
  and republishes those names, plus its own copies of the shell primitives.

The brief said "it's an app, not a plugin". The honest cost of that is the theme
adapter and a component library; the honest benefit is a window that does not
live inside the shell process. **Do not start building until this is settled**,
because it decides whether the existing QML is reusable as-is.

## Still outstanding from R1

**The first-run setup wizard was chosen and never built.** The five rungs exist
in `bin/omarchy-roon-endpoint doctor`, but only as a terminal command. The
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

- **No queue route.** `RoonSession` has no `subscribe_queue` or `play_from_here`,
  though both are proven in `spikes/capture-fixtures.py` and a `queue.json`
  fixture exists. Add `subscribe_queue(zone, max_item_count)` — one subscription
  per pinned zone at ~100 items, re-subscribed only on zone change.
- **No browse session management.** `browse()`/`load()` pass `multi_session_key`
  straight through, so R2 must allocate and track one per surface. See below.

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
is for everything MPRIS cannot express. A standalone app in another toolkit could
use `/ws` — another point for the app-vs-plugin decision.

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

1. Settle app vs overlay.
2. Add the queue to the daemon (`subscribe_queue`, `play_from_here`, a `/queue`
   route) — it is the one API gap.
3. Build the first-run wizard, since it is owed from R1 and unblocks anyone who
   is not you.
4. Browse navigation, with one `multi_session_key` per surface.
5. Search on its own session key, debounced.
6. Artist and album views as positions in the browse tree, not as objects.
