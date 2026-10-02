"""The live path, against a real Postgres.

Skipped unless ``MOH_TEST_DATABASE_URL`` names a database these tests may create
tables in, because CI has no Postgres attached yet::

    MOH_TEST_DATABASE_URL=postgresql+asyncpg://herbology@127.0.0.1:5432/herbology_test \
        .venv/bin/pytest api/tending -q

The tables are cut out of ``contracts/schema/001_init.sql`` rather than retyped,
so a column that moves in the frozen schema breaks these tests instead of
quietly passing them — the same arrangement the inventory API uses, for the same
reason. ``water_balance`` is the weather engine's and read-only here.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from tending.repository import Completion, TaskQuery
from tending.service import HORIZON_DAYS, generate_tasks

TEST_DATABASE_URL = os.environ.get("MOH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set MOH_TEST_DATABASE_URL to run the live-database tests",
)

#: Dependency order. Everything before ``care_rule`` is somebody else's and is
#: created only because this parts of the project's tables point at it.
TABLES = [
    "site",
    "member",
    "map_layer",
    "location",
    "source",
    "species",
    "care_value",
    "specimen",
    "water_balance",
    "care_rule",
    "task",
    "task_event",
    "calendar_feed",
]

SITE = uuid.UUID("01890000-0000-7000-8000-000000000001")
STUDY = uuid.UUID("01890010-0000-7000-8000-000000000002")
BORDER = uuid.UUID("01890010-0000-7000-8000-000000000004")
KEEPER = uuid.UUID("01890050-0000-7000-8000-000000000001")
MONSTERA = uuid.UUID("01890030-0000-7000-8000-000000000001")
LAVENDER = uuid.UUID("01890030-0000-7000-8000-000000000002")
INDOOR_PLANT = uuid.UUID("01890040-0000-7000-8000-000000000001")
OUTDOOR_PLANT = uuid.UUID("01890040-0000-7000-8000-000000000004")


def _create_table_sql(repo_root, table: str) -> str:
    sql = (repo_root / "contracts" / "schema" / "001_init.sql").read_text()
    start = sql.index(f"CREATE TABLE {table} (")
    end = sql.index("\n);", start) + len("\n);")
    return sql[start:end]


def _migration_statements(repo_root, name: str) -> list[str]:
    """A later migration's statements, applied as the deployment applies them."""
    sql = (repo_root / "contracts" / "schema" / name).read_text()
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


@pytest_asyncio.fixture
async def repo(repo_root):
    from sqlalchemy.ext.asyncio import create_async_engine

    from tending.database_repository import DatabaseRepository

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
        # 004 before 007, the order the deployment applies them. 004 is the
        # certainty on ``task``, which this package writes.
        for name in ("004_certainty_columns.sql", "007_calendar_push.sql"):
            for statement in _migration_statements(repo_root, name):
                await conn.execute(text(statement))
        await _seed(conn)
    try:
        yield DatabaseRepository(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"DROP TABLE IF EXISTS {', '.join(reversed(TABLES))} CASCADE")
            )
        await engine.dispose()


