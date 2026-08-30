"""The endpoint's own format, read back from RAATServer's log.

Roon's extension API exposes no format data at all, which for a client about
playback quality is the wrong hole to shrug at. This machine is the endpoint
though, so RAATServer writes down exactly what the Core hands it -- and these
tests pin the parsing against real log lines.
"""
from __future__ import annotations

import pytest
from _fixtures import ROOT  # noqa: F401

from omarchy_roond.endpoint import OutputFormat, describe, is_hi_res

# Lines copied verbatim from a live RAATServer log.
LOG = """\
08/30 16:57:11 Trace: [RAAT::Output] [lua] GOT [186] {"request":"setup",\
"format":{"sample_type":"pcm","sample_rate":96000,"bits_per_sample":24}}
08/30 16:57:11 Trace: [RAAT::Output] alsa output setup: format is pcm 96000/24/2
08/30 16:57:11 Trace: [RAAT::Output] [ALSA] [plug:pipewire] using hw \
pcmformat S32_LE bitspersample 32
08/30 16:57:11 Trace: [RAAT::Output] [output/alsa] [plug:pipewire] device is ready
"""


def write_log(tmp_path, text):
    p = tmp_path / "RAATServer_log.txt"
    p.write_text(text)
    return OutputFormat(p)


def test_reads_the_stream_and_the_device(tmp_path):
    fmt = write_log(tmp_path, LOG).read()
    assert fmt["sample_rate"] == 96000
    assert fmt["bits"] == 24
    assert fmt["channels"] == 2
    assert fmt["encoding"] == "pcm"
    assert fmt["device"] == {"format": "S32_LE", "bits": 32}
    assert fmt["label"] == "PCM 24/96"


def test_takes_the_most_recent_format(tmp_path):
    """The log is append-only and spans hours; only the tail is current."""
    older = LOG.replace("96000/24/2", "44100/16/2")
    fmt = write_log(tmp_path, older + LOG).read()
    assert fmt["label"] == "PCM 24/96"


def test_no_log_is_not_an_error(tmp_path):
    """A machine that is not an endpoint simply has nothing to report."""
    assert OutputFormat(tmp_path / "missing.txt").read() is None


def test_a_log_without_a_setup_line_reports_nothing(tmp_path):
    assert write_log(tmp_path, "08/30 nothing interesting here\n").read() is None


def test_reparses_only_when_the_log_changes(tmp_path):
    fmt = write_log(tmp_path, LOG)
    first = fmt.read()
    assert fmt.read() is first          # same object: no re-parse
    path = tmp_path / "RAATServer_log.txt"
    path.write_text(LOG.replace("96000/24/2", "192000/24/2"))
    import os, time
    os.utime(path, (time.time() + 1, time.time() + 1))
    assert fmt.read()["label"] == "PCM 24/192"


@pytest.mark.parametrize("rate,bits,label,hires", [
    (44100, 16, "PCM 16/44.1", False),
    (48000, 16, "PCM 16/48", False),
    (48000, 24, "PCM 24/48", True),
    (96000, 24, "PCM 24/96", True),
    (192000, 24, "PCM 24/192", True),
    (352800, 32, "PCM 32/352.8", True),
])
def test_labels_follow_roons_own_wording(rate, bits, label, hires):
    """Roon shows the endpoint node as "96 kHz 24 bit 2ch PCM"; the badge is the
    same facts in the shorthand listeners read."""
    stream = {"sample_type": "pcm", "sample_rate": rate, "bits": bits}
    assert describe(stream) == label
    assert is_hi_res(stream) is hires


@pytest.mark.parametrize("rate,label", [
    (2822400, "DSD64"), (5644800, "DSD128"), (11289600, "DSD256"),
])
def test_dsd_is_named_by_its_multiple_of_the_cd_rate(rate, label):
    assert describe({"sample_type": "dsd", "sample_rate": rate, "bits": 1}) == label


def test_a_subtype_is_appended_when_there_is_one():
    """Ordinary material reports "none"; anything like MQA shows up here."""
    stream = {"sample_type": "pcm", "sample_rate": 96000, "bits": 24,
              "subtype": "mqa"}
    assert describe(stream) == "PCM 24/96 MQA"


def test_there_is_no_file_format_to_show():
    """RAAT decodes on the Core and streams PCM, so FLAC/ALAC/AAC never reach
    the endpoint. The setup request carries only sample type, rate, depth and
    channels -- a codec here would be invented."""
    fmt = {"sample_type": "pcm", "sample_rate": 96000, "bits": 24}
    assert "flac" not in describe(fmt).lower()
    assert "codec" not in fmt


def test_nothing_playing_is_not_hi_res():
    assert is_hi_res(None) is False
