"""The live repository's SQL, by shape, with no database attached.

CI has no Postgres, so ``test_database_repository.py`` skips there. This
module compiles the statement builders against the Postgres dialect and reads
the SQL: that ``?order=`` is an ``ORDER BY`` in the promised direction, that
``log_entry_id`` is the citation read backwards, that a photograph is looked up
under its own specimen and never by id alone, and that the two table
definitions name only columns the frozen schema has.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.dialects import postgresql

from inventory import tables
from inventory.database_repository import (
    DatabaseRepository,
    log_entries_statement,
    own_photo_statement,
    photos_statement,
    portraits_statement,
)
from inventory.photos import MemoryPhotoStore, key_for

SPECIMEN = "01890040-0000-7000-8000-000000000004"
PHOTO = "01890090-0000-7000-8000-000000000001"


def sql(statement: Any) -> str:
    return re.sub(r"\s+", " ", str(statement.compile(dialect=postgresql.dialect())))


def test_photos_are_ordered_by_taken_at_in_the_promised_direction() -> None:
    assert sql(photos_statement(SPECIMEN, "newest")).endswith(
        "ORDER BY photo.taken_at DESC, photo.id DESC"
    )
    assert sql(photos_statement(SPECIMEN, "oldest")).endswith(
        "ORDER BY photo.taken_at ASC, photo.id ASC"
    )


def test_log_entries_are_ordered_by_occurred_at_in_the_promised_direction() -> None:
    assert sql(log_entries_statement(SPECIMEN, "newest")).endswith(
        "ORDER BY log_entry.occurred_at DESC, log_entry.id DESC"
    )
    assert sql(log_entries_statement(SPECIMEN, "oldest")).endswith(
        "ORDER BY log_entry.occurred_at ASC, log_entry.id ASC"
    )


def test_log_entry_id_is_the_citation_read_backwards() -> None:
    text = sql(photos_statement(SPECIMEN, "newest"))
    assert "WHERE log_entry.photo_id = photo.id" in text
    assert "LIMIT" in text  # one id, deterministically, even if two entries cite
    assert ") AS log_entry_id" in text
    assert "WHERE photo.specimen_id = " in text


def test_a_photograph_is_looked_up_under_its_own_specimen() -> None:
    text = sql(own_photo_statement(SPECIMEN, PHOTO))
    assert "photo.id = " in text and "AND photo.specimen_id = " in text


def test_portraits_are_the_primary_rows_of_the_listed_specimens() -> None:
    text = sql(portraits_statement({SPECIMEN}))
    assert "photo.is_primary IS true" in text
    assert "photo.specimen_id IN" in text


def test_thumb_key_is_asked_of_the_store_not_the_row() -> None:
    key = key_for(PHOTO, ".jpg")
    row = {"id": PHOTO, "specimen_id": SPECIMEN, "image_key": key}

    unconfigured = DatabaseRepository(engine=None, photo_images=None)  # type: ignore[arg-type]
    assert unconfigured._hydrate_photo(row)["thumb_key"] is None

    store = MemoryPhotoStore()
    configured = DatabaseRepository(engine=None, photo_images=store)  # type: ignore[arg-type]
    assert configured._hydrate_photo(row)["thumb_key"] is None
    store.put(key_for(PHOTO, ".jpg", thumb=True), b"\xff\xd8\xff")
    assert configured._hydrate_photo(row)["thumb_key"] == f"{PHOTO}.thumb.jpg"


def _frozen_columns(repo_root: Path, table: str) -> set[str]:
    schema = (repo_root / "contracts" / "schema" / "001_init.sql").read_text()
    start = schema.index(f"CREATE TABLE {table} (")
    body = schema[start : schema.index("\n);", start)]
    return {
        line.strip().split()[0]
        for line in body.splitlines()[1:]
        if line.strip() and not line.strip().startswith(("--", "CHECK", "UNIQUE"))
    }


def test_the_two_tables_name_only_columns_the_frozen_schema_has(
    repo_root: Path,
) -> None:
    for table in (tables.photo, tables.log_entry):
        ours = {column.name for column in table.columns}
        assert ours <= _frozen_columns(repo_root, table.name), table.name