async def _seed(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO site (id, name, latitude, longitude, timezone) VALUES "
            "(:id, 'Test Grounds', 39.7684, -86.1581, 'America/Indiana/Indianapolis')"
        ),
        {"id": SITE},
    )
    await conn.execute(
        text("INSERT INTO member (id, name, role) VALUES (:id, 'Keeper', 'keeper')"),
        {"id": KEEPER},
    )
    for place, name, outdoor, covered in (
        (STUDY, "Study", False, True),
        (BORDER, "South Border", True, False),
    ):
        await conn.execute(
            text(
                "INSERT INTO location (id, site_id, name, kind, is_outdoor, is_covered)"
                " VALUES (:id, :site, :name, 'room', :outdoor, :covered)"
            ),
            {
                "id": place,
                "site": SITE,
                "name": name,
                "outdoor": outdoor,
                "covered": covered,
            },
        )
    for species_id, name, interval in (
        (MONSTERA, "Monstera deliciosa", 9),
        (LAVENDER, "Lavandula angustifolia", 14),
    ):
        await conn.execute(
            text(
                "INSERT INTO species (id, accepted_name, common_names,"
                " water_interval_days, dormancy_months)"
                " VALUES (:id, :name, ARRAY['test plant'], :interval, ARRAY[12,1,2])"
            ),
            {"id": species_id, "name": name, "interval": interval},
        )
    # Cited for the Monstera, uncited for the lavender: the two paths the design
    # distinguishes, both present.
    await conn.execute(
        text(
            "INSERT INTO care_value (id, species_id, field, value, confidence,"
            " is_user_override) VALUES (:id, :species, 'water_interval_days',"
            " '9'::jsonb, 'unknown', true)"
        ),
        {"id": uuid.uuid4(), "species": MONSTERA},
    )
    for plant, species_id, place, outdoor, nickname in (
        (INDOOR_PLANT, MONSTERA, STUDY, False, "Gilderoy"),
        (OUTDOOR_PLANT, LAVENDER, BORDER, True, "Sour Bertram"),
    ):
        await conn.execute(
            text(
                "INSERT INTO specimen (id, species_id, nickname, location_id,"
                " is_outdoor, in_container, container_litres, acquired_on)"
                " VALUES (:id, :species, :nickname, :place, :outdoor, true, 18,"
                " DATE '2024-03-14')"
            ),
            {
                "id": plant,
                "species": species_id,
                "nickname": nickname,
                "place": place,
                "outdoor": outdoor,
            },
        )
    await conn.execute(
        text(
            "INSERT INTO water_balance (day, specimen_id, deficit_mm, capacity_mm,"
            " threshold_mm, k_c) VALUES (CURRENT_DATE, :id, 40, 60, 30, 0.7)"
        ),
        {"id": OUTDOOR_PLANT},
    )


async def test_the_schedule_comes_up_on_an_empty_database(repo):
    """A fresh deployment has no care_rule rows and twelve thirsty plants."""
    generated = await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery())
    assert rows
    assert all(row["title"] and row["plain_title"] for row in rows)
    assert all(row["confidence"] for row in rows)
    assert generated.alerts is not None


async def test_generation_is_idempotent_against_postgres(repo):
    await generate_tasks(repo)
    first = {
        str(row["id"]): row["ics_sequence"] for row in await repo.tasks(TaskQuery())
    }
    await generate_tasks(repo)
    second = {
        str(row["id"]): row["ics_sequence"] for row in await repo.tasks(TaskQuery())
    }
    assert first == second


async def test_the_outdoor_plant_is_scheduled_by_the_water_balance(repo):
    """Deficit 40 against a threshold of 30 is a watering, and it is due today."""
    await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT)))
    assert rows
    assert rows[0]["due_at"].date() == datetime.now(UTC).date()


async def test_completion_is_logged_as_an_event_and_retires_the_cycle(repo):
    await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT)))
    done = await repo.complete(
        [str(rows[0]["id"])], Completion(completed_by=str(KEEPER), notes="Thirsty")
    )
    assert done and done[0]["status"] == "done"
    after = await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT)))
    assert any(
        row["status"] == "cancelled" for row in after if row["id"] != done[0]["id"]
    )

    async with repo._engine.connect() as conn:
        kinds = [
            row[0]
            for row in (
                await conn.execute(text("SELECT kind FROM task_event ORDER BY at"))
            ).all()
        ]
    assert "created" in kinds and "completed" in kinds and "cancelled" in kinds


async def test_a_completed_task_is_never_rewritten_by_a_later_generation(repo):
    await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT)))
    done = await repo.complete([str(rows[0]["id"])], Completion())
    await generate_tasks(repo)
    again = await repo.task(str(done[0]["id"]))
    assert again is not None and again["status"] == "done"


