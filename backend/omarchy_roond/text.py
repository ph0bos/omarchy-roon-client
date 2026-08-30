"""What Roon tells us about a track, in the shape the interface wants.

Roon gives an extension no structured metadata at all. `now_playing` carries
three pre-formatted display strings and nothing else -- no track id, no album id,
no artist id, no format. Verified against a live Core, the convention is:

    one_line.line1     "Parallax - Nocturne Atlas"
    two_line.line1     "Parallax"          title
    two_line.line2     "Nocturne Atlas"         artist
    three_line.line1   "Parallax"          title
    three_line.line2   "Nocturne Atlas"         artist
    three_line.line3   "Parallax"          album

So `three_line` is the only sensible source, and everything downstream -- the bar
widget label, the notification, the lyrics lookup -- comes from parsing it. These
are pure functions over dicts so they can be tested against captured fixtures
without a Core.
"""
from __future__ import annotations


def track(now_playing: dict | None) -> dict:
    """A track's title, artist and album from a `now_playing` object.

    Missing lines become empty strings rather than None: every caller renders
    these, and a template that has to guard each field is a template that will
    one day print "None".
    """
    if not now_playing:
        return {"title": "", "artist": "", "album": "", "image_key": None,
                "artist_image_keys": [], "length": 0, "seek_position": 0}

    lines = now_playing.get("three_line") or {}
    two = now_playing.get("two_line") or {}
    return {
        "title": lines.get("line1") or two.get("line1") or "",
        "artist": lines.get("line2") or two.get("line2") or "",
        "album": lines.get("line3") or "",
        "image_key": now_playing.get("image_key"),
        # Undocumented, but present on every Core we have seen: artist
        # photography, which the Now Playing backdrop can use.
        "artist_image_keys": list(now_playing.get("artist_image_keys") or []),
        "length": now_playing.get("length") or 0,
        "seek_position": now_playing.get("seek_position") or 0,
    }


def label(now_playing: dict | None, separator: str = " · ") -> str:
    """One line for the bar widget. Empty when nothing is playing."""
    t = track(now_playing)
    parts = [p for p in (t["title"], t["artist"]) if p]
    return separator.join(parts)


def volume_bounds(output: dict) -> tuple[float, float] | None:
    """The range a volume slider may actually use, or None if there is no fader.

    Two traps, both observed on a live Core:

    * An output can have no `volume` object at all, permanently and while playing
      -- a Bluesound network streamer handles its own volume and never exposes one to
      Roon. There is nothing to draw; a disabled slider would wrongly imply the
      control exists but is unavailable.
    * `soft_limit` is undocumented but real, and is lower than `max` on any zone
      the owner has volume-limited. Drawing `min..max` lets the user push past a
      ceiling the Core will refuse, which reads as the app being broken.
    """
    vol = output.get("volume")
    if not vol or vol.get("type") == "incremental":
        return None
    if vol.get("value") is None or vol.get("min") is None or vol.get("max") is None:
        return None

    low = float(vol["min"])
    high = float(vol["max"])
    for ceiling in ("soft_limit", "hard_limit_max"):
        if vol.get(ceiling) is not None:
            high = min(high, float(vol[ceiling]))
    if vol.get("hard_limit_min") is not None:
        low = max(low, float(vol["hard_limit_min"]))
    return (low, high) if high > low else None


def is_standby(output: dict) -> bool:
    """True when an output's source control reports standby.

    Do NOT gate the transport UI on this, and do not show it in place of the
    zone's state. Tested against a Bluesound network streamer: it reports
    `source_controls[].status == "standby"` continuously, including while
    actively playing audible music. The zone's own `state` is the only authority
    on whether something is playing.

    It is a property of the *source control* -- roughly, whether the amplifier
    input is selected -- and plenty of devices never report it accurately. Treat
    it as a dim hint on the zone row at most, never as a reason to disable
    controls or to tell the user the device is asleep.
    """
    for control in output.get("source_controls") or []:
        if control.get("status") == "standby":
            return True
    return False
