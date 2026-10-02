"""Where an uploaded plan or survey goes.

The first image store in the tree, written by the maps module. It
stands on the shared one in `api/app/images/`: the behaviour,
the exceptions and every name this module exported are unchanged, so nothing
that imports ``grounds.storage`` has moved. What is particular to map layers
stays here — the key pattern (a layer id and an extension, no thumbnail) and
the word an operator reads in the full-volume message.

Three failures are ordinary and each has an answer the router can give:

* the operator has not named a directory yet — :class:`ImageStoreUnconfigured`
* the disk is full, or a quota is spent — :class:`ImageStoreFull`
* the key names nothing — :class:`ImageNotFound`
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
)
from app.images import FilesystemImageStore as _Filesystem
from app.images import MemoryImageStore as _Memory

__all__ = [
    "KEY_PATTERN",
    "ImageStoreUnconfigured",
    "ImageStoreFull",
    "ImageNotFound",
    "BadImageKey",
    "key_for",
    "LayerImageStore",
    "FilesystemImageStore",
    "MemoryImageStore",
]

#: Keys are minted here from a layer id and a sniffed extension, never from
#: anything a client sent. No thumbnail variant: a layer is served whole.
KEY_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.(png|jpg)$")

#: Everything the grounds router needs from a place to keep images.
LayerImageStore = ImageStore


def key_for(layer_id: str, extension: str) -> str:
    key = f"{layer_id}{extension}"
    if not KEY_PATTERN.match(key):
        raise BadImageKey(f"Refusing to store under {key!r}")
    return key


class FilesystemImageStore(_Filesystem):
    """The real one: a directory on the volume the operator mounted."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, key_pattern=KEY_PATTERN, what="map layers")


class MemoryImageStore(_Memory):
    """Mock mode's store, and what the suite runs against."""

    def __init__(self) -> None:
        super().__init__(key_pattern=KEY_PATTERN)