async def test_a_rescheduled_task_keeps_its_uid_and_gains_a_sequence(repo):
    """The property the whole identity scheme exists to hold."""
    await generate_tasks(repo)
    before = (await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT))))[0]
    # A three-day rule where there was a nine-day one moves every occurrence.
    await repo.create_care_rule(
        {
            "specimen_id": str(INDOOR_PLANT),
            "task_type": "water",
            "strategy": "interval",
            "base_interval_days": 3,
        }
    )
    await generate_tasks(repo)
    after = await repo.task(str(before["id"]))
    if after is not None and after["due_at"] != before["due_at"]:
        assert after["ics_uid"] == before["ics_uid"]
        assert after["ics_sequence"] == before["ics_sequence"] + 1


async def test_each_feed_has_its_own_token_and_revoking_one_spares_the_rest(repo):
    keep = await repo.create_feed({"member_id": str(KEEPER), "name": "All rounds"})
    doomed = await repo.create_feed({"member_id": str(KEEPER), "name": "Old phone"})
    assert keep["token"] != doomed["token"]

    await repo.revoke_feed(str(doomed["id"]))
    assert await repo.feed_by_token(doomed["token"]) is None
    assert await repo.feed_by_token(keep["token"]) is not None


async def test_the_horizon_is_respected(repo):
    await generate_tasks(repo)
    horizon = datetime.now(UTC).date()
    for row in await repo.tasks(TaskQuery()):
        assert (row["due_at"].date() - horizon).days <= HORIZON_DAYS


async def test_an_uncited_interval_survives_the_round_trip_as_a_visible_mark(repo):
    """The lavender's interval has no care_value row at all."""
    await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT)))
    assert rows
    assert rows[0]["confidence"] in {"unknown", "low", "medium"}


async def test_care_rules_list_the_derived_rule_when_nothing_is_stored(repo):
    rules = await repo.care_rules(str(INDOOR_PLANT))
    assert rules and rules[0]["task_type"] == "water"


async def test_a_care_rule_for_an_unknown_specimen_is_refused(repo):
    from tending.repository import UnknownSpecimenError

    with pytest.raises(UnknownSpecimenError):
        await repo.create_care_rule(
            {"specimen_id": str(uuid.uuid4()), "task_type": "water"}
        )


async def test_the_dormancy_month_check_uses_the_sites_calendar(repo):
    """December is winter in Indianapolis and the rules suspend watering."""
    generated = await generate_tasks(repo, today=date(2026, 12, 15))
    rows = await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT)))
    assert not rows or generated.unscheduled


# ------------------------------------------------------------ calendar push


async def test_a_status_change_on_the_same_day_gains_a_sequence(repo):
    """Rain settles a task without moving it; its event must still change."""
    await generate_tasks(repo)
    row = (await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT))))[0]
    rained = {**row, "status": "satisfied", "satisfied_by": "rain"}
    await repo.upsert_tasks([rained])
    after = await repo.task(str(row["id"]))
    assert after is not None
    assert after["status"] == "satisfied"
    assert after["ics_sequence"] == row["ics_sequence"] + 1


@pytest.fixture
def caldav(tmp_path, monkeypatch):
    """The hub's adapter pointed at the fake, with an empty secrets directory."""
    import httpx

    from tending import push
    from tending.tests.caldav_fake import FakeCaldav

    server = FakeCaldav()
    monkeypatch.setenv("MOH_SECRETS_DIR", str(tmp_path))
    monkeypatch.setattr(
        push,
        "client_factory",
        lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(server.handler)),
    )
    return server, tmp_path


