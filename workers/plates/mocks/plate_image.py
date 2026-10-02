"""Stand-in plate images for mock mode and for the suite.

The maps module made this call for map layers and the reasoning carries over
exactly: rather than commit image binaries to a repository that has no business
holding them, mock mode *draws* its plates, once per process.

It matters beyond tidiness. The sourcing path sniffs a real header, measures
real dimensions through `grounds.images.probe`, checks real bounds and stores
real bytes, so mock mode exercises the same format work the live deployment
does. A mock that hands around a three-byte sentinel is a mock that hides
format bugs — and this package found one that way: a truncated PNG raised out
of the pipeline instead of being refused as a candidate.

The encoder is deliberately minimal — greyscale, filter 0, one IDAT — because
the alternative is a new image dependency for a picture of a leaf.

**What these images are allowed to be.** A drawn stand-in must not look like a
scanned plate, because a believable fake is the exact failure this release is
about. So the figure here is a plain schematic in flat greys: no aged paper
wash, no plate number, no copperplate binomial, nothing that would let a
screenshot of mock mode be mistaken for a historical plate. The mock
repository pairs them with an attribution that says what they are.
"""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache

#: Flat greys, no paper texture. See the module docstring.
_PAPER = 0xEE
_FAINT = 0xC8
_LINE = 0x55


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


def _schematic(width: int, height: int, seed: int) -> bytes:
    """A stem with a few leaves, drawn from `seed` so each species differs.

    Varying with the seed is not decoration: a book view whose twelve pages are
    the same picture cannot show that paging works, and a reviewer cannot tell
    a caching bug from a correct render.
    """
    rows = [bytearray([_PAPER]) * width for _ in range(height)]
    centre = width // 2
    state = (seed * 1103515245 + 12345) & 0x7FFFFFFF

    def nudge(bound: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state % bound

    # The stem.
    for y in range(height // 6, height - height // 8):
        for x in range(centre - 1, centre + 2):
            rows[y][x] = _LINE

    # Leaves, alternating sides.
    leaves = 3 + nudge(3)
    for index in range(leaves):
        y0 = height // 5 + index * (height * 3 // (5 * leaves))
        span = width // 4 + nudge(width // 8)
        side = 1 if index % 2 else -1
        depth = height // (8 + nudge(4))
        for step in range(span):
            x = centre + side * step
            if not 1 <= x < width - 1:
                break
            lift = int(depth * (step / max(1, span)) ** 0.6)
            for thickness in range(-1, 2):
                y = y0 - lift + thickness
                if 0 <= y < height:
                    rows[y][x] = _LINE
            for fill in range(1, max(1, lift)):
                y = y0 - fill
                if 0 <= y < height and rows[y][x] == _PAPER:
                    rows[y][x] = _FAINT

    # A thin frame, so a page's edge is visible against the book's surface.
    for y in (0, height - 1):
        rows[y] = bytearray([_FAINT]) * width
    for row in rows:
        row[0] = row[-1] = _FAINT
    return encode_greyscale_png(width, height, rows)


@lru_cache(maxsize=64)
def plate_png(seed: int = 0, width: int = 600, height: int = 800) -> bytes:
    """A stand-in plate. Portrait, as a plate is."""
    return _schematic(width, height, seed)


@lru_cache(maxsize=64)
def thumb_png(seed: int = 0) -> bytes:
    """The same figure, small enough for a list row."""
    return _schematic(150, 200, seed)


def seed_for(value: str) -> int:
    """A stable seed from any identifier, so a plate looks the same every run."""
    return zlib.crc32(value.encode("utf-8"))
