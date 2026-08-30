from __future__ import annotations

from _fixtures import a_zone, load
from omarchy_roond import text


def test_track_parses_three_line_convention():
    np = a_zone()["now_playing"]
    t = text.track(np)
    assert t["title"] == np["three_line"]["line1"]
    assert t["artist"] == np["three_line"]["line2"]
    assert t["album"] == np["three_line"]["line3"]
    assert t["length"] > 0


def test_track_of_nothing_playing_is_all_empty_strings():
    t = text.track(None)
    assert t["title"] == t["artist"] == t["album"] == ""
    assert t["artist_image_keys"] == []
    assert t["length"] == 0


def test_track_falls_back_to_two_line():
    t = text.track({"two_line": {"line1": "Title", "line2": "Artist"}})
    assert (t["title"], t["artist"], t["album"]) == ("Title", "Artist", "")


def test_artist_image_keys_are_carried_through():
    """Undocumented in the JSDoc, present on every Core seen: artist photos."""
    np = a_zone()["now_playing"]
    if np.get("artist_image_keys"):
        assert text.track(np)["artist_image_keys"] == np["artist_image_keys"]


def test_label_omits_missing_parts():
    assert text.label({"three_line": {"line1": "T", "line2": "A"}}) == "T · A"
    assert text.label({"three_line": {"line1": "T"}}) == "T"
    assert text.label(None) == ""


def _output(name: str) -> dict:
    return next(o for o in load("outputs")["outputs"] if o["display_name"] == name)


def test_volume_bounds_respects_soft_limit():
    """The Workshop output reports max 100 but is limited to 50.

    Drawing min..max would let the user push past a ceiling the Core refuses.
    """
    out = _output("Workshop")
    assert out["volume"]["max"] == 100
    assert text.volume_bounds(out) == (0.0, 50.0)


def test_volume_bounds_of_an_ordinary_output():
    out = _output("Lounge")
    low, high = text.volume_bounds(out)
    assert (low, high) == (0.0, 100.0)


def test_output_with_no_volume_control_has_no_bounds():
    assert text.volume_bounds(_output("Network Streamer")) is None


def test_incremental_volume_has_no_bounds():
    """'+' and '-' only, no value and no range. There is no slider to draw."""
    assert text.volume_bounds({"volume": {"type": "incremental"}}) is None


def test_standby_is_detected():
    assert text.is_standby(_output("Network Streamer")) is True
    assert text.is_standby(_output("Lounge")) is False


def test_standby_does_not_imply_silence():
    """A network streamer reports standby while playing audible music.

    Captured from a Bluesound network streamer, whose name is scrubbed along with the
    rest of the fixture.

    Guards the assumption this code originally shipped with -- that standby meant
    the hardware was asleep and pressing play would do nothing. It does not, and
    nothing may gate transport on it.
    """
    out = _output("Network Streamer")
    assert text.is_standby(out) is True
    assert text.volume_bounds(out) is None      # and never gains one


# -- album art palette -----------------------------------------------------
def test_palette_finds_colour_in_a_near_black_sleeve():
    """`Slow Light` by Nocturne Atlas is the cover that forced the second pass.

    Almost every pixel falls below the strict value floor, so the strict pass
    finds nothing and the interface loses a colour that is plainly in the
    artwork. Mostly black with chroma in it is still a coloured sleeve.
    """
    from omarchy_roond import palette

    dark = [(6, 8, 11)] * 240            # near-black field
    chroma = [(40, 90, 120)] * 16        # a small muted-blue detail
    assert palette.dominant_colour(dark) is None
    assert palette.dominant_colour(dark + chroma) is not None


def test_palette_still_refuses_a_greyscale_sleeve():
    """The permissive pass must not start inventing colour where there is none."""
    from omarchy_roond import palette

    assert palette.dominant_colour([(20, 20, 20)] * 200) is None
    assert palette.dominant_colour([(200, 200, 200)] * 200) is None
    assert palette.dominant_colour([(0, 0, 0)] * 128 + [(255, 255, 255)] * 128) is None