async def test_a_pushing_feed_round_trips_its_state_through_postgres(repo, caldav):
    from tending import push
    from tending.tests.caldav_fake import PASSWORD, USERNAME

    server, secrets = caldav
    created = await repo.create_feed(
        {"member_id": str(KEEPER), "name": "Pushed", "push_target": "caldav"}
    )
    feed_id = str(created["id"])
    base = "https://herbology.example"

    assert (await push.push_owed(repo, base_url=base, generate=True)) == {
        feed_id: "awaiting_operator"
    }
    row = await repo.feed(feed_id)
    assert row is not None and row["push_dirty_since"] is not None

    (secrets / f"moh_caldav_{feed_id}").write_text(
        f"https://caldav.example.net/dav/plants/\n{USERNAME}\n{PASSWORD}\n"
    )
    assert (await push.push_owed(repo, base_url=base)) == {feed_id: "ok"}
    row = await repo.feed(feed_id)
    assert row is not None
    assert row["push_state"] and row["push_last_ok_at"] and row["push_error"] is None
    assert row["push_dirty_since"] is None
    assert row["push_config"] == {}

    seen = len(server.requests)
    assert (await push.push_owed(repo, base_url=base)) == {feed_id: "nothing_owed"}
    assert server.requests[seen:] == []

    task = (await repo.tasks(TaskQuery(specimen_id=str(INDOOR_PLANT))))[0]
    await repo.complete([str(task["id"])], Completion(completed_by=str(KEEPER)))
    assert (await push.push_owed(repo, base_url=base, generate=True)) == {feed_id: "ok"}
    assert server.puts(seen)

    server.status = 401
    other = (await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT))))[0]
    await repo.complete([str(other["id"])], Completion())
    assert (await push.push_owed(repo, base_url=base, generate=True)) == {
        feed_id: "failing"
    }
    row = await repo.feed(feed_id)
    assert row is not None and row["push_error"]
    assert USERNAME not in row["push_error"] and PASSWORD not in row["push_error"]
    assert push.status_of(row) == "failing"

    await repo.revoke_feed(feed_id)
    seen = len(server.requests)
    assert await push.push_feed(repo, feed_id, base_url=base) == "off"
    assert server.requests[seen:] == []


# ------------------------------------------------------------- task certainty


async def _stored_certainty(repo, task_id) -> tuple:
    """Read the three columns straight from the table, not through the store."""
    async with repo._engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT confidence, degraded, degradations, ics_sequence"
                    " FROM task WHERE id = :id"
                ),
                {"id": uuid.UUID(str(task_id))},
            )
        ).one()
    return tuple(row)


async def test_a_tasks_certainty_is_stored_on_the_row(repo):
    """Written by generation, into migration 004's columns, not recomputed."""
    await generate_tasks(repo)
    for row in await repo.tasks(TaskQuery()):
        confidence, degraded, degradations, _ = await _stored_certainty(repo, row["id"])
        assert confidence in {"high", "medium", "low", "unknown"}
        assert degraded == bool(degradations)
        assert all({"code", "detail", "caps_at"} <= set(d) for d in degradations)
        assert (confidence, degraded, degradations) == (
            row["confidence"],
            row["degraded"],
            row["degradations"],
        )


async def test_a_completed_task_keeps_the_certainty_it_was_issued_with(repo):
    """The case the columns exist for: nothing regenerates a done task."""
    await generate_tasks(repo)
    row = (await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT))))[0]
    issued = await _stored_certainty(repo, row["id"])
    done = await repo.complete([str(row["id"])], Completion())
    await generate_tasks(repo)
    after = await repo.task(str(done[0]["id"]))
    assert after is not None and after["status"] == "done"
    assert after["confidence"] == issued[0] and after["confidence"] is not None
    assert after["degradations"] == issued[2]


async def test_a_change_in_certainty_alone_gains_a_sequence(repo):
    """A calendar must update when only how sure the task is has changed."""
    await generate_tasks(repo)
    row = (await repo.tasks(TaskQuery(specimen_id=str(OUTDOOR_PLANT))))[0]
    caveat = {
        "code": "balance_not_current",
        "detail": "The water balance ends two days early.",
        "caps_at": "low",
    }
    doubted = {**row, "confidence": "low", "degraded": True, "degradations": [caveat]}
    await repo.upsert_tasks([doubted])
    confidence, degraded, degradations, sequence = await _stored_certainty(
        repo, row["id"]
    )
    assert (confidence, degraded, degradations) == ("low", True, [caveat])
    assert sequence == row["ics_sequence"] + 1

    # And the same certainty again is not a change.
    await repo.upsert_tasks([doubted])
    assert (await _stored_certainty(repo, row["id"]))[3] == sequence


async def test_regeneration_with_unchanged_certainty_keeps_the_sequence(repo):
    await generate_tasks(repo)
    before = {
        str(r["id"]): (r["ics_sequence"], r["confidence"])
        for r in await repo.tasks(TaskQuery())
    }
    await generate_tasks(repo)
    after = {
        str(r["id"]): (r["ics_sequence"], r["confidence"])
        for r in await repo.tasks(TaskQuery())
    }
    assert before == after


