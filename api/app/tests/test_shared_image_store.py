"""The one image store, and the two modules that stand on it."""

from __future__ import annotations

import errno
import re
from pathlib import Path

import pytest

from app import images

A_UUID = "0189abcd-0000-7000-8000-000000000001"


def test_both_earlier_stores_are_the_shared_one() -> None:
    """The maps module's and the journal's names resolve to the shared classes, so an `except`
    written
    Or an earlier release still catches what it did."""
    from workers.plates import storage as plates

    from grounds import storage as grounds

    assert grounds.ImageStoreFull is images.ImageStoreFull
    assert grounds.ImageNotFound is images.ImageNotFound
    assert plates.PlateStoreFull is images.ImageStoreFull
    assert plates.PlateNotFound is images.ImageNotFound
    assert plates.BadPlateKey is images.BadImageKey
    assert plates.UnsupportedImageFormat is images.UnsupportedImageFormat
    assert issubclass(grounds.FilesystemImageStore, images.FilesystemImageStore)
    assert issubclass(plates.FilesystemPlateStore, images.FilesystemImageStore)


def test_each_module_keeps_its_own_key_pattern() -> None:
    from workers.plates import storage as plates

    from grounds import storage as grounds

    thumb = f"{A_UUID}.thumb.png"
    assert plates.KEY_PATTERN.match(thumb), "a plate has a thumbnail"
    assert not grounds.KEY_PATTERN.match(thumb), "a map layer does not"
    with pytest.raises(images.BadImageKey):
        grounds.MemoryImageStore().put(thumb, b"\x89PNG")
    plates.MemoryPlateStore().put(thumb, b"\x89PNG")


def test_the_full_volume_message_names_what_the_volume_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    def full(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "replace", full)
    store = images.FilesystemImageStore(tmp_path, what="photographs")
    with pytest.raises(images.ImageStoreFull) as caught:
        store.put(f"{A_UUID}.png", b"\x89PNG\r\n\x1a\n")
    assert "holding photographs" in str(caught.value)
    assert not list(tmp_path.glob(".*.part")), "a failed write takes its scratch file"


def test_round_trip_and_missing(tmp_path: Path) -> None:
    store = images.FilesystemImageStore(tmp_path)
    key = f"{A_UUID}.jpg"
    assert not store.exists(key)
    with pytest.raises(images.ImageNotFound):
        store.get(key)
    store.put(key, b"\xff\xd8\xff\xe0")
    assert store.exists(key)
    assert store.get(key) == b"\xff\xd8\xff\xe0"
    store.delete(key)
    assert not store.exists(key)


def test_keys_are_never_trusted(tmp_path: Path) -> None:
    store = images.FilesystemImageStore(tmp_path)
    for bad in ("../etc/passwd", f"{A_UUID}.gif", "plain.png", ""):
        with pytest.raises(images.BadImageKey):
            store.get(bad)


def test_sniff_reads_the_header_not_the_name() -> None:
    assert images.sniff_extension(b"\x89PNG\r\n\x1a\n...") == ".png"
    assert images.sniff_extension(b"\xff\xd8\xff\xdb...") == ".jpg"
    with pytest.raises(images.UnsupportedImageFormat) as caught:
        images.sniff_extension(b"GIF89a", what="a photograph")
    assert str(caught.value).startswith("A photograph must be a PNG or a JPEG")


def test_a_caller_may_tighten_the_pattern() -> None:
    strict = re.compile(r"^[0-9a-f-]{36}\.png$")
    store = images.MemoryImageStore(key_pattern=strict)
    store.put(f"{A_UUID}.png", b"\x89PNG")
    with pytest.raises(images.BadImageKey):
        store.put(f"{A_UUID}.jpg", b"\xff\xd8\xff")
    assert len(store) == 1
