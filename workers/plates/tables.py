"""SQLAlchemy Core tables for the journal subset of the frozen schema.

These mirror ``contracts/schema/001_init.sql`` and never create it — migrations
are forward-only SQL owned by the maintainers. The definitions stay narrow (the
columns this API reads or writes), so a schema change that matters shows up
here as a mismatch rather than as silence.

``member`` is the inventory API's table and is read-only here: a field note's author
and a plate's approver are both members, and the journal needs their names to
show them.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

plate = Table(
    "plate",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("species_id", Uuid),
    Column("specimen_id", Uuid),
    Column("image_key", Text, nullable=False),
    Column("thumb_key", Text),
    Column("origin", Text, nullable=False),
    Column("source_id", Uuid),
    Column("license", Text),
    Column("attribution", Text),
    Column("style", Text),
    Column("approved", Boolean, nullable=False),
    Column("approved_by", Uuid),
    Column("created_at", DateTime(timezone=True)),
)

field_note = Table(
    "field_note",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("specimen_id", Uuid, nullable=False),
    Column("body", Text, nullable=False),
    Column("written_at", DateTime(timezone=True)),
    Column("written_by", Uuid),
)

#: Read-only. The inventory API's table.
member = Table(
    "member",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("notify_prefs", JSONB),
)
