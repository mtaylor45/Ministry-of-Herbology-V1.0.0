"""Uploading a photograph of a plant, serving it back, and every refusal.

An unauthenticated multipart endpoint on a self-hosted box is a way to fill
somebody's disk, so much of this module is the refusals, and each checks the
*status and the sentence*: a bare 415 sends an operator to logs this app keeps
deliberately thin. The rest is the no-invented-plant-facts rule — a photograph belongs to one
plant and is never served under another — and the design three answers for a
volume: unconfigured is 503 naming the variable, full is 507, missing is 404
and never a stand-in.
"""

from __future__ import annotations

import errno
from datetime import UTC, datetime
from typing import Any

import pytest

from inventory import photos
from inventory.config import PhotoSettings
from inventory.fixture_repository import MOCK_CAPTION, fixture_repository
from inventory.repository import get_repository

KEEPER = "01890050-0000-7000-8000-000000000001"


def png_bytes(width: int = 48, height: int = 32, shade: int = 0xB0) -> bytes:
    from grounds.mocks.plan_image import encode_greyscale_png

    return encode_greyscale_png(
        width, height, [bytearray([shade]) * width for _ in range(height)]
    )


def png_header_claiming(width: int, height: int) -> bytes:
    """A PNG whose header declares a size nothing here could decode."""
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    )


def jpeg_bytes(width: int = 40, height: int = 30) -> bytes:
    """SOI then a baseline SOF0 frame header: enough for the probe to measure."""
    return (
        b"\xff\xd8\xff\xc0\x00\x0b\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x01\x01\x11\x00"
    )


@pytest.fixture
def a_specimen(client: Any) -> str:
    return str(client.get("/api/v1/specimens").json()["items"][0]["id"])


@pytest.fixture
def another_specimen(client: Any, a_specimen: str) -> str:
    rows = client.get("/api/v1/specimens").json()["items"]
    return str(next(r["id"] for r in rows if r["id"] != a_specimen))


def _upload(client: Any, specimen_id: str, data: bytes, **form: str) -> Any:
    return client.post(
        f"/api/v1/specimens/{specimen_id}/photos",
        files={"file": ("snap.png", data, "image/png")},
        data=form,
    )


# ------------------------------------------------------------- the happy path


