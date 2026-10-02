"""Where a plate's bytes go.

The journal wrote this as the second near-identical image store in the
tree and escalated it rather than importing the maps module's across an ownership boundary
(the module's original docstring is quoted ). A extracted the
shared store to `api/app/images/`; this module now stands
on it and keeps every name it exported, so nothing in ``workers/plates`` has
moved. What is particular to plates stays here: the key pattern (a plate id,
an optional ``.thumb``, an extension) and the word an operator reads in the
full-volume message. ``api/`` is on the worker image's ``PYTHONPATH`` beside
``workers/``, which is also how `grounds.images.probe` resolves.

Three failures are ordinary and each has an answer the router can give:

* the operator has not named a directory yet — :class:`PlateStoreUnconfigured`
* the disk is full, or a quota is spent — :class:`PlateStoreFull`
* the key names nothing — :class:`PlateNotFound`
"""

from __future__ import annotations

import re
from pathlib import Path

from app.images import (
    EXTENSIONS,
    BadImageKey,
    ImageNotFound,
    ImageStore,
    ImageStoreFull,
    ImageStoreUnconfigured,
    UnsupportedImageFormat,
)
from app.images import FilesystemImageStore as _Filesystem
from app.images import MemoryImageStore as _Memory
from app.images import sniff_extension as _sniff_extension

__all__ = [
    "EXTENSIONS",
    "KEY_PATTERN",
    "BadPlateKey",
    "FilesystemPlateStore",
    "MemoryPlateStore",
    "PlateImageStore",
    "PlateNotFound",
    "PlateStoreFull",
    "PlateStoreUnconfigured",
    "UnsupportedImageFormat",
    "key_for",
    "sniff_extension",
]

#: Keys are minted here from a plate id and a sniffed extension, never from
#: anything a remote catalogue sent. The pattern is enforced on every read as
#: well as every write.
KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:\.thumb)?\.(png|jpg)$"
)

# The plate-flavoured names this package has used bound to the
# shared classes so an ``except PlateStoreFull`` catches exactly what it did.
PlateStoreUnconfigured = ImageStoreUnconfigured
PlateStoreFull = ImageStoreFull
PlateNotFound = ImageNotFound
BadPlateKey = BadImageKey

#: Everything the journal needs from a place to keep plates.
PlateImageStore = ImageStore


def sniff_extension(data: bytes) -> str:
    """``.png`` or ``.jpg``, read from the magic bytes and not from a filename.

    A remote catalogue's URL ends in whatever it likes, and a ``Content-Type``
    is a claim. The header is the only part of the answer the far end could not
    get wrong by accident.
    """
    return _sniff_extension(data, what="a plate")


def key_for(plate_id: str, extension: str, *, thumb: bool = False) -> str:
    key = f"{plate_id}{'.thumb' if thumb else ''}{extension}"
    if not KEY_PATTERN.match(key):
        raise BadPlateKey(f"Refusing to store under {key!r}")
    return key


class FilesystemPlateStore(_Filesystem):
    """The real one: a directory on the volume the operator mounted."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, key_pattern=KEY_PATTERN, what="plates")


class MemoryPlateStore(_Memory):
    """Mock mode's store, and what the suite runs against."""

    def __init__(self) -> None:
        super().__init__(key_pattern=KEY_PATTERN)
