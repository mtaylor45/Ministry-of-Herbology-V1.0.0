"""The Postgres session store against a real database (migration 008).

Skips unless ``MOH_TEST_DATABASE_URL`` names a database; CI provides one (B,
an earlier release) and fails the job if this skips. The table is cut out of migration 008
itself rather than retyped, as the other live suites do with 001, so a column
that changes in the migration breaks this test instead of drifting from it.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.auth import tokens
from app.auth.store import IDLE_LIFETIME, database_store, is_live, now_utc
from app.settings import REPO_ROOT

DATABASE_URL = os.environ.get("MOH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="needs MOH_TEST_DATABASE_URL")


MIGRATION = (
    REPO_ROOT
    / "contracts"
    / "schema"
    / "008_household_session_and_enrichment_retry.sql"
)


def _session_table_sql() -> list[str]:
    """The CREATE TABLE and CREATE INDEX for household_session, verbatim."""
    sql = MIGRATION.read_text()
    start = sql.index("CREATE TABLE household_session (")
    end = sql.index("ALTER TABLE species")
    body = "\n".join(
        line
        for line in sql[start:end].splitlines()
        if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in body.split(";") if statement.strip()]


@pytest.fixture
async def store():
    assert DATABASE_URL is not None
    store = database_store(DATABASE_URL)
    async with store._engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS household_session"))
        for statement in _session_table_sql():
            await connection.execute(text(statement))
    yield store
    async with store._engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS household_session"))
    await store._engine.dispose()


async def test_a_session_round_trips_by_its_hash_only(store) -> None:
    epoch = tokens.epoch_of("a long garden passphrase")
    token = tokens.new_token()
    created = await store.create(tokens.hash_token(token), epoch, "Safari on iPhone")
    found = await store.find(tokens.hash_token(token))
    assert found is not None and found.id == created.id
    assert found.token_hash == tokens.hash_token(token) != token.encode()
    assert is_live(found, epoch, now_utc())
    assert await store.find(tokens.hash_token("someone else's")) is None


async def test_revocation_one_and_all(store) -> None:
    epoch = tokens.epoch_of("a long garden passphrase")
    a = await store.create(tokens.hash_token("a" * 43), epoch, "A device")
    b = await store.create(tokens.hash_token("b" * 43), epoch, "A device")
    await store.revoke(a.id, now_utc())
    assert [s.id for s in await store.list_live(epoch, now_utc())] == [b.id]
    await store.revoke_all(now_utc())
    assert await store.list_live(epoch, now_utc()) == []


async def test_idle_and_epoch_end_a_session(store) -> None:
    epoch = tokens.epoch_of("a long garden passphrase")
    session = await store.create(tokens.hash_token("c" * 43), epoch, "A device")
    later = now_utc() + IDLE_LIFETIME + timedelta(minutes=1)
    assert not is_live(session, epoch, later)
    assert not is_live(session, tokens.epoch_of("a different passphrase"), now_utc())
    await store.touch(session, later - timedelta(minutes=2))
    touched = await store.find(session.token_hash)
    assert touched is not None and is_live(touched, epoch, later)
