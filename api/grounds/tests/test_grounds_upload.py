"""Uploading a plan or a survey, and refusing everything that is not one.

An unauthenticated multipart endpoint on a self-hosted box is a way to fill
somebody's disk, so most of this module is about the refusals rather than the
happy path. Each one checks the *status and the reason*, because "415" with no
explanation sends an operator to the logs and this app's logs are deliberately
thin.
"""

from __future__ import annotations

import errno
from typing import Any

import pytest

from grounds import images, storage
from grounds.config import GroundsSettings
from grounds.tests.conftest import png_bytes


def _upload(client: Any, data: bytes, **form: str) -> Any:
    fields = {"name": "North plat", "kind": "survey", **form}
    return client.post(
        "/api/v1/grounds/layers",
        files={"file": ("plan.png", data, "image/png")},
        data=fields,
    )


def test_an_uploaded_layer_comes_back_measured_and_uncalibrated(client: Any) -> None:
    response = _upload(client, png_bytes(320, 240), name="Back garden", kind="survey")
    assert response.status_code == 201, response.text
    layer = response.json()
    assert layer["name"] == "Back garden"
    assert layer["kind"] == "survey"
    assert (layer["image_width_px"], layer["image_height_px"]) == (320, 240)
    # The state the design said the contract cannot express: an empty
    # Calibration object, not a null.
    assert layer["calibration"] == {"scale_mm_per_px": None, "points": []}
    assert layer["scale_mm_per_px"] is None


