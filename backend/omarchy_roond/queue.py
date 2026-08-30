"""The queue for one zone, merged from Roon's subscription deltas.

The same shape as `zones.py` and for the same reason: the Core sends the whole
list once and then edits it forever, so the merge is the part worth isolating and
testing offline.

    Subscribed    replace everything from `items`
    Changed       apply `changes` in order: remove(index, count), insert(index, items)
    Unsubscribed  drop everything

One subscription at a time, following the pinned zone. A queue is ~100 items of
three display lines each; keeping one per zone would mean holding a copy of every
room's list to render one of them.

**Only `Subscribed` is verified against a live Core** -- `spikes/fixtures/queue.json`
is a capture of it. The `changes` operations come from `node-roon-api-transport`
and have not been observed here, so an operation this does not recognise sets
`stale` instead of guessing: a queue quietly out of step with the Core is worse
than one that re-fetches. `RoonSession` re-subscribes when it sees that flag.
"""
from __future__ import annotations

from . import text


def entry(raw: dict) -> dict:
    """One queue item in the shape the interface renders.

    Queue items carry the same `three_line`/`two_line` display strings as
    `now_playing`, so the parsing is `text.track`'s -- there is no more
    structured metadata here than there is anywhere else in the API.
    """
    t = text.track(raw)
    return {
        # The only durable handle on a queue item, and what `play_from_here`
        # takes. Position is not usable as an id: the list edits underneath it.
        "queue_item_id": raw.get("queue_item_id"),
        "title": t["title"],
        "artist": t["artist"],
        "album": t["album"],
        "image_key": t["image_key"],
        "length": t["length"],
    }


class QueueStore:
    def __init__(self) -> None:
        self.zone_id: str | None = None
        self.stale = False
        self._items: list[dict] = []

    # -- queries ---------------------------------------------------------
    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[dict]:
        return list(self._items)

    def summary(self) -> dict:
        """What `/queue` serves and the WebSocket pushes."""
        return {"zone_id": self.zone_id, "items": [entry(i) for i in self._items]}

    # -- merging ---------------------------------------------------------
    def reset(self, zone_id: str | None) -> None:
        """Point at a different zone, holding nothing until it answers."""
        self.zone_id = zone_id
        self.stale = False
        self._items = []

    def apply(self, response: str, body: dict | None) -> bool:
        """Merge one subscription message. Returns True if the list changed."""
        body = body or {}

        if response == "Subscribed":
            self._items = list(body.get("items") or [])
            self.stale = False
            return True

        if response == "Unsubscribed":
            changed = bool(self._items)
            self._items = []
            return changed

        if response != "Changed":
            return False

        changed = False
        for change in body.get("changes") or []:
            operation = change.get("operation")
            index = int(change.get("index") or 0)
            if operation == "remove":
                count = int(change.get("count") or 0)
                if count > 0:
                    del self._items[index:index + count]
                    changed = True
            elif operation == "insert":
                items = list(change.get("items") or [])
                if items:
                    self._items[index:index] = items
                    changed = True
            else:
                # Applying the rest would leave a list that looks right and is
                # not. Stop, and let the session re-subscribe for the truth.
                self.stale = True
                break
        return changed
