"""Stand-in plan and survey images for mock mode.

The earlier mock pointed ``image_url`` at ``/static/mock/floor-plan.svg``, which no
build has ever produced — the map had a layer with no picture in it. Rather
than commit two large binaries to a repository that has no business holding
them, mock mode *draws* its two layers: a greyscale grid with a scale bar,
generated once per process.

That matters beyond tidiness. The upload path measures a real PNG header and
the store keeps real bytes, so mock mode exercises the same probe, the same
size bound and the same serving route the live deployment uses. A mock that
skips the format work is a mock that hides format bugs.

The encoder here is deliberately minimal — greyscale, filter 0, one IDAT —
because the alternative is a new image dependency for a picture of a grid.
"""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_greyscale_png(width: int, height: int, rows: list[bytearray]) -> bytes:
    """A valid 8-bit greyscale PNG. `rows` is one bytearray of `width` per line."""
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0: none
        raw.extend(row)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def _grid(width: int, height: int, spacing: int, major_every: int) -> bytes:
    """A pale sheet ruled every `spacing` pixels, darker on every `major_every`."""
    paper, minor, major, edge = 0xEC, 0xCF, 0xA8, 0x6B
    rows: list[bytearray] = []
    for y in range(height):
        on_minor_row = y % spacing == 0
        on_major_row = y % (spacing * major_every) == 0
        row = bytearray([paper]) * width
        if on_major_row:
            row = bytearray([major]) * width
        elif on_minor_row:
            row = bytearray([minor]) * width
        for x in range(0, width, spacing):
            shade = major if x % (spacing * major_every) == 0 else minor
            if shade < row[x]:
                row[x] = shade
        rows.append(row)
    border = bytearray([edge]) * width
    for y in (0, 1, height - 2, height - 1):
        rows[y] = border
    for row in rows:
        row[0] = row[1] = row[-2] = row[-1] = edge
    return encode_greyscale_png(width, height, rows)


@lru_cache
def floor_plan_png() -> bytes:
    """A ruled sheet standing in for a scanned ground-floor plan."""
    return _grid(1600, 1200, 25, 4)


@lru_cache
def survey_png() -> bytes:
    """A ruled sheet standing in for a scanned property plat."""
    return _grid(2000, 1500, 25, 4)
