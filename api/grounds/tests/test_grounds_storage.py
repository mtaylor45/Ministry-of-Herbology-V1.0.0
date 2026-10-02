"""Where the bytes go, and what happens when they cannot.

the design is the whole subject here: the operator supplies the volume, the
repository supplies the name, and nothing in this tree may carry a path that
works as-is.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from grounds.config import GroundsSettings, get_grounds_settings
from grounds.storage import (
    BadImageKey,
    FilesystemImageStore,
    ImageNotFound,
    ImageStoreFull,
    MemoryImageStore,
    key_for,
)
from grounds.tests.conftest import png_bytes

LAYER_ID = "0189aaaa-bbbb-cccc-dddd-eeeeffff0001"


@pytest.fixture
def store(tmp_path: Path) -> FilesystemImageStore:
    return FilesystemImageStore(tmp_path / "layers")


# ----------------------------------------------------- the design, the volume


def test_the_image_directory_has_no_default() -> None:
    """The repository carries the name and the shape, never a working value."""
    assert GroundsSettings(_env_file=None).image_dir is None


def test_the_upload_endpoint_names_the_variable_when_nothing_is_configured(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset, uploads answer 503 rather than writing into a container layer."""
    from grounds import router as grounds_router
    from grounds.fixture_repository import fixture_repository

    # Take the mock's in-memory store away, so the router falls through to the
    # configured volume — which is what a live deployment does.
    monkeypatch.delattr(type(fixture_repository()), "images", raising=False)
    monkeypatch.setattr(fixture_repository(), "images", None, raising=False)
    monkeypatch.setattr(
        grounds_router, "get_grounds_settings", lambda: GroundsSettings(image_dir=None)
    )

    response = client.post(
        "/api/v1/grounds/layers",
        files={"file": ("plan.png", png_bytes(), "image/png")},
        data={"name": "Nowhere to put it", "kind": "survey"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "MOH_GROUNDS_IMAGE_DIR" in detail
    assert "survives a redeploy" in detail


def test_the_limits_are_bounds_rather_than_operator_secrets() -> None:
    """Unlike the directory, these have defaults — and the defaults are sane."""
    settings = GroundsSettings(_env_file=None)
    assert settings.max_upload_bytes >= 1024 * 1024
    assert settings.max_image_pixels >= 1_000_000


def test_the_settings_read_the_documented_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MOH_GROUNDS_IMAGE_DIR", str(tmp_path))
    monkeypatch.setenv("MOH_GROUNDS_MAX_UPLOAD_BYTES", "4096")
    get_grounds_settings.cache_clear()
    try:
        settings = get_grounds_settings()
        assert settings.image_dir == tmp_path
        assert settings.max_upload_bytes == 4096
    finally:
        get_grounds_settings.cache_clear()


# -------------------------------------------------------- the filesystem store


def test_a_stored_image_reads_back_byte_for_byte(store: FilesystemImageStore) -> None:
    data = png_bytes(32, 16)
    key = key_for(LAYER_ID, ".png")
    store.put(key, data)
    assert store.exists(key)
    assert store.get(key) == data


def test_the_directory_is_created_on_first_write(tmp_path: Path) -> None:
    """A fresh volume is an empty mount point, not a prepared tree."""
    root = tmp_path / "not" / "yet" / "there"
    store = FilesystemImageStore(root)
    store.put(key_for(LAYER_ID, ".png"), png_bytes())
    assert root.is_dir()


def test_a_missing_key_is_a_miss_rather_than_a_crash(
    store: FilesystemImageStore,
) -> None:
    with pytest.raises(ImageNotFound):
        store.get(key_for(LAYER_ID, ".png"))


def test_delete_is_idempotent(store: FilesystemImageStore) -> None:
    key = key_for(LAYER_ID, ".png")
    store.delete(key)
    store.put(key, png_bytes())
    store.delete(key)
    store.delete(key)
    assert not store.exists(key)


@pytest.mark.parametrize(
    "key",
    [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "/etc/passwd",
        f"{LAYER_ID}.png/../../x",
        f"{LAYER_ID}.sh",
        f"{LAYER_ID}.png.exe",
        "layer.png",
        "",
    ],
)
def test_a_key_that_did_not_come_from_key_for_never_reaches_the_disk(
    store: FilesystemImageStore, key: str
) -> None:
    with pytest.raises(BadImageKey):
        store.get(key)
    with pytest.raises(BadImageKey):
        store.put(key, b"x")


def test_key_for_refuses_to_mint_a_key_from_something_that_is_not_a_layer_id() -> None:
    for layer_id, extension in (
        ("../etc/passwd", ".png"),
        (LAYER_ID, ".svg"),
        ("not-a-uuid", ".png"),
    ):
        with pytest.raises(BadImageKey):
            key_for(layer_id, extension)


def test_a_full_volume_leaves_no_part_file_behind(
    store: FilesystemImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half-written file is the thing that makes a full disk worse later."""
    store.root.mkdir(parents=True, exist_ok=True)
    real_replace = os.replace

    def refuse(source: Any, target: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(ImageStoreFull):
        store.put(key_for(LAYER_ID, ".png"), png_bytes())

    monkeypatch.setattr(os, "replace", real_replace)
    assert list(store.root.iterdir()) == []


def test_an_unrelated_os_error_is_not_dressed_up_as_a_full_disk(
    store: FilesystemImageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.root.mkdir(parents=True, exist_ok=True)

    def refuse(source: Any, target: Any) -> None:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError) as raised:
        store.put(key_for(LAYER_ID, ".png"), png_bytes())
    assert not isinstance(raised.value, ImageStoreFull)


def test_a_rewrite_replaces_the_object_rather_than_appending(
    store: FilesystemImageStore,
) -> None:
    key = key_for(LAYER_ID, ".png")
    store.put(key, png_bytes(64, 64))
    second = png_bytes(16, 16)
    store.put(key, second)
    assert store.get(key) == second


# ------------------------------------------------------------- the mock store


def test_the_memory_store_answers_the_same_protocol() -> None:
    store = MemoryImageStore()
    key = key_for(LAYER_ID, ".jpg")
    assert not store.exists(key)
    with pytest.raises(ImageNotFound):
        store.get(key)
    store.put(key, b"bytes")
    assert store.get(key) == b"bytes"
    store.delete(key)
    assert not store.exists(key)
    with pytest.raises(BadImageKey):
        store.put("../escape.png", b"x")