def test_an_uploaded_layer_joins_the_list_and_serves_its_bytes(client: Any) -> None:
    sent = png_bytes(96, 64)
    layer = _upload(client, sent).json()

    listed = client.get("/api/v1/grounds/layers").json()
    assert layer["id"] in {row["id"] for row in listed}

    image = client.get(layer["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == sent


def test_a_layer_is_attached_to_the_site_when_none_is_named(client: Any) -> None:
    """`site_id` is optional on the form; a household has one site."""
    layer = _upload(client, png_bytes()).json()
    existing = client.get("/api/v1/grounds/layers").json()
    assert layer["site_id"] == existing[0]["site_id"]


def test_each_upload_stacks_above_the_last(client: Any) -> None:
    before = client.get("/api/v1/grounds/layers").json()
    first = _upload(client, png_bytes(), name="One").json()
    second = _upload(client, png_bytes(), name="Two").json()
    assert first["ordinal"] > max(row["ordinal"] for row in before)
    assert second["ordinal"] > first["ordinal"]


# ------------------------------------------------------------- the refusals


def test_a_text_file_renamed_to_png_is_refused(client: Any) -> None:
    """The client's Content-Type is a hint. The magic bytes decide."""
    response = _upload(client, b"this is not a picture at all")
    assert response.status_code == 415
    assert "PNG or a JPEG" in response.json()["detail"]


def test_a_pdf_plat_is_refused_with_the_reason_adr_0015_gives(client: Any) -> None:
    response = _upload(client, b"%PDF-1.7\n1 0 obj\n")
    assert response.status_code == 415
    detail = response.json()["detail"]
    assert "rasteris" in detail
    assert "PNG or JPEG" in detail


def test_an_empty_upload_is_refused(client: Any) -> None:
    response = _upload(client, b"")
    assert response.status_code == 422


def test_a_layer_needs_a_name(client: Any) -> None:
    response = _upload(client, png_bytes(), name="   ")
    assert response.status_code == 422
    assert "name" in response.json()["detail"]


def test_an_unknown_kind_is_refused(client: Any) -> None:
    response = _upload(client, png_bytes(), kind="satellite")
    assert response.status_code == 422
    assert "floor_plan" in response.json()["detail"]


def test_a_body_past_the_bound_is_refused_without_being_kept(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grounds import router as grounds_router

    monkeypatch.setattr(
        grounds_router,
        "get_grounds_settings",
        lambda: GroundsSettings(max_upload_bytes=1024),
    )
    response = _upload(client, png_bytes(600, 600))
    assert response.status_code == 413
    assert "1,024 bytes" in response.json()["detail"]


def test_a_decompression_bomb_is_refused_from_its_header(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound is on declared dimensions, checked before anything decodes."""
    from grounds import router as grounds_router

    monkeypatch.setattr(
        grounds_router,
        "get_grounds_settings",
        lambda: GroundsSettings(max_image_pixels=100),
    )
    response = _upload(client, png_bytes(64, 64))
    assert response.status_code == 413
    assert "64×64" in response.json()["detail"]


def test_a_full_volume_answers_507_and_stores_no_row(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grounds.fixture_repository import fixture_repository

    before = client.get("/api/v1/grounds/layers").json()

    def refuse(key: str, data: bytes) -> None:
        raise storage.ImageStoreFull(
            errno.ENOSPC, "The volume holding map layers is full"
        )

    monkeypatch.setattr(fixture_repository().images, "put", refuse)
    response = _upload(client, png_bytes())
    assert response.status_code == 507
    assert "full" in response.json()["detail"]
    assert client.get("/api/v1/grounds/layers").json() == before


def test_a_failed_row_write_takes_its_orphan_image_with_it(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-created layer must not leave bytes on the operator's volume."""
    from grounds.fixture_repository import fixture_repository

    repo = fixture_repository()
    stored: list[str] = []
    real_put = repo.images.put

    def remember(key: str, data: bytes) -> None:
        stored.append(key)
        real_put(key, data)

    async def explode(data: dict) -> dict:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(repo.images, "put", remember)
    monkeypatch.setattr(repo, "create_layer", explode)

    with pytest.raises(RuntimeError):
        _upload(client, png_bytes())

    assert stored, "the test never reached the store"
    assert not any(repo.images.exists(key) for key in stored)


# ------------------------------------------------------------ probing itself


@pytest.mark.parametrize(
    ("width", "height"), [(1, 1), (64, 48), (1600, 1200), (2000, 1500)]
)
def test_a_generated_png_measures_the_size_it_was_generated_at(
    width: int, height: int
) -> None:
    probed = images.probe(png_bytes(width, height))
    assert (probed.width_px, probed.height_px) == (width, height)
    assert probed.media_type == "image/png"
    assert probed.extension == ".png"


def test_a_truncated_png_header_is_refused_rather_than_guessed() -> None:
    with pytest.raises(images.UnsupportedImageError):
        images.probe(images.PNG_MAGIC + b"\x00\x00")


def test_a_jpeg_is_measured_from_its_frame_marker() -> None:
    """A minimal JPEG: SOI, an APP0 to skip over, then a baseline SOF0."""
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0"
        + (16).to_bytes(2, "big")
        + b"JFIF\x00"
        + b"\x00" * 9
        + b"\xff\xc0"
        + (11).to_bytes(2, "big")
        + b"\x08"
        + (480).to_bytes(2, "big")
        + (640).to_bytes(2, "big")
        + b"\x01\x01\x11\x00"
    )
    probed = images.probe(jpeg)
    assert (probed.width_px, probed.height_px) == (640, 480)
    assert probed.extension == ".jpg"


def test_a_huffman_table_is_not_mistaken_for_a_frame() -> None:
    """0xC4 sits inside the SOFn numeric run and is a table, not a frame.

    Getting this wrong reads two bytes of Huffman codes as a picture's size,
    which is the classic way a hand-rolled JPEG parse goes wrong.
    """
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xc4"
        + (6).to_bytes(2, "big")
        + b"\x00\x01\x02\x03"
        + b"\xff\xc0"
        + (11).to_bytes(2, "big")
        + b"\x08"
        + (100).to_bytes(2, "big")
        + (200).to_bytes(2, "big")
        + b"\x01\x01\x11\x00"
    )
    probed = images.probe(jpeg)
    assert (probed.width_px, probed.height_px) == (200, 100)


def test_a_jpeg_that_ends_before_its_frame_is_refused() -> None:
    with pytest.raises(images.UnsupportedImageError, match="no frame header"):
        images.probe(
            b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
        )
