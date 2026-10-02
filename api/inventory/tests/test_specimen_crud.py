"""the earlier exit criterion, on the wire: add a plant by name and it is in the Register.

Mock mode, which is the mode every other parts of the project runs. The same handlers and
the same serialisers answer in live mode, so what is asserted here about shapes
and invariants holds there too; ``test_database_repository.py`` checks the SQL
underneath it.
"""

from __future__ import annotations

from inventory import enrichment

MONSTERA = "01890030-0000-7000-8000-000000000001"
LAVENDER = "01890030-0000-7000-8000-000000000002"


def register(client, **params) -> dict:
    return client.get("/api/v1/specimens", params=params).json()


# ------------------------------------------------------- the exit criterion


def test_a_plant_added_by_name_appears_in_the_register(client):
    before = register(client)["total"]

    created = client.post("/api/v1/specimens", json={"name": "Monstera deliciosa"})
    assert created.status_code == 201, created.text
    body = created.json()

    after = register(client)
    assert after["total"] == before + 1
    assert body["id"] in {item["id"] for item in after["items"]}


def test_a_typed_name_that_matches_a_species_is_resolved_on_the_spot(client):
    body = client.post("/api/v1/specimens", json={"name": "Monstera deliciosa"}).json()
    assert body["species"]["id"] == MONSTERA
    # No nickname was given, so the display name falls through to the common name.
    assert body["nickname"] is None
    assert body["display_name"] == "Swiss cheese plant"


def test_a_common_name_resolves_too_and_is_case_insensitive(client):
    body = client.post("/api/v1/specimens", json={"name": "english LAVENDER"}).json()
    assert body["species"]["id"] == LAVENDER


def test_an_unmatched_name_still_names_the_plant_in_the_register(client):
    """Never block on the botany worker: the plant is added, resolution is queued."""
    body = client.post("/api/v1/specimens", json={"name": "Dittany of Crete"}).json()
    assert body["species"] is None
    assert body["display_name"] == "Dittany of Crete"

    found = register(client, q="dittany")
    assert found["total"] == 1
    assert found["items"][0]["id"] == body["id"]


def test_a_nickname_given_at_intake_wins_over_the_species_name(client):
    body = client.post(
        "/api/v1/specimens",
        json={"name": "Monstera deliciosa", "nickname": "Gilderoy II"},
    ).json()
    assert body["display_name"] == "Gilderoy II"
    assert body["species"]["id"] == MONSTERA


def test_adding_a_plant_queues_enrichment_without_waiting_for_it(client):
    enrichment.clear_recent()
    body = client.post("/api/v1/specimens", json={"name": "Dittany of Crete"}).json()

    queued = enrichment.recent()
    assert [r.specimen_id for r in queued] == [body["id"]]
    assert queued[0].typed_name == "Dittany of Crete"
    # An unresolved name needs a taxon before it can have sources.
    assert queued[0].job == enrichment.RESOLVE_TAXON


def test_a_resolved_plant_is_queued_for_sources_not_for_resolution(client):
    client.post("/api/v1/specimens", json={"name": "Monstera deliciosa"})
    assert enrichment.recent()[0].job == enrichment.ENRICH_SPECIES


# ------------------------------------------------------ the exposure fields


def test_a_new_plant_takes_its_outdoor_flag_from_its_location(client, outdoor_location):
    body = client.post(
        "/api/v1/specimens",
        json={"name": "Lavandula angustifolia", "location_id": outdoor_location["id"]},
    ).json()
    assert body["is_outdoor"] is True
    assert body["location"]["id"] == outdoor_location["id"]
    assert body["location"]["is_covered"] == outdoor_location["is_covered"]


def test_a_new_plant_with_no_location_is_not_swept_into_the_frost_alerts(client):
    body = client.post("/api/v1/specimens", json={"name": "Dittany of Crete"}).json()
    assert body["location"] is None
    assert body["is_outdoor"] is False


