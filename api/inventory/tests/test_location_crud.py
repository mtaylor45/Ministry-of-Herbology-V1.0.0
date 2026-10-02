"""Locations and zones — the places the weather engines read exposure from."""

from __future__ import annotations

SITE = "01890000-0000-7000-8000-000000000001"


def locations(client, **params) -> list[dict]:
    return client.get("/api/v1/locations", params=params).json()


def test_a_new_location_appears_in_the_tree(client):
    before = len(locations(client))
    created = client.post(
        "/api/v1/locations",
        json={
            "name": "Potting Shed",
            "kind": "room",
            "is_outdoor": False,
            "is_covered": True,
            "sun_exposure": "low_light",
        },
    )
    # 'low_light' is a species light label, not a sun exposure: the contract's
    # enum is the one that applies here.
    assert created.status_code == 422

    created = client.post(
        "/api/v1/locations",
        json={
            "name": "Potting Shed",
            "kind": "room",
            "is_outdoor": False,
            "is_covered": True,
            "sun_exposure": "part_shade",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["specimen_count"] == 0
    assert body["site_id"] == SITE
    assert len(locations(client)) == before + 1


def test_a_zone_is_a_location_of_kind_zone(client):
    body = client.post(
        "/api/v1/locations",
        json={"name": "Herb Spiral", "kind": "zone", "is_outdoor": True},
    ).json()
    assert body["kind"] == "zone"
    assert body["boundary_px"] is None
    assert body["map_layer_id"] is None
    assert [z["id"] for z in locations(client) if z["kind"] == "zone"].count(
        body["id"]
    ) == 1


def test_an_unstated_sun_exposure_is_unknown_and_not_null(client):
    """The no-invented-plant-facts rule habit: say "we do not know" out loud rather than leaving a
    hole."""
    body = client.post(
        "/api/v1/locations",
        json={"name": "Back Steps", "kind": "area", "is_outdoor": True},
    ).json()
    assert body["sun_exposure"] == "unknown"


def test_covering_is_recorded_rather_than_inferred(client):
    """is_covered is what makes rain stop at a porch roof."""
    porch = client.post(
        "/api/v1/locations",
        json={
            "name": "Side Porch",
            "kind": "zone",
            "is_outdoor": True,
            "is_covered": True,
        },
    ).json()
    assert porch["is_outdoor"] is True
    assert porch["is_covered"] is True

    open_bed = client.post(
        "/api/v1/locations",
        json={"name": "West Bed", "kind": "bed", "is_outdoor": True},
    ).json()
    assert open_bed["is_covered"] is False


def test_a_location_needs_a_name_a_kind_and_an_exposure(client):
    assert client.post("/api/v1/locations", json={}).status_code == 422
    assert (
        client.post(
            "/api/v1/locations",
            json={"name": "Nowhere", "kind": "shed", "is_outdoor": True},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/locations", json={"name": "Nowhere", "kind": "bed"}
        ).status_code
        == 422
    )


def test_a_location_cannot_hang_off_a_parent_that_does_not_exist(client):
    response = client.post(
        "/api/v1/locations",
        json={
            "name": "Orphan Bed",
            "kind": "bed",
            "is_outdoor": True,
            "parent_id": "01890010-0000-7000-8000-00000000dead",
        },
    )
    assert response.status_code == 422


def test_editing_a_location_updates_it_in_place(client, outdoor_location):
    edited = client.patch(
        f"/api/v1/locations/{outdoor_location['id']}",
        json={
            "name": "The South Border",
            "kind": outdoor_location["kind"],
            "is_outdoor": True,
            "is_covered": True,
            "sun_exposure": "part_sun",
        },
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["id"] == outdoor_location["id"]
    assert body["name"] == "The South Border"
    assert body["is_covered"] is True
    assert body["sun_exposure"] == "part_sun"


def test_roofing_a_bed_stops_its_rain_without_moving_its_plants(
    client, outdoor_location
):
    plant = client.post(
        "/api/v1/specimens",
        json={"name": "Rosa gallica", "location_id": outdoor_location["id"]},
    ).json()
    client.patch(
        f"/api/v1/locations/{outdoor_location['id']}",
        json={
            "name": outdoor_location["name"],
            "kind": outdoor_location["kind"],
            "is_outdoor": True,
            "is_covered": True,
        },
    )
    after = client.get(f"/api/v1/specimens/{plant['id']}").json()
    assert after["is_outdoor"] is True
    assert after["location"]["is_covered"] is True


def test_moving_a_location_indoors_carries_every_plant_standing_in_it(
    client, outdoor_location
):
    """The denormalised flag is not allowed to lag behind its location's."""
    first = client.post(
        "/api/v1/specimens",
        json={"name": "Rosa gallica", "location_id": outdoor_location["id"]},
    ).json()
    second = client.post(
        "/api/v1/specimens",
        json={"name": "Citrus × limon", "location_id": outdoor_location["id"]},
    ).json()
    assert first["is_outdoor"] is True and second["is_outdoor"] is True

    client.patch(
        f"/api/v1/locations/{outdoor_location['id']}",
        json={
            "name": outdoor_location["name"],
            "kind": "room",
            "is_outdoor": False,
            "is_covered": True,
        },
    )

    for plant_id in (first["id"], second["id"]):
        moved = client.get(f"/api/v1/specimens/{plant_id}").json()
        assert moved["is_outdoor"] is False, moved
        assert moved["location"]["is_outdoor"] is False

    # And the Register's outdoor filter agrees, which is what the frost guard reads.
    outdoor_ids = {
        item["id"]
        for item in client.get(
            "/api/v1/specimens", params={"outdoor": True, "limit": 200}
        ).json()["items"]
    }
    assert first["id"] not in outdoor_ids and second["id"] not in outdoor_ids


def test_editing_a_location_that_does_not_exist_is_a_404(client):
    assert (
        client.patch(
            "/api/v1/locations/01890010-0000-7000-8000-00000000dead",
            json={"name": "Nowhere", "kind": "bed", "is_outdoor": True},
        ).status_code
        == 404
    )


def test_a_locations_specimen_count_tracks_what_stands_in_it(client, indoor_location):
    before = _count(client, indoor_location["id"])
    client.post(
        "/api/v1/specimens",
        json={"name": "Ocimum basilicum", "location_id": indoor_location["id"]},
    )
    assert _count(client, indoor_location["id"]) == before + 1


def test_locations_can_be_filtered_by_site_and_exposure(client):
    assert locations(client, site_id=SITE)
    assert locations(client, site_id="01890000-0000-7000-8000-00000000dead") == []
    assert all(loc["is_outdoor"] for loc in locations(client, outdoor=True))
    assert not any(loc["is_outdoor"] for loc in locations(client, outdoor=False))


def _count(client, location_id: str) -> int:
    return next(loc for loc in locations(client) if loc["id"] == location_id)[
        "specimen_count"
    ]
