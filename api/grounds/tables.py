"""SQLAlchemy Core tables for the grounds subset of the frozen schema.

These mirror ``contracts/schema/001_init.sql`` and never create it — migrations
are forward-only SQL owned by the maintainers. The definitions stay narrow (the
columns this API reads or writes), so a schema change that matters shows up
here as a mismatch rather than as silence.

``specimen`` is the inventory API's table. Grounds reads three of its columns and
writes exactly two — ``map_layer_id`` and ``pin_px`` — because that is where
the schema puts a pin. Everything else on it is the inventory API's, and the write below names
its two columns explicitly rather than updating a dict, so a pin can never
carry an unrelated field along with it.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
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

#: Read-only here: a layer uploaded without a `site_id` is attached to the
#: household's site, and there is one.
site = Table(
    "site",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

map_layer = Table(
    "map_layer",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("site_id", Uuid, nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    # The object key on the operator's volume, not a URL. `grounds.schemas`
    # is the only place the two are joined.
    Column("image_key", Text, nullable=False),
    Column("image_width_px", Integer, nullable=False),
    Column("image_height_px", Integer, nullable=False),
    Column("scale_mm_per_px", Float),
    Column("calibration", JSONB, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

#: The inventory API's. Read for the pin's `SpecimenBrief`; written only in the two
#: columns named in :data:`PIN_COLUMNS`.
specimen = Table(
    "specimen",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("species_id", Uuid),
    Column("nickname", Text),
    Column("map_layer_id", Uuid),
    Column("pin_px", JSONB),
    Column("is_outdoor", Boolean, nullable=False),
    Column("archived_at", DateTime(timezone=True)),
)

#: The botany worker's. Read to build a display name when a specimen has no nickname.
species = Table(
    "species",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("accepted_name", Text, nullable=False),
    Column("common_names", ARRAY(Text), nullable=False),
)

#: The only columns of `specimen` the grounds API writes. Named, not inferred.
PIN_COLUMNS = ("map_layer_id", "pin_px")