def test_moving_a_plant_re_derives_its_outdoor_flag(
    client, indoor_location, outdoor_location
):
    plant = client.post(
        "/api/v1/specimens",
        json={"name": "Citrus × limon", "location_id": outdoor_location["id"]},
    ).json()
    assert plant["is_outdoor"] is True

    moved = client.patch(
        f"/api/v1/specimens/{plant['id']}",
        json={"location_id": indoor_location["id"]},
    ).json()
    assert moved["is_outdoor"] is False
    assert moved["location"]["id"] == indoor_location["id"]

    back = client.patch(
        f"/api/v1/specimens/{plant['id']}",
        json={"location_id": outdoor_location["id"]},
    ).json()
    assert back["is_outdoor"] is True


def test_clearing_a_plants_location_leaves_it_indoors(client, outdoor_location):
    plant = client.post(
        "/api/v1/specimens",
        json={"name": "Citrus × limon", "location_id": outdoor_location["id"]},
    ).json()
    cleared = client.patch(
        f"/api/v1/specimens/{plant['id']}", json={"location_id": None}
    ).json()
    assert cleared["location"] is None
    assert cleared["is_outdoor"] is False


def test_the_outdoor_flag_never_drifts_from_its_location(
    client, indoor_location, outdoor_location
):
    """The same invariant tests/contract/test_fixtures.py asserts on fixture data.

    It has to hold for rows the API creates and edits, not only for the ones
    The test suite wrote by hand.
    """
    client.post(
        "/api/v1/specimens",
        json={"name": "Rosa gallica", "location_id": outdoor_location["id"]},
    )
    client.post(
        "/api/v1/specimens",
        json={"name": "Ocimum basilicum", "location_id": indoor_location["id"]},
    )
    client.patch(
        f"/api/v1/locations/{outdoor_location['id']}",
        json={**_location_body(outdoor_location), "is_outdoor": False},
    )

    for item in register(client, limit=200)["items"]:
        if item["location"] is None:
            assert item["is_outdoor"] is False, item
        else:
            assert item["is_outdoor"] == item["location"]["is_outdoor"], item


# ------------------------------------------------------------------- groups


def test_a_group_is_one_specimen_with_a_count(client, outdoor_location):
    before = register(client)["total"]
    body = client.post(
        "/api/v1/specimens",
        json={
            "name": "Lavandula angustifolia",
            "location_id": outdoor_location["id"],
            "count": 12,
        },
    ).json()

    assert body["is_group"] is True
    assert body["count"] == 12
    # One hedge, tended once — not twelve rows.
    assert register(client)["total"] == before + 1


def test_a_single_plant_is_not_a_group(client):
    body = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    assert body["is_group"] is False
    assert body["count"] == 1


def test_a_count_below_one_is_refused(client):
    assert (
        client.post(
            "/api/v1/specimens", json={"name": "Rosa gallica", "count": 0}
        ).status_code
        == 422
    )


# --------------------------------------------------------------- validation


def test_a_plant_needs_a_name(client):
    assert client.post("/api/v1/specimens", json={}).status_code == 422
    assert client.post("/api/v1/specimens", json={"name": "   "}).status_code == 422


def test_a_plant_cannot_be_put_in_a_location_that_does_not_exist(client):
    response = client.post(
        "/api/v1/specimens",
        json={
            "name": "Rosa gallica",
            "location_id": "01890010-0000-7000-8000-00000000dead",
        },
    )
    assert response.status_code == 422
    assert "location" in response.json()["detail"].casefold()


def test_a_plant_cannot_name_a_species_that_does_not_exist(client):
    response = client.post(
        "/api/v1/specimens",
        json={
            "name": "Rosa gallica",
            "species_id": "01890030-0000-7000-8000-00000000dead",
        },
    )
    assert response.status_code == 422


# ------------------------------------------------------------------ editing


def test_an_edit_changes_only_the_fields_it_names(client):
    plant = client.post(
        "/api/v1/specimens",
        json={"name": "Monstera deliciosa", "container_litres": 18},
    ).json()

    edited = client.patch(
        f"/api/v1/specimens/{plant['id']}", json={"nickname": "Gilderoy the Second"}
    ).json()
    assert edited["display_name"] == "Gilderoy the Second"
    assert edited["container_litres"] == 18
    assert edited["species"]["id"] == plant["species"]["id"]