def test_an_uploaded_png_comes_back_as_a_photo_and_serves_its_bytes(
    client: Any, a_specimen: str
) -> None:
    sent = png_bytes(64, 48)
    before = datetime.now(UTC)
    response = _upload(client, a_specimen, sent, caption="  First leaf  ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["caption"] == "First leaf"
    assert body["is_primary"] is False
    assert body["log_entry_id"] is None
    assert response.headers["Location"] == body["url"]
    taken = datetime.fromisoformat(body["taken_at"].replace("Z", "+00:00"))
    assert before.replace(microsecond=0) <= taken <= datetime.now(UTC)

    image = client.get(body["url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == sent

    listed = client.get(f"/api/v1/specimens/{a_specimen}/photos").json()
    assert body["id"] in {row["id"] for row in listed}


def test_an_upload_has_no_thumbnail_and_says_so(client: Any, a_specimen: str) -> None:
    """No decoder is pinned, so no thumbnail is made: `thumb_url` is null (the journal's
    precedent) and `?variant=thumb` serves the original rather than nothing."""
    sent = png_bytes()
    body = _upload(client, a_specimen, sent).json()
    assert body["thumb_url"] is None
    fallback = client.get(body["url"], params={"variant": "thumb"})
    assert fallback.status_code == 200
    assert fallback.content == sent


def test_a_jpeg_is_served_as_a_jpeg_whatever_the_client_claimed(
    client: Any, a_specimen: str
) -> None:
    response = client.post(
        f"/api/v1/specimens/{a_specimen}/photos",
        files={"file": ("snap.png", jpeg_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    image = client.get(response.json()["url"])
    assert image.headers["content-type"] == "image/jpeg"


def test_a_caption_of_only_whitespace_is_null(client: Any, a_specimen: str) -> None:
    body = _upload(client, a_specimen, png_bytes(), caption="   ").json()
    assert body["caption"] is None


def test_taken_at_and_member_id_are_recorded_when_given(
    client: Any, a_specimen: str
) -> None:
    body = _upload(
        client,
        a_specimen,
        png_bytes(),
        taken_at="2026-09-01T08:30:00+02:00",
        member_id=KEEPER,
    ).json()
    assert body["taken_at"] == "2026-09-01T06:30:00Z"


def test_a_member_nobody_knows_is_refused_and_nothing_is_kept(
    client: Any, a_specimen: str
) -> None:
    before = len(client.get(f"/api/v1/specimens/{a_specimen}/photos").json())
    response = _upload(
        client,
        a_specimen,
        png_bytes(),
        member_id="00000000-0000-4000-8000-000000000000",
    )
    assert response.status_code == 422
    assert "member" in response.json()["detail"].lower()
    assert len(client.get(f"/api/v1/specimens/{a_specimen}/photos").json()) == before
    store = fixture_repository().photo_images
    assert isinstance(store, photos.MemoryPhotoStore)
    # Nothing orphaned: each seeded photograph is an original and a thumbnail.
    assert len(store) == 2 * len(fixture_repository()._photos)


# ------------------------------------------------------------ the portrait


def test_is_primary_is_exclusive_and_becomes_the_registers_portrait(
    client: Any, a_specimen: str
) -> None:
    first = _upload(client, a_specimen, png_bytes(), is_primary="true").json()
    assert first["is_primary"] is True
    assert (
        client.get(f"/api/v1/specimens/{a_specimen}").json()["primary_photo_url"]
        == first["url"]
    )

    second = _upload(
        client, a_specimen, png_bytes(shade=0x40), is_primary="true"
    ).json()
    photos_now = client.get(f"/api/v1/specimens/{a_specimen}/photos").json()
    primaries = [p["id"] for p in photos_now if p["is_primary"]]
    assert primaries == [second["id"]]
    assert (
        client.get(f"/api/v1/specimens/{a_specimen}").json()["primary_photo_url"]
        == second["url"]
    )


# -------------------------------------------------------------- the refusals


def test_a_gif_is_refused_with_a_sentence(client: Any, a_specimen: str) -> None:
    response = _upload(client, a_specimen, b"GIF89a" + bytes(64))
    assert response.status_code == 415
    assert "PNG or a JPEG" in response.json()["detail"]


def test_an_empty_upload_is_a_422(client: Any, a_specimen: str) -> None:
    response = _upload(client, a_specimen, b"")
    assert response.status_code == 422


def test_a_photo_for_a_plant_that_does_not_exist_is_a_404(client: Any) -> None:
    response = _upload(client, "00000000-0000-4000-8000-000000000000", png_bytes())
    assert response.status_code == 404


def test_an_upload_over_the_byte_bound_is_abandoned(
    client: Any, a_specimen: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inventory import router

    monkeypatch.setattr(
        router, "get_photo_settings", lambda: PhotoSettings(max_upload_bytes=200)
    )
    response = _upload(client, a_specimen, png_bytes(400, 400))
    assert response.status_code == 413
    assert "200 bytes" in response.json()["detail"]


def test_a_header_declaring_a_decompression_bomb_is_refused_unread(
    client: Any, a_specimen: str
) -> None:
    response = _upload(client, a_specimen, png_header_claiming(100_000, 100_000))
    assert response.status_code == 413
    assert "pixels" in response.json()["detail"]


def test_a_full_volume_is_a_507_and_nothing_is_listed(
    client: Any, a_specimen: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fixture_repository().photo_images

    def full(key: str, data: bytes) -> None:
        raise photos.ImageStoreFull(
            errno.ENOSPC, "The volume holding photographs is full."
        )

    assert store is not None
    monkeypatch.setattr(store, "put", full)
    before = len(client.get(f"/api/v1/specimens/{a_specimen}/photos").json())
    response = _upload(client, a_specimen, png_bytes())
    assert response.status_code == 507
    assert "full" in response.json()["detail"]
    assert len(client.get(f"/api/v1/specimens/{a_specimen}/photos").json()) == before


# ------------------------------------------------------------------- the no-invented-plant-facts
# rule


def test_a_photograph_is_never_served_under_another_plant(
    client: Any, a_specimen: str, another_specimen: str
) -> None:
    body = _upload(client, a_specimen, png_bytes()).json()
    elsewhere = client.get(
        f"/api/v1/specimens/{another_specimen}/photos/{body['id']}/image"
    )
    assert elsewhere.status_code == 404
    listed = client.get(f"/api/v1/specimens/{another_specimen}/photos").json()
    assert body["id"] not in {row["id"] for row in listed}


def test_a_file_missing_from_the_volume_is_a_404_and_not_a_stand_in(
    client: Any, a_specimen: str
) -> None:
    body = _upload(client, a_specimen, png_bytes()).json()
    store = fixture_repository().photo_images
    assert store is not None
    store.delete(body["id"] + ".png")
    response = client.get(body["url"])
    assert response.status_code == 404
    assert "restore the photo volume" in response.json()["detail"]


# ------------------------------------------------------------------- order


def test_newest_is_the_default_and_oldest_reverses_it(
    client: Any, a_specimen: str
) -> None:
    for day in ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", "2026-07-01T00:00:00Z"):
        _upload(client, a_specimen, png_bytes(), taken_at=day)
    base = f"/api/v1/specimens/{a_specimen}/photos"
    default = client.get(base).json()
    newest = client.get(base, params={"order": "newest"}).json()
    oldest = client.get(base, params={"order": "oldest"}).json()
    stamps = [p["taken_at"] for p in newest]
    assert default == newest
    assert stamps == sorted(stamps, reverse=True)
    assert [p["id"] for p in oldest] == [p["id"] for p in reversed(newest)]


def test_an_order_the_contract_does_not_name_is_a_422(
    client: Any, a_specimen: str
) -> None:
    response = client.get(
        f"/api/v1/specimens/{a_specimen}/photos", params={"order": "sideways"}
    )
    assert response.status_code == 422


def test_listing_a_plant_that_does_not_exist_is_a_404(client: Any) -> None:
    response = client.get(
        "/api/v1/specimens/00000000-0000-4000-8000-000000000000/photos"
    )
    assert response.status_code == 404


# ----------------------------------------------------------- the mock seed


def test_mock_photographs_say_what_they_are_and_serve_real_bytes(client: Any) -> None:
    """The no-invented-plant-facts rule for a mock: every seeded picture is captioned as a stand-in,
    names
    nothing real, and is a real PNG with a real thumbnail behind it."""
    seen = 0
    for specimen in client.get("/api/v1/specimens").json()["items"]:
        for photo in client.get(f"/api/v1/specimens/{specimen['id']}/photos").json():
            seen += 1
            assert photo["caption"] == MOCK_CAPTION
            assert "not a photograph" in photo["caption"]
            assert photo["thumb_url"] is not None
            original = client.get(photo["url"])
            thumb = client.get(photo["thumb_url"])
            assert original.headers["content-type"] == "image/png"
            assert thumb.headers["content-type"] == "image/png"
            assert 0 < len(thumb.content) < len(original.content)
    assert seen >= 3


# --------------------------------------------------------------- the design


def test_with_no_volume_configured_the_upload_is_a_503_and_the_list_still_answers(
    client: Any, a_specimen: str
) -> None:
    """Live mode with `MOH_PHOTOS_IMAGE_DIR` unset: the repository's store is
    None. Stood in for here with the fixture store so no database is needed —
    the router's branch is the same one."""
    repo = fixture_repository()
    repo.photo_images = None

    async def _unconfigured() -> Any:
        return repo

    client.app.dependency_overrides[get_repository] = _unconfigured
    try:
        response = _upload(client, a_specimen, png_bytes())
        assert response.status_code == 503
        assert "MOH_PHOTOS_IMAGE_DIR" in response.json()["detail"]
        listed = client.get(f"/api/v1/specimens/{a_specimen}/photos")
        assert listed.status_code == 200
        image = client.get(listed.json()[0]["url"])
        assert image.status_code == 503
    finally:
        client.app.dependency_overrides.pop(get_repository, None)


def test_the_store_comes_from_the_variable_and_has_no_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from inventory.config import get_photo_settings
    from inventory.repository import photo_store_from_settings

    monkeypatch.delenv("MOH_PHOTOS_IMAGE_DIR", raising=False)
    get_photo_settings.cache_clear()
    try:
        assert photo_store_from_settings() is None
        monkeypatch.setenv("MOH_PHOTOS_IMAGE_DIR", str(tmp_path))
        get_photo_settings.cache_clear()
        store = photo_store_from_settings()
        assert isinstance(store, photos.FilesystemPhotoStore)
        assert store.root == tmp_path
    finally:
        get_photo_settings.cache_clear()


def test_the_filesystem_store_keeps_a_photo_and_its_thumbnail_apart(
    tmp_path: Any,
) -> None:
    store = photos.FilesystemPhotoStore(tmp_path)
    key = photos.key_for("0189aaaa-0000-7000-8000-000000000001", ".jpg")
    thumb = photos.thumb_key_for(key)
    assert thumb == "0189aaaa-0000-7000-8000-000000000001.thumb.jpg"
    store.put(key, b"\xff\xd8\xff" + bytes(4))
    assert store.exists(key) and not store.exists(thumb)
    assert store.get(key).startswith(b"\xff\xd8\xff")
    with pytest.raises(photos.BadImageKey):
        photos.key_for("../etc/passwd", ".png")
    with pytest.raises(photos.ImageNotFound):
        store.get(thumb)
