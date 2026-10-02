"""SQLAlchemy Core tables for the inventory subset of the frozen schema.

These mirror ``contracts/schema/001_init.sql`` and are never used to create it —
migrations are forward-only SQL owned by the maintainers. Keeping the definitions
narrow (the columns this API reads or writes) means a schema change that
matters shows up here as a mismatch rather than as silence.

``species`` and ``source`` are the botany worker's tables; inventory reads them to
hydrate a specimen's ``SpeciesBrief`` and to answer the toxicity filter, and
never writes to them.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

#: Read-only here. Owner: The maintainers; inventory needs it only to attach a
#: newly created location to the household's site.
site = Table(
    "site",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

member = Table(
    "member",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("notify_prefs", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("archived_at", DateTime(timezone=True)),
)

location = Table(
    "location",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("site_id", Uuid, nullable=False),
    Column("parent_id", Uuid),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("is_outdoor", Boolean, nullable=False),
    Column("is_covered", Boolean, nullable=False),
    Column("sun_exposure", Text),
    Column("map_layer_id", Uuid),
    Column("boundary_px", JSONB),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("archived_at", DateTime(timezone=True)),
)

specimen = Table(
    "specimen",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("species_id", Uuid),
    Column("nickname", Text),
    Column("cultivar", Text),
    Column("is_group", Boolean, nullable=False),
    Column("count", Integer, nullable=False),
    Column("location_id", Uuid),
    Column("map_layer_id", Uuid),
    Column("pin_px", JSONB),
    Column("is_outdoor", Boolean, nullable=False),
    Column("in_container", Boolean, nullable=False),
    Column("container_litres", Float),
    Column("container_note", Text),
    Column("soil_note", Text),
    Column("acquired_on", Date),
    Column("provenance", Text),
    Column("status", Text, nullable=False),
    Column("water_k_c_override", Float),
    Column("water_interval_days_override", Integer),
    Column("min_temp_c_override", Float),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("archived_at", DateTime(timezone=True)),
)

#: Read-only here. Owner: The botany worker.
species = Table(
    "species",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("accepted_name", Text, nullable=False),
    Column("family", Text),
    Column("genus", Text),
    Column("common_names", ARRAY(Text), nullable=False),
    Column("toxic_to_pets", Boolean),
    Column("toxic_to_children", Boolean),
)

photo = Table(
    "photo",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("specimen_id", Uuid, nullable=False),
    Column("image_key", Text, nullable=False),
    Column("taken_at", DateTime(timezone=True), nullable=False),
    Column("caption", Text),
    Column("is_primary", Boolean, nullable=False),
    Column("taken_by", Uuid),
)

log_entry = Table(
    "log_entry",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("specimen_id", Uuid, nullable=False),
    Column("kind", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("body", Text),
    Column("photo_id", Uuid),
    Column("data", JSONB, nullable=False),
    Column("logged_by", Uuid),
)

#: The columns of ``specimen`` this API may set on a create or an edit. Anything
#: absent here is another parts of the project's (pins are the maps module's, overrides arrive by
#: PATCH).
SPECIMEN_WRITABLE = frozenset(
    {
        "species_id",
        "nickname",
        "cultivar",
        "is_group",
        "count",
        "location_id",
        "is_outdoor",
        "in_container",
        "container_litres",
        "soil_note",
        "acquired_on",
        "provenance",
        "status",
        "water_k_c_override",
        "water_interval_days_override",
        "min_temp_c_override",
        "notes",
    }
)