def test_an_explicit_null_clears_a_field(client):
    plant = client.post(
        "/api/v1/specimens", json={"name": "Monstera deliciosa", "nickname": "Gilderoy"}
    ).json()
    cleared = client.patch(
        f"/api/v1/specimens/{plant['id']}", json={"nickname": None}
    ).json()
    assert cleared["nickname"] is None
    assert cleared["display_name"] == "Swiss cheese plant"


def test_status_can_be_set_to_any_value_the_contract_allows(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    edited = client.patch(
        f"/api/v1/specimens/{plant['id']}", json={"status": "struggling"}
    ).json()
    assert edited["status"] == "struggling"
    assert (
        client.patch(
            f"/api/v1/specimens/{plant['id']}", json={"status": "flourishing"}
        ).status_code
        == 422
    )


def test_editing_a_plant_that_does_not_exist_is_a_404(client):
    assert (
        client.patch(
            "/api/v1/specimens/01890040-0000-7000-8000-00000000dead",
            json={"nickname": "x"},
        ).status_code
        == 404
    )


def test_an_edit_cannot_move_a_plant_somewhere_that_does_not_exist(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    assert (
        client.patch(
            f"/api/v1/specimens/{plant['id']}",
            json={"location_id": "01890010-0000-7000-8000-00000000dead"},
        ).status_code
        == 422
    )


# ---------------------------------------------------------------- archiving


def test_archiving_takes_a_plant_off_the_register_but_keeps_the_record(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    before = register(client)["total"]

    assert client.delete(f"/api/v1/specimens/{plant['id']}").status_code == 204
    assert register(client)["total"] == before - 1

    kept = client.get(f"/api/v1/specimens/{plant['id']}")
    assert kept.status_code == 200
    assert kept.json()["status"] == "archived"


def test_the_register_can_still_be_asked_for_archived_plants(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    client.delete(f"/api/v1/specimens/{plant['id']}")

    archived = register(client, status="archived")
    assert [item["id"] for item in archived["items"]] == [plant["id"]]


def test_archiving_is_idempotent(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    assert client.delete(f"/api/v1/specimens/{plant['id']}").status_code == 204
    assert client.delete(f"/api/v1/specimens/{plant['id']}").status_code == 204


def test_archiving_something_that_does_not_exist_is_a_404(client):
    assert (
        client.delete(
            "/api/v1/specimens/01890040-0000-7000-8000-00000000dead"
        ).status_code
        == 404
    )


def test_archiving_a_plant_drops_it_from_its_locations_count(client, indoor_location):
    plant = client.post(
        "/api/v1/specimens",
        json={"name": "Ocimum basilicum", "location_id": indoor_location["id"]},
    ).json()
    before = _location(client, indoor_location["id"])["specimen_count"]

    client.delete(f"/api/v1/specimens/{plant['id']}")
    assert _location(client, indoor_location["id"])["specimen_count"] == before - 1


def test_a_plant_can_be_brought_back_from_the_archive(client):
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    client.delete(f"/api/v1/specimens/{plant['id']}")
    restored = client.patch(
        f"/api/v1/specimens/{plant['id']}", json={"status": "thriving"}
    ).json()
    assert restored["status"] == "thriving"
    assert plant["id"] in {item["id"] for item in register(client, limit=200)["items"]}


def test_a_lost_plant_is_not_archived_and_stays_on_the_register(client):
    """'lost' and 'given_away' are part of the record, not a soft delete."""
    plant = client.post("/api/v1/specimens", json={"name": "Rosa gallica"}).json()
    client.patch(f"/api/v1/specimens/{plant['id']}", json={"status": "lost"})
    assert plant["id"] in {item["id"] for item in register(client, limit=200)["items"]}


# ------------------------------------------------------------------ helpers


def _location(client, location_id: str) -> dict:
    return next(
        loc
        for loc in client.get("/api/v1/locations").json()
        if loc["id"] == location_id
    )


def _location_body(location: dict) -> dict:
    return {
        "name": location["name"],
        "kind": location["kind"],
        "is_outdoor": location["is_outdoor"],
        "is_covered": location["is_covered"],
        "sun_exposure": location["sun_exposure"],
    }
