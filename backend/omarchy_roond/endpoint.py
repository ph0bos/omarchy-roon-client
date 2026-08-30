"""What is actually coming out of this machine, in numbers.

Roon's *extension* API exposes no format information at all -- no sample rate,
no bit depth, no codec, no signal path. That is a real hole, and for a client
whose whole subject is playback quality it is the wrong hole to shrug at.

But this machine is not only a controller: it is the endpoint. RAATServer runs
here, and it writes down exactly what the Core hands it:

    {"request":"setup","format":{"sample_type":"pcm","sample_rate":96000,
                                 "bits_per_sample":24,...}}
    alsa output setup: format is pcm 96000/24/2
    [ALSA] [plug:pipewire] using hw pcmformat S32_LE bitspersample 32

So the source format comes from RAATServer's own log, and the device format from
the line under it. Together they are a two-stop signal path: what Roon sent, and
what the sound card was opened as.

This only ever describes the LOCAL endpoint. A zone in another room is played by
somebody else's hardware and this machine cannot know anything about it -- which
is why the badge disappears when the pinned zone is not this one, rather than
showing a number that belongs to a different room.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# "alsa output setup: format is pcm 96000/24/2"
SETUP = re.compile(r"alsa output setup: format is (\w+) (\d+)/(\d+)/(\d+)")
# The setup request carries a subtype alongside the sample type; "none" for
# ordinary material, and the place anything like MQA would show up.
SUBTYPE = re.compile(r'"sample_subtype"\s*:\s*"([^"]+)"')
# "[ALSA] [plug:pipewire] using hw pcmformat S32_LE bitspersample 32"
DEVICE = re.compile(r"using hw pcmformat (\S+) bitspersample (\d+)")

TAIL_BYTES = 256 * 1024


def log_path() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(data) / "omarchy-roon" / "roon" / "RAATServer" / "Logs"
            / "RAATServer_log.txt")


class OutputFormat:
    """The endpoint's current format, re-read only when the log has changed."""

    def __init__(self, path: Path | None = None):
        self.path = path or log_path()
        self._mtime = 0.0
        self._cached: dict | None = None

    def read(self) -> dict | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None                      # not an endpoint, or never started
        if mtime == self._mtime:
            return self._cached
        self._mtime = mtime
        self._cached = self._parse()
        return self._cached

    def _parse(self) -> dict | None:
        try:
            size = self.path.stat().st_size
            with self.path.open("rb") as fh:
                # The log grows all day; only the tail can be current, and
                # reading megabytes on every poll would be absurd.
                fh.seek(max(0, size - TAIL_BYTES))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            return None

        stream = device = None
        subtype = None
        for line in reversed(tail.splitlines()):
            if stream is None:
                m = SETUP.search(line)
                if m:
                    stream = {
                        "encoding": m.group(1),
                        "sample_rate": int(m.group(2)),
                        "bits": int(m.group(3)),
                        "channels": int(m.group(4)),
                    }
            if device is None:
                m = DEVICE.search(line)
                if m:
                    device = {"format": m.group(1), "bits": int(m.group(2))}
            if subtype is None:
                m = SUBTYPE.search(line)
                if m:
                    subtype = m.group(1)
            if stream and device and subtype is not None:
                break

        if not stream:
            return None
        if subtype and subtype != "none":
            stream["subtype"] = subtype
        return {
            **stream,
            "device": device,
            "label": describe(stream),
        }


def describe(stream: dict) -> str:
    """The endpoint stage of the signal path, worded the way Roon words it.

    Roon shows this node as "96 kHz 24 bit 2ch PCM", so the badge is
    `PCM 24/96` -- the sample type, then the shorthand every listener reads at a
    glance.

    There is no file format here, and there cannot be: **RAAT decodes on the
    Core and streams PCM to the endpoint.** FLAC, ALAC, AAC and the rest are
    resolved long before this machine sees anything, and the setup request
    carries only sample type, rate, depth and channels. Showing a codec would
    mean inventing one.
    """
    kind = str(stream.get("sample_type") or stream.get("encoding") or "pcm").lower()

    if kind == "dsd":
        # Roon names DSD by its multiple of the CD rate: DSD64, DSD128, DSD256.
        multiple = round(stream["sample_rate"] / 44100)
        return f"DSD{multiple}"

    khz = stream["sample_rate"] / 1000
    khz_text = f"{khz:.1f}".rstrip("0").rstrip(".")
    label = f"{kind.upper()} {stream['bits']}/{khz_text}"
    subtype = stream.get("subtype")
    return f"{label} {subtype.upper()}" if subtype and subtype != "none" else label


def is_hi_res(stream: dict | None) -> bool:
    """Above CD. The threshold everyone means when they say hi-res."""
    if not stream:
        return False
    return stream.get("sample_rate", 0) > 48000 or stream.get("bits", 0) > 16
