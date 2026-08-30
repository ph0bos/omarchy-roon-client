"""Browsing, which is a conversation with a cursor rather than a query.

Roon's browse API is not "fetch a page". The Core holds a *cursor* per
`multi_session_key`, and every call moves it:

    browse(item_key=...)   push into that item, and say what is there now
    load(offset, count)    read a window of wherever the cursor is

So a page is always two calls, and they must not be interleaved with anyone
else's. Two surfaces sharing a key yank each other around; two requests on the
SAME key racing each other are the same bug arriving down one wire. HTTP gives
no ordering guarantee between two requests, so the pair is done here, under a
lock held per session key, and served as one route.

That is the whole reason this module exists rather than QML calling `/browse`
and `/load` itself.

    browse -> action "list"     there is a list to read: load it
              action "message"  the Core is saying something (often an error)
              anything else     an item changed in place; nothing to load

Only the "list" path is verified against a live Core -- it is what R1's
`--browse` walked. The others come from `node-roon-api-browse`, so unknown
actions are passed through untouched rather than guessed at: a surface can say
"the Core said X" honestly, where inventing a list would be a lie.
"""
from __future__ import annotations

import threading

# Roon's own hierarchy names. Jumping straight into one avoids walking the tree
# from the root to reach, say, every album.
HIERARCHIES = ("browse", "playlists", "internet_radio", "albums", "artists",
               "genres", "composers", "search")

DEFAULT_COUNT = 100
MAX_COUNT = 500


class SessionKeys:
    """One lock per browse cursor.

    Locks are never removed: a surface's key is a fixed string ("browse",
    "search"), so the map is bounded by the number of surfaces rather than by
    anything a user does.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, session_key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(session_key)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_key] = lock
            return lock


def page(session, keys: SessionKeys, session_key: str, hierarchy: str = "browse",
         item_key: str | None = None, input: str | None = None,  # noqa: A002
         offset: int = 0, count: int = DEFAULT_COUNT, pop_all: bool = False,
         pop_levels: int | None = None, zone_id: str | None = None,
         refresh_list: bool = False) -> dict:
    """One move of the cursor, and the window it lands on.

    `input` is how search works: the search hierarchy answers with an item
    carrying an `input_prompt`, and you browse it again with what was typed.
    """
    if hierarchy not in HIERARCHIES:
        raise ValueError(f"unknown hierarchy: {hierarchy}")
    count = max(1, min(int(count), MAX_COUNT))
    offset = max(0, int(offset))

    opts: dict = {"multi_session_key": session_key}
    if item_key:
        opts["item_key"] = item_key
    if input is not None:
        opts["input"] = input
    if pop_all:
        opts["pop_all"] = True
    if pop_levels:
        opts["pop_levels"] = int(pop_levels)
    if refresh_list:
        opts["refresh_list"] = True
    if zone_id:
        # Playing something needs a zone: an action item like "Play Now" acts on
        # the zone the browse session was told about, not on a global "current".
        opts["zone_or_output_id"] = zone_id

    with keys.lock(session_key):
        reply = session.browse(hierarchy, **opts)
        body = reply.body or {}
        action = body.get("action")

        if action != "list":
            # A message, or an item that changed in place. There is no list to
            # read, and asking for one would move a cursor that did not move.
            return {
                "action": action,
                "message": body.get("message"),
                "is_error": bool(body.get("is_error")),
                "item": body.get("item"),
                "list": None,
                "items": [],
                "offset": 0,
                "session_key": session_key,
                "hierarchy": hierarchy,
            }

        listing = body.get("list") or {}
        page_body = (session.load(hierarchy, offset, count,
                                  multi_session_key=session_key).body) or {}

    return {
        "action": "list",
        "message": None,
        "is_error": False,
        "item": None,
        "list": listing,
        "items": page_body.get("items") or [],
        # What the Core actually gave us, which is not always what was asked
        # for: a list shorter than the window ends early.
        "offset": page_body.get("offset", offset),
        "session_key": session_key,
        "hierarchy": hierarchy,
    }
