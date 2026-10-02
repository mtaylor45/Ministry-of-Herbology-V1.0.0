"""The live path, against a real Postgres.

Skipped unless ``MOH_TEST_DATABASE_URL`` names a database these tests may
create tables in, because CI has no Postgres attached yet::

    MOH_TEST_DATABASE_URL=postgresql+asyncpg://herbology@127.0.0.1:5432/herbology_test \
        .venv/bin/python -m pytest api/grounds -q

The tables are cut out of ``contracts/schema/001_init.sql`` rather than
retyped, so a column that moves in the frozen schema breaks these tests
instead of quietly passing them — including the two columns of the inventory API's
``specimen`` table that a pin actually is.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from grounds.database_repository import DatabaseRepository
from grounds.repository import (
    PinOutsideLayerError,
    UnknownLayerError,
    UnknownSpecimenError,
)

TEST_DATABASE_URL = os.environ.get("MOH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set MOH_TEST_DATABASE_URL to run the live-database tests",
)

#: Dependency order. ``location`` is here because ``specimen`` points at it.
TABLES = ["site", "map_layer", "location", "species", "specimen"]

SITE = uuid.UUID("01890000-0000-7000-8000-000000000001")
PLAN = uuid.UUID("01890070-0000-7000-8000-000000000001")
SURVEY = uuid.UUID("01890070-0000-7000-8000-000000000002")
INDOORS = uuid.UUID("01890010-0000-7000-8000-000000000002")
MONSTERA = uuid.UUID("01890030-0000-7000-8000-000000000001")
NAMED = uuid.UUID("01890040-0000-7000-8000-000000000001")
UNNAMED = uuid.UUID("01890040-0000-7000-8000-000000000002")

PLAN_SIZE = (1600, 1200)
SURVEY_SIZE = (2000, 1500)


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


@pytest.fixture
def repo(engine) -> DatabaseRepository:
    return DatabaseRepository(engine)


async def _seed(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO site (id, name, latitude, longitude, timezone)"
            " VALUES (:id, 'Test Grounds', 39.7, -86.1, 'America/Indiana/Indianapolis')"
        ),
        {"id": SITE},
    )
    await conn.execute(
        text(
            "INSERT INTO location (id, site_id, name, kind, is_outdoor, is_covered)"
            " VALUES (:id, :site, 'Study', 'room', false, true)"
        ),
        {"id": INDOORS, "site": SITE},
    )
    await conn.execute(
        text(
            "INSERT INTO species (id, accepted_name, common_names)"
            " VALUES (:id, 'Monstera deliciosa', ARRAY['swiss cheese plant'])"
        ),
        {"id": MONSTERA},
    )
    for layer_id, name, kind, (width, height), ordinal in (
        (PLAN, "Ground floor", "floor_plan", PLAN_SIZE, 0),
        (SURVEY, "Property survey", "survey", SURVEY_SIZE, 1),
    ):
        await conn.execute(
            text(
                "INSERT INTO map_layer (id, site_id, name, kind, image_key,"
                " image_width_px, image_height_px, calibration, ordinal)"
                " VALUES (:id, :site, :name, :kind, :key, :w, :h,"
                ' \'{"scale_mm_per_px": null, "points": []}\'::jsonb, :ordinal)'
            ),
            {
                "id": layer_id,
                "site": SITE,
                "name": name,
                "kind": kind,
                "key": f"{layer_id}.png",
                "w": width,
                "h": height,
                "ordinal": ordinal,
            },
        )
    for specimen_id, nickname in ((NAMED, "Gilderoy"), (UNNAMED, None)):
        await conn.execute(
            text(
                "INSERT INTO specimen (id, species_id, nickname, location_id,"
                " is_outdoor, is_group, count) VALUES (:id, :species, :nickname,"
                " :location, false, false, 1)"
            ),
            {
                "id": specimen_id,
                "species": MONSTERA,
                "nickname": nickname,
                "location": INDOORS,
            },
        )


# --------------------------------------------------------------------- reads


async def test_layers_come_back_in_stacking_order(repo: DatabaseRepository) -> None:
    layers = await repo.list_layers()
    assert [row["kind"] for row in layers] == ["floor_plan", "survey"]
    assert (layers[0]["image_width_px"], layers[0]["image_height_px"]) == PLAN_SIZE


async def test_an_unknown_or_malformed_layer_id_is_a_miss_not_a_crash(
    repo: DatabaseRepository,
) -> None:
    assert await repo.get_layer(str(uuid.uuid4())) is None
    assert await repo.get_layer("certainly-not-a-uuid") is None
    assert await repo.list_pins("certainly-not-a-uuid") == []


async def test_an_unpinned_specimen_is_not_a_pin(repo: DatabaseRepository) -> None:
    """The seed places nobody, so the Grounds start empty rather than at zero-zero."""
    assert await repo.list_pins() == []


async def test_the_default_site_is_the_household(repo: DatabaseRepository) -> None:
    assert await repo.default_site_id() == str(SITE)


# -------------------------------------------------------------------- writes


async def test_a_pin_is_two_columns_of_a_specimen(
    repo: DatabaseRepository, engine
) -> None:
    await repo.set_pin(str(NAMED), str(PLAN), {"x": 100, "y": 200})
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT map_layer_id, pin_px FROM specimen WHERE id = :id"),
                {"id": NAMED},
            )
        ).one()
    assert str(row[0]) == str(PLAN)
    assert row[1] == {"x": 100.0, "y": 200.0}


async def test_lifting_a_pin_clears_both_columns_together(
    repo: DatabaseRepository, engine
) -> None:
    """A `pin_px` with no `map_layer_id` would be a pin on no map."""
    await repo.set_pin(str(NAMED), str(PLAN), {"x": 10, "y": 10})
    await repo.set_pin(str(NAMED), str(PLAN), None)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT map_layer_id, pin_px FROM specimen WHERE id = :id"),
                {"id": NAMED},
            )
        ).one()
    assert row == (None, None)
    assert await repo.list_pins() == []


async def test_a_pin_reads_back_with_the_brief_a_cross_link_needs(
    repo: DatabaseRepository,
) -> None:
    await repo.set_pin(str(NAMED), str(SURVEY), {"x": 1, "y": 2})
    pins = await repo.list_pins()
    assert len(pins) == 1
    assert pins[0]["specimen"]["display_name"] == "Gilderoy"
    assert pins[0]["layer_id"] == str(SURVEY)
    assert pins[0]["px"] == {"x": 1.0, "y": 2.0}


async def test_a_specimen_with_no_nickname_falls_back_to_its_common_name(
    repo: DatabaseRepository,
) -> None:
    written = await repo.set_pin(str(UNNAMED), str(PLAN), {"x": 5, "y": 5})
    assert written["specimen"]["display_name"] == "Swiss cheese plant"


async def test_filtering_pins_by_layer_narrows_them(repo: DatabaseRepository) -> None:
    await repo.set_pin(str(NAMED), str(PLAN), {"x": 1, "y": 1})
    await repo.set_pin(str(UNNAMED), str(SURVEY), {"x": 1, "y": 1})
    assert len(await repo.list_pins(str(PLAN))) == 1
    assert len(await repo.list_pins(str(SURVEY))) == 1
    assert len(await repo.list_pins()) == 2


async def test_a_pin_off_the_sheet_is_refused_and_nothing_is_written(
    repo: DatabaseRepository,
) -> None:
    with pytest.raises(PinOutsideLayerError):
        await repo.set_pin(str(NAMED), str(PLAN), {"x": PLAN_SIZE[0] + 1, "y": 0})
    assert await repo.list_pins() == []


async def test_unknown_ids_are_refused(repo: DatabaseRepository) -> None:
    with pytest.raises(UnknownLayerError):
        await repo.set_pin(str(NAMED), str(uuid.uuid4()), {"x": 1, "y": 1})
    with pytest.raises(UnknownSpecimenError):
        await repo.set_pin(str(uuid.uuid4()), str(PLAN), {"x": 1, "y": 1})


async def test_an_uploaded_layer_stacks_above_the_ones_already_there(
    repo: DatabaseRepository,
) -> None:
    created = await repo.create_layer(
        {
            "site_id": str(SITE),
            "name": "North plat",
            "kind": "survey",
            "image_key": f"{uuid.uuid4()}.png",
            "image_width_px": 800,
            "image_height_px": 600,
        }
    )
    assert created["ordinal"] == 2
    assert created["calibration"] == {"scale_mm_per_px": None, "points": []}
    assert [row["name"] for row in await repo.list_layers()][-1] == "North plat"


async def test_calibration_and_its_scale_are_written_together(
    repo: DatabaseRepository,
) -> None:
    stored = {"scale_mm_per_px": 12.5, "points": []}
    updated = await repo.set_calibration(str(PLAN), stored)
    assert updated is not None
    assert updated["scale_mm_per_px"] == 12.5
    assert updated["calibration"] == stored
    assert (await repo.get_layer(str(PLAN)))["scale_mm_per_px"] == 12.5


async def test_calibrating_a_layer_that_is_not_there_is_a_miss(
    repo: DatabaseRepository,
) -> None:
    assert await repo.set_calibration(str(uuid.uuid4()), {"points": []}) is None


async def test_the_schema_default_for_calibration_is_normalised_on_the_way_out(
    repo: DatabaseRepository, engine
) -> None:
    """``001_init.sql`` defaults the column to `'[]'::jsonb` — a list, not the
    object ``Calibration`` declares. A row inserted by anything but this API
    must still serve a legal ``MapLayer``."""
    legacy = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO map_layer (id, site_id, name, kind, image_key,"
                " image_width_px, image_height_px) VALUES (:id, :site, 'Legacy',"
                " 'floor_plan', :key, 10, 10)"
            ),
            {"id": legacy, "site": SITE, "key": f"{legacy}.png"},
        )
    row = await repo.get_layer(str(legacy))
    assert row is not None
    assert row["calibration"] == {"scale_mm_per_px": None, "points": []}
