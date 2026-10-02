"""Where a specimen's photographs go, and what a photograph is allowed to be.

The third image store in the tree, and the first that is not a copy: the design
§1 extracted one into ``api/app/images/`` so that this module could be twenty
lines of what is particular to photographs — the key pattern (a photo id, an
optional ``.thumb``, an extension) and the word an operator reads when the
volume is full — and nothing else.

A key is minted here from a photo id and an extension the file's own bytes
earned (:func:`app.images.sniff_extension`), never from a filename or a
``Content-Type`` a client wrote. The thumbnail lives beside the original under
the same id; there is no ``thumb_key`` column on ``photo`` (unlike ``plate``),
so whether a thumbnail exists is a question for the store, not the row.

**What this module does not do is make thumbnails.** Reducing a JPEG needs a
decoder, and this deployment carries none — adding one is a dependency pin,
which is the deployment's file and the maintainers' decision. Mock mode draws
its thumbnails; an upload gets ``thumb_url: null`` until there is something
honest to put there, and ``?variant=thumb`` falls back to the original the
way the journal's plates do.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.images import (
    BadImageKey,
    ImageNotFound,
    ImageStore,
    ImageStoreFull,
    ImageStoreUnconfigured,
    UnsupportedImageFormat,
    sniff_extension,
)
from app.images import FilesystemImageStore as _Filesystem
from app.images import MemoryImageStore as _Memory

__all__ = [
    "KEY_PATTERN",
    "BadImageKey",
    "ImageNotFound",
    "ImageStoreFull",
    "ImageStoreUnconfigured",
    "UnsupportedImageFormat",
    "PhotoImageStore",
    "FilesystemPhotoStore",
    "MemoryPhotoStore",
    "key_for",
    "thumb_key_for",
    "media_type_for",
    "sniff_extension",
]

#: A photo id, an optional ``.thumb``, and one of the two extensions the shared
#: store accepts. Matched on every read and write by the store itself.
KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:\.thumb)?\.(png|jpg)$"
)

_THUMB = ".thumb"

#: Everything the inventory router needs from a place to keep photographs.
PhotoImageStore = ImageStore


def key_for(photo_id: str, extension: str, *, thumb: bool = False) -> str:
    key = f"{photo_id}{_THUMB if thumb else ''}{extension}"
    if not KEY_PATTERN.match(key):
        raise BadImageKey(f"Refusing to store under {key!r}")
    return key


def thumb_key_for(image_key: str) -> str:
    """The thumbnail's key beside an original's: ``<id>.thumb<ext>``."""
    stem, extension = image_key.rsplit(".", 1)
    return key_for(stem, f".{extension}", thumb=True)


def media_type_for(data: bytes) -> str:
    """The media type the bytes themselves declare, never one a client claimed."""
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


class FilesystemPhotoStore(_Filesystem):
    """The real one: a directory on the volume the operator mounted."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, key_pattern=KEY_PATTERN, what="photographs")


class MemoryPhotoStore(_Memory):
    """Mock mode's store, and what the suite runs against."""

    def __init__(self) -> None:
        super().__init__(key_pattern=KEY_PATTERN)
