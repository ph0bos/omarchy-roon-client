# Handover: after v0.2.1

R2 shipped. This is what the next person needs to know to keep building without
rediscovering anything.

Read `CONTEXT.md` first — it is the design log and holds the *why* behind every
decision below. This file is the *what next*.

---

## Where things stand

| | |
|---|---|
| Repo | https://github.com/ph0bos/omarchy-roon-client |
| Released | **v0.2.1**, CI green, Release workflow gates the tag on the manifest version |
| Listing | marketplace submission [#3618](https://github.com/omacom/omarchy-plugin-marketplace/issues/3618) validated at v0.2.1, still awaiting the maintainer's **capability review** — nothing a push can move |
| Shipped | endpoint (RoonBridge as user, via PipeWire), daemon, bar icon + mini player, MPRIS, notifications, quality badge, analyser — **and the player**: sidebar, home, now playing, library, browse, search, queue, first-run wizard |
| Tests | 161 + 7 live (opt-in), fixtures scrubbed, CI enforces the scrub |

**To update the marketplace listing, edit the issue body.** Validation re-runs on
`issues: edited`, not on comments — see `route-issue-automation.yml` in the
marketplace repo. A comment does nothing.

## What the API cannot do, with evidence

These were each established against a live Core. Do not spend an afternoon
re-testing them; do re-test if Roon ships a new API version.

- **A queue cannot be edited.** `play_from_here` is the transport service's only
  queue verb. Asked with an empty body, `remove_from_queue`, `move_in_queue`,
  `reorder_queue` and `clear_queue` all answer the way a method that does not
  exist answers (`InvalidRequest`, no body), where a real verb names the field
  it wanted. `spikes/probe-queue-verbs.py` re-runs that question safely.
- **There is no recently-played and no recently-added.** The browse root an
  extension sees is Library, Playlists, My Live Radio, Genres, Settings; Library
  holds Search, Artists, Albums, Tracks, Composers, Tags. Home is built from
  what exists rather than from what Apple Music would show.
- **There is no metadata API.** `now_playing` is three display strings and an
  image key. An artist page is a *position in a browse tree*, which is why
  opening one works and linking to one cannot.
- **There are no lyrics.**
- **QML cannot reach the daemon's `/ws`.** Quickshell ships no WebSocket module.
  Reactive playback state comes over MPRIS; everything else is HTTP.

## Constraints that still bite

**Browse is a stateful cursor per `multi_session_key`.** Use `POST /page`, which
does the browse+load pair under a lock per key. Never call `/browse` and `/load`
from a surface. Paging uses `/load` on purpose: reading another window must not
move the cursor.

**An `item_key` is only valid inside the session that produced it.** Anything
handing a row between surfaces sends the hierarchy and the *index*, and the
receiving view re-browses and opens that position. Home does exactly this.

**Every async navigation must take a ticket.** A serial bumped per request, with
only the current ticket allowed to draw. Three separate bugs in this project were
the same shape: a slow answer landing after a newer question and painting the
wrong page. Paging checks it too, because a stale window appends into the wrong
list.

**Art comes from the Core**, not the daemon: `<image_base>/<key>?scale=fit&width=…`.
`image_base` is in `/state`, and a session may override it — `--demo` serves its
own sleeve.

## Gotchas that cost real time

- **Never name a QML property `x`, `y`, `width`, `height` or `scale`** — FINAL on
  `QQuickItem`; shadowing one makes the widget fail to load with nothing but
  `Cannot override FINAL property` in the journal.
- **A `Row` or `Column` ignores its children's anchors.** Two bugs came from this,
  including a mark that was never once aligned with the wordmark beside it. If
  you need to position a child, do not put it in a positioner.
- **A binding derived from a property is not reliably current inside that
  property's own change handler.** Compute the value in the handler instead.
- **A synthetic keypress cannot test a Hyprland bind.** `wtype` goes through the
  virtual-keyboard protocol and never reaches the bind layer — verified with a
  probe bind that never fired. Only a person pressing the key can test one.
- **A hot reload can leave the overlay unable to map** (`Layershell screen does
  not correspond to a real screen`). `omarchy restart shell` is the fix, and
  `omarchy-shell roon status` reports how many of the plugin's windows are open,
  which says whether a summon reached the plugin at all.
- **`Ui/Panel` has no size of its own** — set `implicitWidth`/`implicitHeight`.
- **A QML `color` cannot be compared to a string.**
- **SOOD deduplicates on `_tid`.**
- **PyGObject's D-Bus vtable takes five args for a property getter**, not six.

## Working on it

```bash
python -m omarchy_roond --serve --demo   # invented zones, library and queue
python -m omarchy_roond --browse         # exercise a real Core from the terminal
pytest                                    # 161 tests, no Core
ROON_LIVE_HOST=<core-ip> pytest tests/test_live.py
./bin/omarchy-roon-endpoint doctor        # read-only; first thing when anything breaks
omarchy restart shell                     # after any QML change; hot reload is not reliable
```

**`--demo` is how the UI is built and photographed.** It now serves an invented
library — albums, artists, a working search and a twelve-track queue — so no
subscription is needed and nothing personal reaches a screenshot. README
screenshots are taken this way on the `osaka-jade` theme; restore the theme
afterwards, and **verify what is in the frame against the daemon's own data** —
a screenshot once came out showing the real library under demo artwork because
the shell had not actually restarted.

**ruff is not packaged on this machine.** Fetch the standalone binary or CI will
be the first to see a lint error.

**Never commit anything captured from a real Core without scrubbing it.**
`scripts/sanitise-fixtures.py` does it reproducibly and CI enforces `--check`.

## What is worth doing next

1. **Keyboard navigation on Home.** Every other view has it; Home is mouse-only.
2. **Zones as a surface.** Grouping outputs, per-output volume and transfer are
   in the transport API (`group_outputs`, `transfer_zone`) and nothing renders
   them — the sidebar's room row only switches the pin.
3. **Settings.** Notifications, the pinned zone's default, and the endpoint's own
   state are spread between the menu and the terminal.
4. **The marketplace review.** If a maintainer asks about the `installer`
   capability flag, it is `backend/omarchy_roond/setup.py` matching on filename:
   it computes the first-run ladder read-only and installs nothing. Renaming it
   to `firstrun.py` would remove the flag if that is easier than explaining it.
