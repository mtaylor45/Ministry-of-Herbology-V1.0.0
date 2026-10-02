"""The earlier reads must survive being rewired to a repository.

J, the maps module and the scheduler build against these shapes. Swapping the fixture mock for a
real
store is only allowed to change where the rows come from, so this asserts the
responses field for field against the frozen contract rather than against a
snapshot of yesterday's mock.
"""

from __future__ import annotations

import pytest

FIXTURE_TOTAL = 12


def _properties(spec, name: str) -> set[str]:
    return set(spec["components"]["schemas"][name]["properties"])


def test_the_register_still_lists_the_fixture_plants(client):
    body = client.get("/api/v1/specimens").json()
    assert body["total"] == FIXTURE_TOTAL
    assert len(body["items"]) == FIXTURE_TOTAL
    assert all(item["display_name"] for item in body["items"])


def test_a_specimen_carries_exactly_the_fields_the_contract_declares(client, spec):
    item = client.get("/api/v1/specimens").json()["items"][0]
    assert set(item) == _properties(spec, "Specimen")
    for required in spec["components"]["schemas"]["Specimen"]["required"]:
        assert item[required] is not None, required


def test_a_location_carries_exactly_the_fields_the_contract_declares(client, spec):
    location = client.get("/api/v1/locations").json()[0]
    assert set(location) == _properties(spec, "Location")
    for required in spec["components"]["schemas"]["Location"]["required"]:
        assert location[required] is not None, required


def test_an_embedded_species_is_a_species_brief(client, spec):
    item = next(
        i for i in client.get("/api/v1/specimens").json()["items"] if i["species"]
    )
    assert set(item["species"]) == _properties(spec, "SpeciesBrief")


def test_a_created_specimen_answers_in_the_same_shape_as_a_listed_one(client, spec):
    created = client.post(
        "/api/v1/specimens", json={"name": "Monstera deliciosa"}
    ).json()
    assert set(created) == _properties(spec, "Specimen")
    fetched = client.get(f"/api/v1/specimens/{created['id']}").json()
    assert fetched == created


def test_one_specimen_still_answers_and_an_unknown_one_still_404s(client):
    first = client.get("/api/v1/specimens").json()["items"][0]
    assert client.get(f"/api/v1/specimens/{first['id']}").json()["id"] == first["id"]
    assert (
        client.get("/api/v1/specimens/01890040-0000-7000-8000-00000000dead").status_code
        == 404
    )


@pytest.mark.parametrize("params", [{"outdoor": True}, {"outdoor": False}])
def test_the_outdoor_filter_still_works(client, params):
    body = client.get("/api/v1/specimens", params=params).json()
    assert body["total"] > 0
    assert all(item["is_outdoor"] is params["outdoor"] for item in body["items"])


def test_the_toxicity_filter_still_answers_for_both_sides(client):
    """A safety feature: it must never silently under-report."""
    toxic = client.get("/api/v1/specimens", params={"toxic_to_pets": True}).json()
    safe = client.get("/api/v1/specimens", params={"toxic_to_pets": False}).json()
    assert toxic["total"] > 0 and safe["total"] > 0
    assert toxic["total"] + safe["total"] == FIXTURE_TOTAL

    for item in toxic["items"]:
        detail = client.get(f"/api/v1/species/{item['species']['id']}").json()
        assert detail["toxic_to_pets"] is True


def test_an_unresolved_plant_is_not_reported_as_safe_by_omission(client):
    """It answers "not toxic" because nothing says it is — and stays in "all"."""
    plant = client.post("/api/v1/specimens", json={"name": "Dittany of Crete"}).json()
    ids = lambda params: {  # noqa: E731
        i["id"]
        for i in client.get(
            "/api/v1/specimens", params={**params, "limit": 200}
        ).json()["items"]
    }
    assert plant["id"] not in ids({"toxic_to_pets": True})
    assert plant["id"] in ids({"toxic_to_pets": False})
    assert plant["id"] in ids({})


def test_the_location_filter_still_works(client):
    location = client.get("/api/v1/locations").json()[0]
    body = client.get(
        "/api/v1/specimens", params={"location_id": location["id"]}
    ).json()
    assert body["total"] == location["specimen_count"]
    assert all(item["location"]["id"] == location["id"] for item in body["items"])


def test_search_matches_the_species_as_well_as_the_nickname(client):
    """The brief: search is by display name and species."""
    by_nickname = client.get("/api/v1/specimens", params={"q": "bertram"}).json()
    assert by_nickname["total"] == 1

    by_species = client.get("/api/v1/specimens", params={"q": "lavandula"}).json()
    assert by_species["total"] > 0
    assert all(
        "lavandula" in item["species"]["accepted_name"].casefold()
        for item in by_species["items"]
    )


def test_the_register_pages_and_hands_back_a_usable_cursor(client):
    first = client.get("/api/v1/specimens", params={"limit": 5}).json()
    assert len(first["items"]) == 5
    assert first["total"] == FIXTURE_TOTAL
    assert first["next_cursor"] == "5"

    second = client.get(
        "/api/v1/specimens", params={"limit": 5, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 5
    assert second["next_cursor"] == "10"

    last = client.get(
        "/api/v1/specimens", params={"limit": 5, "cursor": second["next_cursor"]}
    ).json()
    assert len(last["items"]) == 2
    assert last["next_cursor"] is None

    seen = [i["id"] for page in (first, second, last) for i in page["items"]]
    assert len(set(seen)) == FIXTURE_TOTAL


def test_a_malformed_cursor_says_so_rather_than_quietly_starting_over(client):
    assert client.get("/api/v1/specimens", params={"cursor": "🌿"}).status_code == 422
    assert client.get("/api/v1/specimens", params={"cursor": "-1"}).status_code == 422


def test_members_still_answer(client, spec):
    members = client.get("/api/v1/members").json()
    assert members
    required = set(spec["components"]["schemas"]["Member"]["required"])
    assert required <= set(members[0])


def test_the_photo_and_log_endpoints_answer_their_contract_shapes(client, spec):
    """These answered `[]` from stubs; now every row has the keys the
    contract requires, and a plant with nothing recorded still answers `[]`."""
    first = client.get("/api/v1/specimens").json()["items"][0]
    photos = client.get(f"/api/v1/specimens/{first['id']}/photos").json()
    entries = client.get(f"/api/v1/specimens/{first['id']}/log").json()
    assert photos and entries  # the first fixture plant is seeded with both
    for row in photos:
        assert set(spec["components"]["schemas"]["Photo"]["required"]) <= set(row)
    for row in entries:
        assert set(spec["components"]["schemas"]["LogEntry"]["required"]) <= set(row)

    bare = client.post(
        "/api/v1/specimens", json={"name": "Nothing recorded yet"}
    ).json()
    assert client.get(f"/api/v1/specimens/{bare['id']}/photos").json() == []
    assert client.get(f"/api/v1/specimens/{bare['id']}/log").json() == []
