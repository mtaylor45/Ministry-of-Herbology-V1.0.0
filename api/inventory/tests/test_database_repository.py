"""The live path, against a real Postgres.

Skipped unless ``MOH_TEST_DATABASE_URL`` names a database these tests may
create tables in, because CI has no Postgres attached yet::

    MOH_TEST_DATABASE_URL=postgresql+asyncpg://herbology@127.0.0.1:5432/herbology_test \
        .venv/bin/python -m pytest api/inventory -q

The tables are cut out of ``contracts/schema/001_init.sql`` rather than retyped,
so a column that moves in the frozen schema breaks these tests instead of
quietly passing them. The Timescale hypertables are left out: none of the
inventory tables is one.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get("MOH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set MOH_TEST_DATABASE_URL to run the live-database tests",
)

#: Dependency order. ``species`` is the botany worker's and read-only here; it is
#: created because a specimen points at it.
TABLES = [
    "site",
    "member",
    "map_layer",
    "location",
    "species",
    "specimen",
    "photo",
    "log_entry",
]

SITE = uuid.UUID("01890000-0000-7000-8000-000000000001")
INDOORS = uuid.UUID("01890010-0000-7000-8000-000000000002")
OUTDOORS = uuid.UUID("01890010-0000-7000-8000-000000000004")
PORCH = uuid.UUID("01890010-0000-7000-8000-000000000006")
MONSTERA = uuid.UUID("01890030-0000-7000-8000-000000000001")
LAVENDER = uuid.UUID("01890030-0000-7000-8000-000000000002")
KEEPER = uuid.UUID("01890050-0000-7000-8000-000000000001")


def _create_table_sql(repo_root, table: str) -> str:
    sql = (repo_root / "contracts" / "schema" / "001_init.sql").read_text()
    start = sql.index(f"CREATE TABLE {table} (")
    end = sql.index("\n);", start) + len("\n);")
    return sql[start:end]


@pytest_asyncio.fixture
async def engine(repo_root):
    from sqlalchemy.ext.asyncio import create_async_engine

    # NullPool: each test gets its own event loop, and an asyncpg connection
    # belongs to the loop that opened it.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "citext"'))
        await conn.execute(
            text(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))} CASCADE")
        )
        for table in TABLES:
            await conn.execute(text(_create_table_sql(repo_root, table)))
        await _seed(conn)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))} CASCADE")
            )
        await engine.dispose()


async def _seed(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO site (id, name, latitude, longitude, timezone)"
            " VALUES (:id, 'Test Grounds', 39.7, -86.1, 'America/Indiana/Indianapolis')"
        ),
        {"id": SITE},
    )
    places = [
        (INDOORS, "Study", "room", False, True, "part_shade"),
        (OUTDOORS, "South Border", "bed", True, False, "full_sun"),
        (PORCH, "Covered Porch", "zone", True, True, "part_shade"),
    ]
    for id_, name, kind, outdoor, covered, sun in places:
        await conn.execute(
            text(
                "INSERT INTO location (id, site_id, name, kind, is_outdoor,"
                " is_covered, sun_exposure) VALUES (:id, :site, :name, :kind,"
                " :outdoor, :covered, :sun)"
            ),
            {
                "id": id_,
                "site": SITE,
                "name": name,
                "kind": kind,
                "outdoor": outdoor,
                "covered": covered,
                "sun": sun,
            },
        )
    taxa = [
        (
            MONSTERA,
            "Monstera deliciosa",
            "Araceae",
            ["Swiss cheese plant", "ceriman"],
            True,
        ),
        (LAVENDER, "Lavandula angustifolia", "Lamiaceae", ["English lavender"], False),
    ]
    for id_, accepted, family, common, toxic in taxa:
        await conn.execute(
            text(
                "INSERT INTO species (id, accepted_name, family, common_names,"
                " toxic_to_pets) VALUES (:id, :accepted, :family, :common, :toxic)"
            ),
            {
                "id": id_,
                "accepted": accepted,
                "family": family,
                "common": common,
                "toxic": toxic,
            },
        )
    await conn.execute(
        text("INSERT INTO member (id, name, role) VALUES (:id, 'Keeper', 'keeper')"),
        {"id": KEEPER},
    )


@pytest_asyncio.fixture
async def repo(engine):
    from inventory.database_repository import DatabaseRepository
    from inventory.photos import MemoryPhotoStore

    return DatabaseRepository(engine, photo_images=MemoryPhotoStore())


@pytest.fixture
def live_client(engine):
    """The real router, with the live repository behind it instead of fixtures."""
    from fastapi.testclient import TestClient

    from app.main import app
    from inventory.database_repository import DatabaseRepository
    from inventory.repository import get_repository

    async def _live():
        return DatabaseRepository(engine)

    app.dependency_overrides[get_repository] = _live
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_repository, None)


# --------------------------------------------------------------- the basics


@pytest.mark.asyncio
async def test_a_created_plant_is_read_back_with_its_location_and_species(repo):
    from inventory.repository import SpecimenQuery

    row = await repo.create_specimen(
        {
            "name": "Monstera deliciosa",
            "species_id": MONSTERA,
            "location_id": INDOORS,
            "count": 1,
            "in_container": True,
            "container_litres": 18.0,
            "acquired_on": date(2026, 3, 14),
        }
    )
    assert row["is_outdoor"] is False
    assert row["location"]["name"] == "Study"
    assert row["species"]["accepted_name"] == "Monstera deliciosa"
    assert row["status"] == "thriving"
    assert row["created_at"] is not None

    page = await repo.list_specimens(SpecimenQuery())
    assert page.total == 1
    assert page.items[0]["id"] == row["id"]


@pytest.mark.asyncio
async def test_the_outdoor_flag_is_taken_from_the_location_not_the_request(repo):
    outdoors = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    indoors = await repo.create_specimen(
        {"name": "Monstera", "species_id": MONSTERA, "location_id": INDOORS}
    )
    unplaced = await repo.create_specimen({"name": "Dittany"})

    assert outdoors["is_outdoor"] is True
    assert indoors["is_outdoor"] is False
    assert unplaced["is_outdoor"] is False
    assert unplaced["location"] is None
    assert unplaced["species"] is None


@pytest.mark.asyncio
async def test_a_group_is_one_row_with_a_count(repo):
    from inventory.repository import SpecimenQuery

    row = await repo.create_specimen(
        {
            "name": "Lavandula",
            "species_id": LAVENDER,
            "location_id": OUTDOORS,
            "count": 12,
        }
    )
    assert row["is_group"] is True
    assert row["count"] == 12
    assert (await repo.list_specimens(SpecimenQuery())).total == 1


@pytest.mark.asyncio
async def test_a_plant_cannot_be_created_somewhere_that_does_not_exist(repo):
    from inventory.repository import UnknownLocationError, UnknownSpeciesError

    with pytest.raises(UnknownLocationError):
        await repo.create_specimen({"name": "Nowhere", "location_id": uuid.uuid4()})
    with pytest.raises(UnknownSpeciesError):
        await repo.create_specimen({"name": "Nothing", "species_id": uuid.uuid4()})


# ------------------------------------------------------------------ editing


@pytest.mark.asyncio
async def test_moving_a_plant_re_derives_its_outdoor_flag(repo):
    row = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    moved = await repo.update_specimen(row["id"], {"location_id": INDOORS})
    assert moved["is_outdoor"] is False
    assert moved["location"]["id"] == INDOORS

    cleared = await repo.update_specimen(row["id"], {"location_id": None})
    assert cleared["is_outdoor"] is False
    assert cleared["location"] is None


@pytest.mark.asyncio
async def test_an_edit_touches_only_the_fields_it_names(repo):
    row = await repo.create_specimen(
        {
            "name": "Monstera",
            "species_id": MONSTERA,
            "location_id": INDOORS,
            "container_litres": 18.0,
        }
    )
    edited = await repo.update_specimen(
        row["id"], {"nickname": "Gilderoy", "soil_note": "peat-free"}
    )
    assert edited["nickname"] == "Gilderoy"
    assert edited["soil_note"] == "peat-free"
    assert edited["container_litres"] == 18.0
    assert edited["location"]["id"] == INDOORS


@pytest.mark.asyncio
async def test_editing_a_plant_that_does_not_exist_answers_nothing(repo):
    assert await repo.update_specimen(str(uuid.uuid4()), {"nickname": "x"}) is None


@pytest.mark.asyncio
async def test_roofing_a_location_does_not_move_its_plants_indoors(repo):
    row = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    await repo.update_location(
        str(OUTDOORS),
        {"name": "South Border", "kind": "bed", "is_outdoor": True, "is_covered": True},
    )
    after = await repo.get_specimen(row["id"])
    assert after["is_outdoor"] is True
    assert after["location"]["is_covered"] is True


@pytest.mark.asyncio
async def test_moving_a_location_indoors_carries_its_plants_with_it(repo):
    from inventory.repository import SpecimenQuery

    first = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    second = await repo.create_specimen(
        {"name": "Monstera", "species_id": MONSTERA, "location_id": OUTDOORS}
    )
    elsewhere = await repo.create_specimen(
        {"name": "Porch lavender", "species_id": LAVENDER, "location_id": PORCH}
    )

    await repo.update_location(
        str(OUTDOORS),
        {
            "name": "Winter Room",
            "kind": "room",
            "is_outdoor": False,
            "is_covered": True,
        },
    )

    for specimen_id in (first["id"], second["id"]):
        row = await repo.get_specimen(specimen_id)
        assert row["is_outdoor"] is False, row
        assert row["location"]["is_outdoor"] is False
    # An unrelated location is untouched.
    assert (await repo.get_specimen(elsewhere["id"]))["is_outdoor"] is True

    outdoors = await repo.list_specimens(SpecimenQuery(outdoor=True))
    assert [r["id"] for r in outdoors.items] == [elsewhere["id"]]


# ---------------------------------------------------------------- archiving


@pytest.mark.asyncio
async def test_archiving_keeps_the_row_and_drops_it_from_the_register(repo):
    from inventory.repository import SpecimenQuery

    row = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    assert await repo.archive_specimen(row["id"]) is True

    assert (await repo.list_specimens(SpecimenQuery())).total == 0
    kept = await repo.get_specimen(row["id"])
    assert kept is not None
    assert kept["status"] == "archived"
    assert kept["archived_at"] is not None

    archived = await repo.list_specimens(SpecimenQuery(status="archived"))
    assert [r["id"] for r in archived.items] == [row["id"]]


@pytest.mark.asyncio
async def test_re_archiving_does_not_rewrite_the_date_it_was_lost_on(repo):
    row = await repo.create_specimen({"name": "Dittany"})
    await repo.archive_specimen(row["id"])
    first = (await repo.get_specimen(row["id"]))["archived_at"]
    await repo.archive_specimen(row["id"])
    assert (await repo.get_specimen(row["id"]))["archived_at"] == first


@pytest.mark.asyncio
async def test_archiving_something_that_does_not_exist_says_so(repo):
    assert await repo.archive_specimen(str(uuid.uuid4())) is False


@pytest.mark.asyncio
async def test_an_archived_plant_stops_counting_against_its_location(repo):
    row = await repo.create_specimen(
        {"name": "Lavandula", "species_id": LAVENDER, "location_id": OUTDOORS}
    )
    assert (await repo.get_location(str(OUTDOORS)))["specimen_count"] == 1
    await repo.archive_specimen(row["id"])
    assert (await repo.get_location(str(OUTDOORS)))["specimen_count"] == 0


# ------------------------------------------------------- filtering and search


@pytest.mark.asyncio
async def test_the_toxicity_filter_reads_the_species_table(repo):
    from inventory.repository import SpecimenQuery

    toxic = await repo.create_specimen({"name": "Monstera", "species_id": MONSTERA})
    safe = await repo.create_specimen({"name": "Lavandula", "species_id": LAVENDER})
    unknown = await repo.create_specimen({"name": "Dittany"})

    yes = await repo.list_specimens(SpecimenQuery(toxic_to_pets=True))
    no = await repo.list_specimens(SpecimenQuery(toxic_to_pets=False))
    assert [r["id"] for r in yes.items] == [toxic["id"]]
    assert {r["id"] for r in no.items} == {safe["id"], unknown["id"]}


@pytest.mark.asyncio
async def test_search_matches_nickname_accepted_name_and_common_names(repo):
    from inventory.repository import SpecimenQuery

    nicknamed = await repo.create_specimen(
        {"name": "Gilderoy", "nickname": "Gilderoy", "species_id": MONSTERA}
    )
    plain = await repo.create_specimen({"name": "Lavandula", "species_id": LAVENDER})

    async def found(q: str) -> set:
        return {r["id"] for r in (await repo.list_specimens(SpecimenQuery(q=q))).items}

    assert await found("gilder") == {nicknamed["id"]}
    assert await found("lavandula") == {plain["id"]}
    assert await found("English lav") == {plain["id"]}
    assert await found("swiss cheese") == {nicknamed["id"]}
    assert await found("nothing here") == set()


@pytest.mark.asyncio
async def test_the_register_pages_in_insertion_order(repo):
    from inventory.repository import SpecimenQuery

    made = [
        await repo.create_specimen({"name": f"Plant {n}", "species_id": LAVENDER})
        for n in range(5)
    ]
    first = await repo.list_specimens(SpecimenQuery(limit=2))
    assert first.total == 5
    assert first.next_cursor == "2"
    assert [r["id"] for r in first.items] == [made[0]["id"], made[1]["id"]]

    last = await repo.list_specimens(SpecimenQuery(limit=2, offset=4))
    assert last.next_cursor is None
    assert [r["id"] for r in last.items] == [made[4]["id"]]


@pytest.mark.asyncio
async def test_a_typed_name_resolves_against_the_species_table(repo):
    assert await repo.resolve_species_by_name("Monstera deliciosa") == str(MONSTERA)
    assert await repo.resolve_species_by_name("monstera DELICIOSA") == str(MONSTERA)
    assert await repo.resolve_species_by_name("English lavender") == str(LAVENDER)
    assert await repo.resolve_species_by_name("CERIMAN") == str(MONSTERA)
    assert await repo.resolve_species_by_name("Dittany of Crete") is None


# --------------------------------------------------------------- locations


@pytest.mark.asyncio
async def test_a_location_created_live_joins_the_household_site(repo):
    row = await repo.create_location(
        {
            "name": "Potting Shed",
            "kind": "room",
            "is_outdoor": False,
            "is_covered": True,
        }
    )
    assert row["site_id"] == SITE
    assert row["sun_exposure"] == "unknown"
    assert row["specimen_count"] == 0
    assert any(r["id"] == row["id"] for r in await repo.list_locations())


@pytest.mark.asyncio
async def test_locations_filter_by_site_and_exposure(repo):
    outdoors = await repo.list_locations(outdoor=True)
    assert {r["id"] for r in outdoors} == {OUTDOORS, PORCH}
    assert await repo.list_locations(site_id=str(uuid.uuid4())) == []


@pytest.mark.asyncio
async def test_editing_a_location_that_does_not_exist_answers_nothing(repo):
    assert (
        await repo.update_location(
            str(uuid.uuid4()), {"name": "x", "kind": "bed", "is_outdoor": True}
        )
        is None
    )


@pytest.mark.asyncio
async def test_members_come_from_the_database_in_live_mode(repo):
    members = await repo.list_members()
    assert [m["name"] for m in members] == ["Keeper"]


# ---------------------------------------------------- the router, live-backed


def test_the_exit_criterion_holds_against_a_real_database(live_client, spec):
    """Add a plant by name and it appears in the Register — on Postgres."""
    created = live_client.post(
        "/api/v1/specimens",
        json={"name": "Monstera deliciosa", "location_id": str(OUTDOORS)},
    )
    assert created.status_code == 201, created.text
    body = created.json()

    assert set(body) == set(spec["components"]["schemas"]["Specimen"]["properties"])
    assert body["species"]["accepted_name"] == "Monstera deliciosa"
    assert body["display_name"] == "Swiss cheese plant"
    assert body["is_outdoor"] is True

    register = live_client.get("/api/v1/specimens").json()
    assert register["total"] == 1
    assert register["items"][0]["id"] == body["id"]


def test_the_live_router_archives_rather_than_deletes(live_client):
    body = live_client.post("/api/v1/specimens", json={"name": "Dittany"}).json()
    assert live_client.delete(f"/api/v1/specimens/{body['id']}").status_code == 204
    assert live_client.get("/api/v1/specimens").json()["total"] == 0
    assert live_client.get(f"/api/v1/specimens/{body['id']}").status_code == 200


def test_the_live_router_keeps_the_outdoor_flag_in_step(live_client):
    body = live_client.post(
        "/api/v1/specimens",
        json={"name": "Lavandula angustifolia", "location_id": str(OUTDOORS)},
    ).json()
    assert body["is_outdoor"] is True

    live_client.patch(
        f"/api/v1/locations/{OUTDOORS}",
        json={"name": "Winter Room", "kind": "room", "is_outdoor": False},
    )
    after = live_client.get(f"/api/v1/specimens/{body['id']}").json()
    assert after["is_outdoor"] is False
    assert after["location"]["is_outdoor"] is False


def test_the_live_router_refuses_a_location_that_does_not_exist(live_client):
    response = live_client.post(
        "/api/v1/specimens", json={"name": "Nowhere", "location_id": str(uuid.uuid4())}
    )
    assert response.status_code == 422


# --------------------------------------------------- photographs and the log


async def _a_plant(repo, location=INDOORS):
    return await repo.create_specimen(
        {"species_id": MONSTERA, "location_id": location, "count": 1}
    )


async def _a_photo(repo, specimen_id, **extra):
    from inventory.photos import key_for

    photo_id = str(uuid.uuid4())
    repo.photo_images.put(key_for(photo_id, ".png"), b"\x89PNG\r\n\x1a\n")
    return await repo.create_photo(
        str(specimen_id),
        {"id": photo_id, "image_key": key_for(photo_id, ".png"), **extra},
    )


@pytest.mark.asyncio
async def test_photos_list_in_both_orders_and_the_portrait_is_exclusive(repo):
    from datetime import UTC, datetime

    plant = await _a_plant(repo)
    first = await _a_photo(
        repo,
        plant["id"],
        taken_at=datetime(2026, 8, 1, tzinfo=UTC),
        is_primary=True,
        member_id=str(KEEPER),
    )
    second = await _a_photo(
        repo, plant["id"], taken_at=datetime(2026, 9, 1, tzinfo=UTC), is_primary=True
    )
    newest = await repo.list_photos(str(plant["id"]), "newest")
    oldest = await repo.list_photos(str(plant["id"]), "oldest")
    assert [str(p["id"]) for p in newest] == [str(second["id"]), str(first["id"])]
    assert [str(p["id"]) for p in oldest] == [str(first["id"]), str(second["id"])]
    assert [p["is_primary"] for p in oldest] == [False, True]
    assert all(p["thumb_key"] is None for p in oldest)
    assert str(oldest[0]["taken_by"]) == str(KEEPER)
    fetched = await repo.get_specimen(str(plant["id"]))
    assert fetched["primary_photo_url"].endswith(f"/photos/{second['id']}/image")


@pytest.mark.asyncio
async def test_a_photo_is_only_found_under_its_own_plant(repo):
    mine = await _a_plant(repo)
    theirs = await _a_plant(repo)
    photo = await _a_photo(repo, mine["id"])
    assert await repo.get_photo(str(mine["id"]), str(photo["id"])) is not None
    assert await repo.get_photo(str(theirs["id"]), str(photo["id"])) is None


@pytest.mark.asyncio
async def test_a_log_entry_cites_its_own_plants_photo_and_the_join_reads_back(repo):
    from inventory.repository import UnknownPhotoError

    mine = await _a_plant(repo)
    theirs = await _a_plant(repo)
    photo = await _a_photo(repo, mine["id"])
    entry = await repo.create_log_entry(
        str(mine["id"]),
        {"kind": "growth", "body": "A leaf.", "photo_id": str(photo["id"])},
    )
    assert str(entry["photo"]["id"]) == str(photo["id"])
    assert str(entry["photo"]["log_entry_id"]) == str(entry["id"])
    listed = await repo.list_photos(str(mine["id"]), "newest")
    assert str(listed[0]["log_entry_id"]) == str(entry["id"])

    with pytest.raises(UnknownPhotoError):
        await repo.create_log_entry(
            str(theirs["id"]), {"kind": "growth", "photo_id": str(photo["id"])}
        )


@pytest.mark.asyncio
async def test_a_move_writes_its_relocate_entry_in_the_same_transaction(repo):
    plant = await _a_plant(repo, INDOORS)
    await repo.update_specimen(str(plant["id"]), {"location_id": OUTDOORS})
    entries = await repo.list_log_entries(str(plant["id"]), "newest")
    assert entries[0]["kind"] == "relocate"
    assert entries[0]["data"] == {
        "from_location_id": str(INDOORS),
        "to_location_id": str(OUTDOORS),
    }
    await repo.update_specimen(str(plant["id"]), {"nickname": "Still here"})
    assert len(await repo.list_log_entries(str(plant["id"]), "newest")) == 1
