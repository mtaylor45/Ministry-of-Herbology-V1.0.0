"""One place to keep an image on the operator's volume.

The maps module wrote the first of these for map layers (`api/grounds/storage.py`)
and the journal the second for plates (`workers/plates/storage.py`), and
The journal said in the same breath that two was the moment to extract one and that the
extraction belonged somewhere the maintainers owns. This is it, pulled forward
to an earlier release because the inventory API's photo upload would otherwise have been the third
copy. Both earlier modules now stand on this one and keep their own names, so
nothing that imported them has moved.

The shape is the design: there is no object store and no bucket, so an image
lives on a **volume the operator mounts and names**, under a key the schema
stores (`image_key`, `thumb_key`). Three failures are ordinary and each has an
HTTP answer a router can give:

* no directory configured — :class:`ImageStoreUnconfigured`, 503
* the volume is full or out of quota — :class:`ImageStoreFull`, 507
* the key names nothing — :class:`ImageNotFound`, 404

Writes go to a temporary file beside the target and are :func:`os.replace`-d
into place, so a write that dies half way leaves no half-image for a later read
to serve, and a failed write takes its temporary file with it. Keys are matched
against the caller's pattern on every read and write, never trusted: a store
that trusts its caller is one refactor away from serving ``../../etc/passwd``.

A caller gives the store two things: the key pattern its ids produce, and the
word for what it keeps (`"map layers"`, `"plates"`, `"photographs"`), which is
all that differs between the error messages an operator reads.
"""

from __future__ import annotations

import errno
import os
import re
from pathlib import Path
from typing import Protocol

#: A uuid, an optional ``.thumb``, and one of the two extensions this project
#: stores. Callers that do not mint thumbnails may pass a stricter pattern.
DEFAULT_KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:\.thumb)?\.(png|jpg)$"
)

#: What an image may be stored as, judged from its header and never from a
#: filename or a ``Content-Type``, both of which are claims. Anything else is
#: refused rather than transcoded with a dependency the deployment would then
#: have to carry.
EXTENSIONS: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}


class ImageStoreUnconfigured(RuntimeError):
    """No image directory is configured. The router answers 503."""


class ImageStoreFull(OSError):
    """The volume is full or out of quota. The router answers 507."""


class ImageNotFound(LookupError):
    """No stored object under that key. The router answers 404."""


class BadImageKey(ValueError):
    """A key that did not come from the caller's ``key_for``. Never reaches the disk."""


class UnsupportedImageFormat(ValueError):
    """Bytes that are not a PNG or a JPEG, judged from the header."""


def sniff_extension(data: bytes, *, what: str = "an image") -> str:
    """``.png`` or ``.jpg`` from the magic bytes, or :class:`UnsupportedImageFormat`."""
    for magic, extension in EXTENSIONS.items():
        if data.startswith(magic):
            return extension
    raise UnsupportedImageFormat(
        f"{what[0].upper()}{what[1:]} must be a PNG or a JPEG. These bytes are "
        "neither, so they were discarded rather than stored under a name that "
        "implies otherwise."
    )


class ImageStore(Protocol):
    """Everything a router or a worker needs from a place to keep images."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


class FilesystemImageStore:
    """The real one: a directory on the volume the operator mounted."""

    def __init__(
        self,
        root: Path,
        *,
        key_pattern: re.Pattern[str] = DEFAULT_KEY_PATTERN,
        what: str = "images",
    ) -> None:
        self._root = Path(root)
        self._key_pattern = key_pattern
        self._what = what

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        if not self._key_pattern.match(key):
            raise BadImageKey(f"Refusing to touch {key!r}")
        return self._root / key

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        temporary = path.with_name(f".{key}.{os.getpid()}.part")
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
                raise ImageStoreFull(
                    exc.errno,
                    f"The volume holding {self._what} is full, so the image was "
                    "discarded rather than half-written.",
                ) from exc
            raise

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ImageNotFound(key) from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class MemoryImageStore:
    """Mock mode's store, and what the suites run against.

    A dict, which is exactly right for a stack meant to come up with no volume
    attached and forget everything on restart.
    """

    def __init__(self, *, key_pattern: re.Pattern[str] = DEFAULT_KEY_PATTERN) -> None:
        self._objects: dict[str, bytes] = {}
        self._key_pattern = key_pattern

    def put(self, key: str, data: bytes) -> None:
        if not self._key_pattern.match(key):
            raise BadImageKey(f"Refusing to store under {key!r}")
        self._objects[key] = data

    def get(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise ImageNotFound(key) from exc

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._objects

    def __len__(self) -> int:
        return len(self._objects)
