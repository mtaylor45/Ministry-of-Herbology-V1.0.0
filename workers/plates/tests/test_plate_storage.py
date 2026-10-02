"""Plates go on a volume the operator named, or nowhere.

names the variable, bounds that do have defaults, and a write that never leaves
half an image behind.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from workers.plates import config as plate_config
from workers.plates.config import PlateSettings
from workers.plates.storage import (
    BadPlateKey,
    FilesystemPlateStore,
    MemoryPlateStore,
    PlateNotFound,
    PlateStoreFull,
    UnsupportedImageFormat,
    key_for,
    sniff_extension,
)


def plate_settings(**overrides: Any) -> PlateSettings:
    """Settings built from nothing but what a test asks for.

    ``_env_file=None`` keeps a developer's stray ``.env`` out of the suite. The
    one ``type: ignore`` pydantic-settings' private keyword needs is written
    here rather than at every call site. (There are no ``__init__.py`` files
    under the test trees — see ``pytest.ini`` — so this cannot be imported from
    ``conftest.py``, and each module that needs it carries its own.)
    """
    return PlateSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


PLATE_ID = "01890060-0000-7000-8000-000000000001"
PNG = b"\x89PNG\r\n\x1a\n" + b"rest of a png"
JPEG = b"\xff\xd8\xff" + b"rest of a jpeg"


@pytest.fixture(autouse=True)
def _forget_cached_settings() -> None:
    plate_config.get_plate_settings.cache_clear()


class TestTheOperatorNamesTheDirectory:
    def test_there_is_no_default_image_directory(self, monkeypatch) -> None:
        """the repository carries the name, never a working value."""
        monkeypatch.delenv("MOH_PLATES_IMAGE_DIR", raising=False)
        settings = plate_settings()
        assert settings.image_dir is None

    def test_an_operator_who_names_one_gets_it(self, tmp_path: Path) -> None:
        settings = plate_settings(image_dir=tmp_path)
        assert settings.image_dir == tmp_path

    def test_the_bounds_carry_defaults_because_they_are_not_secrets(self) -> None:
        settings = plate_settings()
        assert settings.max_image_bytes == plate_config.DEFAULT_MAX_IMAGE_BYTES
        assert settings.max_image_pixels == plate_config.DEFAULT_MAX_IMAGE_PIXELS
        assert settings.max_candidates == plate_config.DEFAULT_MAX_CANDIDATES

    def test_an_operator_may_lower_a_bound(self) -> None:
        settings = plate_settings(max_image_bytes=1024)
        assert settings.max_image_bytes == 1024


class TestGenerationIsOffUntilSomebodyChoosesAProvider:
    def test_a_fresh_deployment_cannot_generate(self) -> None:
        settings = plate_settings()
        assert plate_config.generation_is_configured(settings) is False

    def test_an_endpoint_with_no_key_is_not_configured(self) -> None:
        settings = plate_settings(
            generator_endpoint="https://example.invalid/v1/images"
        )
        assert plate_config.generation_is_configured(settings) is False

    def test_a_key_with_no_endpoint_is_not_configured(self) -> None:
        settings = plate_settings(generator_api_key="k")
        assert plate_config.generation_is_configured(settings) is False

    def test_both_halves_turn_it_on(self) -> None:
        settings = plate_settings(
            generator_endpoint="https://example.invalid/v1/images",
            generator_api_key="k",
        )
        assert plate_config.generation_is_configured(settings) is True

    def test_an_operator_may_switch_it_off_while_keeping_the_credential(self) -> None:
        settings = plate_settings(
            generator_endpoint="https://example.invalid/v1/images",
            generator_api_key="k",
            generation_enabled=False,
        )
        assert plate_config.generation_is_configured(settings) is False

    def test_the_reason_names_the_variables_and_recommends_no_provider(self) -> None:
        settings = plate_settings()
        reason = plate_config.generation_unavailable_reason(settings)
        assert reason is not None
        assert "MOH_PLATES_GENERATOR_ENDPOINT" in reason
        assert "MOH_PLATES_GENERATOR_API_KEY" in reason
        assert "no plate at all" in reason

    def test_a_configured_deployment_has_no_reason_to_give(self) -> None:
        settings = plate_settings(
            generator_endpoint="https://example.invalid/v1/images",
            generator_api_key="k",
        )
        assert plate_config.generation_unavailable_reason(settings) is None

    def test_the_repository_carries_no_generator_value(self) -> None:
        """Rule: Mike will not supply credentials, and none is invented here."""
        source = Path(plate_config.__file__).read_text()
        assert "generator_endpoint: str | None = None" in source
        assert "generator_api_key: str | None = None" in source


class TestKeysAreMintedNeverAccepted:
    def test_a_key_is_the_plate_id_and_a_sniffed_extension(self) -> None:
        assert key_for(PLATE_ID, ".png") == f"{PLATE_ID}.png"

    def test_a_thumbnail_is_a_separate_key_for_the_same_plate(self) -> None:
        assert key_for(PLATE_ID, ".png", thumb=True) == f"{PLATE_ID}.thumb.png"

    def test_a_traversal_never_becomes_a_key(self) -> None:
        with pytest.raises(BadPlateKey):
            key_for("../../etc/passwd", ".png")

    def test_an_extension_nobody_sniffed_is_refused(self) -> None:
        with pytest.raises(BadPlateKey):
            key_for(PLATE_ID, ".svg")

    def test_the_format_is_read_from_the_header_not_a_filename(self) -> None:
        assert sniff_extension(PNG) == ".png"
        assert sniff_extension(JPEG) == ".jpg"

    def test_bytes_that_are_neither_are_discarded(self) -> None:
        with pytest.raises(UnsupportedImageFormat, match="discarded"):
            sniff_extension(b"II*\x00 a tiff from a library scanner")


class TestTheFilesystemStore:
    def test_a_plate_comes_back_as_it_went_in(self, tmp_path: Path) -> None:
        store = FilesystemPlateStore(tmp_path)
        key = key_for(PLATE_ID, ".png")
        store.put(key, PNG)
        assert store.get(key) == PNG
        assert store.exists(key)

    def test_it_creates_the_directory_the_operator_mounted(self, tmp_path) -> None:
        store = FilesystemPlateStore(tmp_path / "plates")
        store.put(key_for(PLATE_ID, ".png"), PNG)
        assert (tmp_path / "plates" / f"{PLATE_ID}.png").is_file()

    def test_a_missing_key_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(PlateNotFound):
            FilesystemPlateStore(tmp_path).get(key_for(PLATE_ID, ".png"))

    def test_delete_is_idempotent(self, tmp_path: Path) -> None:
        store = FilesystemPlateStore(tmp_path)
        store.delete(key_for(PLATE_ID, ".png"))  # never stored; no error

    def test_a_read_refuses_a_key_it_did_not_mint(self, tmp_path: Path) -> None:
        with pytest.raises(BadPlateKey):
            FilesystemPlateStore(tmp_path).get("../../../etc/passwd")

    def test_a_full_volume_discards_rather_than_half_writes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        store = FilesystemPlateStore(tmp_path)

        def _no_space(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(os, "replace", _no_space)
        with pytest.raises(PlateStoreFull, match="discarded rather than"):
            store.put(key_for(PLATE_ID, ".png"), PNG)

    def test_a_failed_write_leaves_no_scratch_file_behind(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A full disk that also leaks part-files is a disk that stays full."""
        store = FilesystemPlateStore(tmp_path)

        def _no_space(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(os, "replace", _no_space)
        with pytest.raises(PlateStoreFull):
            store.put(key_for(PLATE_ID, ".png"), PNG)
        assert list(tmp_path.iterdir()) == []

    def test_a_truncated_image_never_becomes_readable(self, tmp_path: Path) -> None:
        """os.replace means a reader sees all of a plate or none of it."""
        store = FilesystemPlateStore(tmp_path)
        key = key_for(PLATE_ID, ".png")
        store.put(key, PNG)
        assert not any(p.name.startswith(".") for p in tmp_path.iterdir())


class TestTheMemoryStoreMockModeRunsOn:
    def test_it_round_trips(self) -> None:
        store = MemoryPlateStore()
        key = key_for(PLATE_ID, ".jpg")
        store.put(key, JPEG)
        assert store.get(key) == JPEG
        assert len(store) == 1

    def test_it_refuses_a_key_it_did_not_mint_too(self) -> None:
        with pytest.raises(BadPlateKey):
            MemoryPlateStore().put("../escape.png", PNG)

    def test_a_missing_key_raises_the_same_error_as_the_real_one(self) -> None:
        with pytest.raises(PlateNotFound):
            MemoryPlateStore().get(key_for(PLATE_ID, ".png"))
