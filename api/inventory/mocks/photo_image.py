"""Stand-in photographs for mock mode and for the suite.

The maps module made this call for map layers and the journal for plates, and the
reasoning carries over: rather than commit photographs to a repository that has
no business holding them, mock mode *draws* its pictures, once per process.
The upload path sniffs a real header, the probe measures real dimensions and
the store keeps real bytes, so mock mode exercises the same format work the
live deployment does.

**What these images are allowed to be.** A photograph is a fact about a plant, so a drawn stand-in
must not pass for one: the figure here is a
flat-grey schematic of a pot with a stem and a few leaves, with no texture, no
background and nothing that could be mistaken for a camera's output. The mock
repository pairs each with a caption that says what it is, and the caption
names no real photograph and no real plant.

The encoder is borrowed read-only from ``grounds.mocks.plan_image`` rather
than copied: the contract suite already imports it the same way, and a third
greyscale PNG writer would be the kind of duplication the design just spent a
releases removing.
"""

from __future__ import annotations

import zlib
from functools import lru_cache

from grounds.mocks.plan_image import encode_greyscale_png

#: Flat greys. See the module docstring.
_PAPER = 0xF2
_FAINT = 0xC4
_LINE = 0x4A
_POT = 0x8C


def _schematic(width: int, height: int, seed: int) -> bytes:
    """A pot, a stem and leaves, varied by `seed` so each picture differs.

    Varying is not decoration: a growth log whose three entries are the same
    picture cannot show that it is a log.
    """
    rows = [bytearray([_PAPER]) * width for _ in range(height)]
    state = (seed * 1103515245 + 12345) & 0x7FFFFFFF

    def nudge(bound: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state % max(1, bound)

    centre = width // 2
    pot_top = height - height // 4
    pot_bottom = height - height // 12
    pot_half = width // 6 + nudge(width // 12)

    # The pot: a trapezoid, filled.
    for y in range(pot_top, pot_bottom):
        t = (y - pot_top) / max(1, pot_bottom - pot_top)
        half = int(pot_half * (1.0 - 0.25 * t))
        for x in range(max(0, centre - half), min(width, centre + half)):
            rows[y][x] = _POT
    # Its rim, a shade darker and a little wider.
    for y in range(max(0, pot_top - 3), pot_top):
        for x in range(
            max(0, centre - pot_half - 4), min(width, centre + pot_half + 4)
        ):
            rows[y][x] = _LINE

    # The stem, rising out of the pot and leaning a little.
    lean = nudge(5) - 2
    top = height // 6 + nudge(height // 10)
    for y in range(top, pot_top):
        x = centre + (lean * (pot_top - y)) // max(1, pot_top - top)
        for thickness in range(-1, 2):
            if 0 <= x + thickness < width:
                rows[y][x + thickness] = _LINE

    # Leaves, alternating sides, each a shaded wedge.
    leaves = 3 + nudge(3)
    for index in range(leaves):
        y0 = top + (index + 1) * (pot_top - top) // (leaves + 1)
        stem_x = centre + (lean * (pot_top - y0)) // max(1, pot_top - top)
        span = width // 5 + nudge(width // 8)
        side = 1 if index % 2 else -1
        depth = height // (9 + nudge(5))
        for step in range(span):
            x = stem_x + side * step
            if not 0 <= x < width:
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

    # A thin frame, so the picture's edge is visible against a light surface.
    for y in (0, height - 1):
        rows[y] = bytearray([_FAINT]) * width
    for row in rows:
        row[0] = row[-1] = _FAINT
    return encode_greyscale_png(width, height, rows)


@lru_cache(maxsize=64)
def photo_png(seed: int = 0, width: int = 640, height: int = 480) -> bytes:
    """A stand-in photograph. Landscape, as a phone held sideways takes one."""
    return _schematic(width, height, seed)


@lru_cache(maxsize=64)
def thumb_png(seed: int = 0) -> bytes:
    """The same figure, small enough for a list row."""
    return _schematic(160, 120, seed)


def seed_for(value: str) -> int:
    """A stable seed from any identifier, so a picture looks the same every run."""
    return zlib.crc32(value.encode("utf-8"))
