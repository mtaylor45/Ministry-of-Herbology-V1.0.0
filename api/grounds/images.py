"""Deciding what an uploaded file actually is, from its own bytes.

The browser's ``Content-Type`` on a multipart part is whatever the client
chose to write there, so it is a hint and never a decision. Everything below
reads the file's own header instead.

Nothing here decodes an image. Width and height come out of the PNG ``IHDR``
chunk and the JPEG ``SOFn`` marker, which is enough for the map (Leaflet needs
the pixel bounds, not the pixels) and costs no new dependency — and, more to
the point, means a hostile file is never handed to a decoder in the first
place. the design accepts PNG and JPEG directly; see :data:`PDF_MAGIC` for the
PDF half, which this release does not carry.
"""

from __future__ import annotations

from dataclasses import dataclass

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
PDF_MAGIC = b"%PDF-"

#: JPEG start-of-frame markers, which are the ones carrying the dimensions.
#: 0xC4 (DHT), 0xC8 (JPG) and 0xCC (DAC) sit in the same numeric run and are
#: not frames — dropping them is the whole subtlety of this parse.
_SOF_MARKERS = {
    *range(0xC0, 0xC4),
    *range(0xC5, 0xC8),
    *range(0xC9, 0xCC),
    *range(0xCD, 0xD0),
}

#: Markers that stand alone: no length field follows them.
_STANDALONE_MARKERS = {0xD8, 0x01, *range(0xD0, 0xD8)}


class UnsupportedImageError(ValueError):
    """The bytes are not a map image this deployment can store. The router answers 415."""


class ImageTooLargeError(ValueError):
    """Header-declared dimensions exceed the configured bound. The router answers 413."""


@dataclass(frozen=True, slots=True)
class ProbedImage:
    """What the header says, before anything trusts the rest of the file."""

    media_type: str
    extension: str
    width_px: int
    height_px: int

    @property
    def pixels(self) -> int:
        return self.width_px * self.height_px


def probe(data: bytes) -> ProbedImage:
    """Identify and measure an upload, or say plainly why it cannot be stored."""
    if data.startswith(PNG_MAGIC):
        width, height = _png_size(data)
        return ProbedImage("image/png", ".png", width, height)
    if data.startswith(JPEG_MAGIC):
        width, height = _jpeg_size(data)
        return ProbedImage("image/jpeg", ".jpg", width, height)
    if data.startswith(PDF_MAGIC):
        raise UnsupportedImageError(
            "A PDF plat has to be rasterised before it can be a map layer "
            ", and this deployment carries no rasteriser. Export the "
            "page as PNG or JPEG and upload that."
        )
    raise UnsupportedImageError(
        "A map layer must be a PNG or a JPEG image. That file is neither — "
        "its first bytes match no format this deployment stores."
    )


def check_within(probed: ProbedImage, max_pixels: int) -> None:
    """Refuse a decompression bomb by its header, before it reaches a decoder."""
    if probed.pixels > max_pixels:
        raise ImageTooLargeError(
            f"That image is {probed.width_px}×{probed.height_px} pixels "
            f"({probed.pixels:,} in all); this deployment stores up to "
            f"{max_pixels:,}. Scale it down and upload it again."
        )


def _png_size(data: bytes) -> tuple[int, int]:
    # 8 bytes of magic, a 4-byte length, the 4-byte chunk type, then IHDR's
    # width and height as big-endian uint32s. A PNG whose first chunk is not
    # IHDR is malformed by the specification.
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise UnsupportedImageError(
            "That PNG has no image header; it is truncated or corrupt."
        )
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width == 0 or height == 0:
        raise UnsupportedImageError("That PNG declares a zero dimension.")
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int]:
    offset = 2  # past SOI
    size = len(data)
    while offset + 1 < size:
        if data[offset] != 0xFF:
            # Fill bytes are legal between segments; anything else is not.
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in _STANDALONE_MARKERS or marker == 0xFF:
            continue
        if marker == 0xD9 or marker == 0xDA:  # EOI, or start of scan
            break
        if offset + 2 > size:
            break
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2:
            raise UnsupportedImageError("That JPEG has a malformed segment length.")
        if marker in _SOF_MARKERS:
            if offset + 7 > size:
                break
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            if width == 0 or height == 0:
                raise UnsupportedImageError("That JPEG declares a zero dimension.")
            return width, height
        offset += length
    raise UnsupportedImageError(
        "That JPEG carries no frame header, so its size cannot be read; it is "
        "truncated or corrupt."
    )