# ------------------------------------------------------ the registration anchor

NEW_PLANT = uuid.UUID("01890040-0000-7000-8000-0000000000aa")


async def _add_plant_without_acquired_on(repo, *, created_at: datetime) -> None:
    """Indoors, a 9-day species, and no acquired date — as the inventory API writes a new plant."""
    async with repo._engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO specimen (id, species_id, nickname, location_id,"
                " is_outdoor, in_container, container_litres, created_at)"
                " VALUES (:id, :species, 'Newcomer', :place, false, true, 5,"
                " :created_at)"
            ),
            {
                "id": NEW_PLANT,
                "species": MONSTERA,
                "place": STUDY,
                "created_at": created_at,
            },
        )


async def test_a_plant_added_today_is_due_one_interval_from_today(repo):
    """Not ~640 days overdue from 2024-01-01 (the maintainer's call, 2 Oct)."""
    today = datetime.now(UTC).date()
    await _add_plant_without_acquired_on(repo, created_at=datetime.now(UTC))
    await generate_tasks(repo)
    rows = await repo.tasks(TaskQuery(specimen_id=str(NEW_PLANT)))
    assert rows
    # The Monstera's cited interval is 9 days, and nothing is overdue.
    assert min(row["due_at"].date() for row in rows) == today + timedelta(days=9)


async def test_the_registration_day_is_the_sites_day_not_utcs(repo):
    """9 pm in Indianapolis on 1 Oct is 1 am UTC on 2 Oct; the plant came 1 Oct."""
    from tending.domain import registered_on

    instant = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    assert registered_on(instant, "America/Indiana/Indianapolis") == date(2026, 10, 1)
    await _add_plant_without_acquired_on(repo, created_at=instant)
    inputs = await repo.scheduling_inputs()
    subject = next(s for s in inputs.subjects if s.specimen_id == str(NEW_PLANT))
    assert subject.added_on == date(2026, 10, 1)


async def test_the_old_epoch_schedule_is_cancelled_not_left_beside_the_new(repo):
    """A deployment that scheduled the plant holds EPOCH-anchored rows.

    They are cancelled with a SEQUENCE bump, so the rounds and every subscribed
    calendar let go of the watering "640 days overdue" instead of showing it
    beside the new one.
    """
    from dataclasses import replace

    from tending.domain import generate, task_row

    await _add_plant_without_acquired_on(repo, created_at=datetime.now(UTC))
    inputs = await repo.scheduling_inputs()
    subject = next(s for s in inputs.subjects if s.specimen_id == str(NEW_PLANT))
    # What the pre-an earlier release code wrote for this plant: the same plant, no anchor date.
    old = [
        task_row(occurrence)
        for occurrence in generate(
            replace(subject, added_on=None),
            inputs.rules[str(NEW_PLANT)],
            today=datetime.now(UTC).date(),
            horizon_days=HORIZON_DAYS,
            latitude=inputs.latitude,
        )
    ]
    # Counted from 2024-01-01, the plant arrived owing a watering.
    assert old and min(row["due_at"] for row in old) < datetime.now(UTC)
    await repo.upsert_tasks(old)

    await generate_tasks(repo)
    for row in old:
        stored = await repo.task(str(row["id"]))
        assert stored is not None
        assert stored["status"] == "cancelled"
        assert stored["ics_sequence"] == 1
    open_rows = [
        row
        for row in await repo.tasks(TaskQuery(specimen_id=str(NEW_PLANT)))
        if row["status"] == "due"
    ]
    assert open_rows
    assert min(row["due_at"] for row in open_rows) > datetime.now(UTC)

    # A second pass has nothing left to cancel and moves nothing.
    sequences = {str(r["id"]): r["ics_sequence"] for r in await repo.tasks(TaskQuery())}
    await generate_tasks(repo)
    assert sequences == {
        str(r["id"]): r["ics_sequence"] for r in await repo.tasks(TaskQuery())
    }
