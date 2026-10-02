"""The growth log: entries, the photograph an entry may cite, and the order.

The no-invented-plant-facts rule lives here. A log entry may cite one of its own plant's photographs
or
none; another plant's picture is a 422 whether it exists or not, because which
other plant a stray id belongs to is not this specimen's business. And the
Register's own move writes the ``relocate`` entry, once, in the move.
"""

from __future__ import annotations

from typing import Any

import pytest

KEEPER = "01890050-0000-7000-8000-000000000001"


def png_bytes() -> bytes:
    from grounds.mocks.plan_image import encode_greyscale_png

    return encode_greyscale_png(16, 16, [bytearray([0x90]) * 16 for _ in range(16)])


@pytest.fixture
def a_specimen(client: Any) -> str:
    return str(client.get("/api/v1/specimens").json()["items"][0]["id"])


@pytest.fixture
def another_specimen(client: Any, a_specimen: str) -> str:
    rows = client.get("/api/v1/specimens").json()["items"]
    return str(next(r["id"] for r in rows if r["id"] != a_specimen))


def _own_photo(client: Any, specimen_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/specimens/{specimen_id}/photos",
        files={"file": ("snap.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _entry(client: Any, specimen_id: str, **body: Any) -> Any:
    return client.post(f"/api/v1/specimens/{specimen_id}/log", json=body)


# ---------------------------------------------------------------- writing


def test_a_minimal_entry_is_created_with_every_key_present(
    client: Any, a_specimen: str
) -> None:
    response = _entry(client, a_specimen, kind="note")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "note"
    assert body["body"] is None
    assert body["photo"] is None  # present and null, never missing
    assert body["data"] == {}
    assert body["occurred_at"].endswith("Z")
    listed = client.get(f"/api/v1/specimens/{a_specimen}/log").json()
    assert listed[0]["id"] == body["id"]


def test_an_entry_citing_its_own_plants_photo_is_illustrated_both_ways(
    client: Any, a_specimen: str
) -> None:
    photo = _own_photo(client, a_specimen)
    response = _entry(
        client,
        a_specimen,
        kind="growth",
        body="  A new leaf.  ",
        photo_id=photo["id"],
        member_id=KEEPER,
        occurred_at="2026-09-30T12:00:00Z",
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["body"] == "A new leaf."
    assert entry["occurred_at"] == "2026-09-30T12:00:00Z"
    assert entry["photo"]["id"] == photo["id"]
    assert entry["photo"]["log_entry_id"] == entry["id"]
    # And the photo list carries the join read backwards.
    photos = client.get(f"/api/v1/specimens/{a_specimen}/photos").json()
    assert (
        next(p for p in photos if p["id"] == photo["id"])["log_entry_id"] == entry["id"]
    )


def test_another_plants_photograph_is_refused(
    client: Any, a_specimen: str, another_specimen: str
) -> None:
    theirs = _own_photo(client, another_specimen)
    response = _entry(client, a_specimen, kind="growth", photo_id=theirs["id"])
    assert response.status_code == 422
    assert "one of its own plant's photographs" in response.json()["detail"]
    assert client.get(f"/api/v1/specimens/{a_specimen}/log").json()[0]["photo"] is None


def test_a_photograph_nobody_has_is_refused_the_same_way(
    client: Any, a_specimen: str
) -> None:
    response = _entry(
        client, a_specimen, kind="pest", photo_id="00000000-0000-4000-8000-000000000000"
    )
    assert response.status_code == 422
    assert "one of its own plant's photographs" in response.json()["detail"]


def test_a_kind_the_contract_does_not_name_is_a_422(
    client: Any, a_specimen: str
) -> None:
    assert _entry(client, a_specimen, kind="watered").status_code == 422


def test_a_member_nobody_knows_is_a_422(client: Any, a_specimen: str) -> None:
    response = _entry(
        client,
        a_specimen,
        kind="note",
        member_id="00000000-0000-4000-8000-000000000000",
    )
    assert response.status_code == 422


def test_an_entry_for_a_plant_that_does_not_exist_is_a_404(client: Any) -> None:
    response = _entry(client, "00000000-0000-4000-8000-000000000000", kind="note")
    assert response.status_code == 404


def test_a_hand_written_relocate_may_carry_the_two_location_keys(
    client: Any, a_specimen: str, indoor_location: dict[str, Any]
) -> None:
    response = _entry(
        client,
        a_specimen,
        kind="relocate",
        data={"from_location_id": None, "to_location_id": indoor_location["id"]},
    )
    assert response.status_code == 201
    assert response.json()["data"] == {
        "from_location_id": None,
        "to_location_id": indoor_location["id"],
    }


# -------------------------------------------------------- the move's entry


def test_moving_a_plant_on_the_register_writes_one_relocate_entry(
    client: Any, indoor_location: dict[str, Any], outdoor_location: dict[str, Any]
) -> None:
    specimen = next(
        r
        for r in client.get("/api/v1/specimens").json()["items"]
        if r["location"] and r["location"]["id"] == indoor_location["id"]
    )
    before = client.get(f"/api/v1/specimens/{specimen['id']}/log").json()

    moved = client.patch(
        f"/api/v1/specimens/{specimen['id']}",
        json={"location_id": outdoor_location["id"]},
    )
    assert moved.status_code == 200, moved.text
    after = client.get(f"/api/v1/specimens/{specimen['id']}/log").json()
    assert len(after) == len(before) + 1
    assert after[0]["kind"] == "relocate"
    assert after[0]["data"] == {
        "from_location_id": indoor_location["id"],
        "to_location_id": outdoor_location["id"],
    }
    assert after[0]["photo"] is None

    # The same location again is not a move, and a nickname edit is not either.
    client.patch(
        f"/api/v1/specimens/{specimen['id']}",
        json={"location_id": outdoor_location["id"]},
    )
    client.patch(f"/api/v1/specimens/{specimen['id']}", json={"nickname": "Moved"})
    assert len(client.get(f"/api/v1/specimens/{specimen['id']}/log").json()) == len(
        after
    )

    # Lifting it off any location is a move to nowhere, and says so.
    client.patch(f"/api/v1/specimens/{specimen['id']}", json={"location_id": None})
    latest = client.get(f"/api/v1/specimens/{specimen['id']}/log").json()[0]
    assert latest["data"] == {
        "from_location_id": outdoor_location["id"],
        "to_location_id": None,
    }


# ------------------------------------------------------------------ reading


def test_newest_is_the_default_and_oldest_reverses_it(
    client: Any, a_specimen: str
) -> None:
    for when in (
        "2026-05-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        "2026-04-01T00:00:00Z",
    ):
        _entry(client, a_specimen, kind="note", occurred_at=when)
    base = f"/api/v1/specimens/{a_specimen}/log"
    default = client.get(base).json()
    newest = client.get(base, params={"order": "newest"}).json()
    oldest = client.get(base, params={"order": "oldest"}).json()
    stamps = [e["occurred_at"] for e in newest]
    assert default == newest
    assert stamps == sorted(stamps, reverse=True)
    assert [e["id"] for e in oldest] == [e["id"] for e in reversed(newest)]


def test_an_order_the_contract_does_not_name_is_a_422(
    client: Any, a_specimen: str
) -> None:
    assert (
        client.get(
            f"/api/v1/specimens/{a_specimen}/log", params={"order": "up"}
        ).status_code
        == 422
    )


def test_listing_a_plant_that_does_not_exist_is_a_404(client: Any) -> None:
    assert (
        client.get(
            "/api/v1/specimens/00000000-0000-4000-8000-000000000000/log"
        ).status_code
        == 404
    )


def test_the_mock_log_cites_only_its_own_plants_pictures(client: Any) -> None:
    """The seed goes through the same invariants as a write."""
    cited = 0
    for specimen in client.get("/api/v1/specimens").json()["items"]:
        own = {
            p["id"]
            for p in client.get(f"/api/v1/specimens/{specimen['id']}/photos").json()
        }
        for entry in client.get(f"/api/v1/specimens/{specimen['id']}/log").json():
            if entry["photo"] is not None:
                cited += 1
                assert entry["photo"]["id"] in own
                assert entry["body"].startswith("Mock entry")
    assert cited >= 3
