"""The live Grounds, on Postgres.

Same protocol as the fixture store, so the router is unchanged between mock
and live mode. Two things are worth knowing before changing anything here.

**A pin is two columns of a specimen**, not a row of its own
(``contracts/schema/001_init.sql``). Placing one therefore updates parts of the project
The inventory API's table, and the update names ``map_layer_id`` and ``pin_px`` explicitly —
see :data:`grounds.tables.PIN_COLUMNS`. Both columns move together in one
statement, because a specimen that has a ``pin_px`` and no ``map_layer_id`` is
a pin on no map.

**The image lives on a volume, not in the database.** The row carries
``image_key``; the bytes are the operator's filesystem's problem and
``grounds.storage``'s. The two can get out of step — a database restored
without its volume is the obvious way — so the image route answers 404 with an
explanation rather than 500 with a traceback.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from grounds.repository import (
    PinOutsideLayerError,
    Record,
    UnknownLayerError,
    UnknownSpecimenError,
)
from grounds.tables import map_layer, site, species, specimen


class DatabaseRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------ reads

    async def list_layers(self, site_id: str | None = None) -> list[Record]:
        statement = select(map_layer).order_by(map_layer.c.ordinal, map_layer.c.name)
        if site_id:
            statement = statement.where(map_layer.c.site_id == _as_uuid(site_id))
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [_layer_record(row) for row in rows]

    async def get_layer(self, layer_id: str) -> Record | None:
        parsed = _as_uuid_or_none(layer_id)
        if parsed is None:
            return None
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(map_layer).where(map_layer.c.id == parsed)
                    )
                )
                .mappings()
                .first()
            )
        return _layer_record(row) if row else None

    async def list_pins(self, layer_id: str | None = None) -> list[Record]:
        statement = (
            select(
                specimen.c.id,
                specimen.c.nickname,
                specimen.c.map_layer_id,
                specimen.c.pin_px,
                specimen.c.is_outdoor,
                species.c.accepted_name,
                species.c.common_names,
            )
            .select_from(
                specimen.outerjoin(species, specimen.c.species_id == species.c.id)
            )
            .where(specimen.c.map_layer_id.isnot(None))
            .where(specimen.c.pin_px.isnot(None))
            .where(specimen.c.archived_at.is_(None))
            .order_by(specimen.c.id)
        )
        if layer_id:
            parsed = _as_uuid_or_none(layer_id)
            if parsed is None:
                return []
            statement = statement.where(specimen.c.map_layer_id == parsed)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [
            {
                "specimen_id": str(row["id"]),
                "layer_id": str(row["map_layer_id"]),
                "px": _pixel(row["pin_px"]),
                "specimen": _brief(row),
            }
            for row in rows
        ]

    async def default_site_id(self) -> str | None:
        async with self._engine.connect() as connection:
            found = await connection.scalar(
                select(site.c.id).order_by(site.c.created_at, site.c.id).limit(1)
            )
        return str(found) if found else None

    # ----------------------------------------------------------------- writes

    async def create_layer(self, data: dict[str, Any]) -> Record:
        layer_id = _as_uuid(data.get("id") or str(uuid.uuid4()))
        async with self._engine.begin() as connection:
            ordinal = data.get("ordinal")
            if ordinal is None:
                ordinal = await self._next_ordinal(connection, data["site_id"])
            values = {
                "id": layer_id,
                "site_id": _as_uuid(data["site_id"]),
                "name": data["name"],
                "kind": data["kind"],
                "image_key": data["image_key"],
                "image_width_px": int(data["image_width_px"]),
                "image_height_px": int(data["image_height_px"]),
                "scale_mm_per_px": data.get("scale_mm_per_px"),
                "calibration": data.get("calibration")
                or {"scale_mm_per_px": None, "points": []},
                "ordinal": int(ordinal),
            }
            row = (
                (
                    await connection.execute(
                        map_layer.insert().values(**values).returning(map_layer)
                    )
                )
                .mappings()
                .one()
            )
        return _layer_record(row)

    async def set_calibration(
        self, layer_id: str, calibration: dict[str, Any]
    ) -> Record | None:
        parsed = _as_uuid_or_none(layer_id)
        if parsed is None:
            return None
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        map_layer.update()
                        .where(map_layer.c.id == parsed)
                        .values(
                            calibration=calibration,
                            scale_mm_per_px=calibration.get("scale_mm_per_px"),
                        )
                        .returning(map_layer)
                    )
                )
                .mappings()
                .first()
            )
        return _layer_record(row) if row else None

    async def set_pin(
        self, specimen_id: str, layer_id: str, px: dict[str, float] | None
    ) -> Record:
        parsed_specimen = _as_uuid_or_none(specimen_id)
        if parsed_specimen is None:
            raise UnknownSpecimenError(specimen_id)
        parsed_layer = _as_uuid_or_none(layer_id)
        if parsed_layer is None:
            raise UnknownLayerError(layer_id)

        async with self._engine.begin() as connection:
            layer = (
                (
                    await connection.execute(
                        select(map_layer).where(map_layer.c.id == parsed_layer)
                    )
                )
                .mappings()
                .first()
            )
            if layer is None:
                raise UnknownLayerError(layer_id)
            if px is not None:
                x, y = float(px["x"]), float(px["y"])
                if not (
                    0 <= x <= layer["image_width_px"]
                    and 0 <= y <= layer["image_height_px"]
                ):
                    raise PinOutsideLayerError(
                        x, y, layer["image_width_px"], layer["image_height_px"]
                    )

            # Both columns in one statement: a `pin_px` with no `map_layer_id`
            # is a pin on no map, and a half-applied move would be exactly that.
            result = await connection.execute(
                update(specimen)
                .where(specimen.c.id == parsed_specimen)
                .values(
                    map_layer_id=parsed_layer if px is not None else None,
                    pin_px=({"x": float(px["x"]), "y": float(px["y"])} if px else None),
                )
                .returning(specimen.c.id, specimen.c.pin_px, specimen.c.map_layer_id)
            )
            written = result.mappings().first()
            if written is None:
                raise UnknownSpecimenError(specimen_id)

            brief_row = (
                (
                    await connection.execute(
                        select(
                            specimen.c.id,
                            specimen.c.nickname,
                            specimen.c.is_outdoor,
                            species.c.accepted_name,
                            species.c.common_names,
                        )
                        .select_from(
                            specimen.outerjoin(
                                species, specimen.c.species_id == species.c.id
                            )
                        )
                        .where(specimen.c.id == parsed_specimen)
                    )
                )
                .mappings()
                .one()
            )

        return {
            "specimen_id": specimen_id,
            "layer_id": layer_id,
            "px": _pixel(written["pin_px"]),
            "specimen": _brief(brief_row),
        }

    async def _next_ordinal(self, connection: AsyncConnection, site_id: str) -> int:
        highest = await connection.scalar(
            select(map_layer.c.ordinal)
            .where(map_layer.c.site_id == _as_uuid(site_id))
            .order_by(map_layer.c.ordinal.desc())
            .limit(1)
        )
        return 0 if highest is None else int(highest) + 1


# ------------------------------------------------------------------ helpers


def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _as_uuid_or_none(value: Any) -> uuid.UUID | None:
    """A malformed id is a miss, not a 500: the router turns `None` into a 404."""
    try:
        return _as_uuid(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _pixel(stored: Any) -> dict[str, float] | None:
    if not isinstance(stored, dict) or "x" not in stored or "y" not in stored:
        return None
    return {"x": float(stored["x"]), "y": float(stored["y"])}


def _layer_record(row: Any) -> Record:
    calibration = row["calibration"]
    # `calibration` defaults to `'[]'::jsonb` in the schema, which is a list,
    # not the object `Calibration` describes. Normalise on the way out rather
    # than serving a list where the contract declares an object.
    if not isinstance(calibration, dict):
        calibration = {"scale_mm_per_px": None, "points": list(calibration or [])}
    return {
        "id": str(row["id"]),
        "site_id": str(row["site_id"]),
        "name": row["name"],
        "kind": row["kind"],
        "image_key": row["image_key"],
        "image_width_px": int(row["image_width_px"]),
        "image_height_px": int(row["image_height_px"]),
        "scale_mm_per_px": row["scale_mm_per_px"],
        "calibration": calibration,
        "ordinal": int(row["ordinal"]),
    }


def _brief(row: Any) -> dict[str, Any]:
    """Nickname, else the species' first common name, else the accepted name.

    The same rule as ``app.fixtures.display_name``, applied to a database row.
    """
    common = list(row["common_names"] or [])
    if row["nickname"]:
        name = str(row["nickname"])
    elif common:
        name = str(common[0]).capitalize()
    elif row["accepted_name"]:
        name = str(row["accepted_name"])
    else:
        name = "Unnamed specimen"
    return {
        "id": str(row["id"]),
        "display_name": name,
        "is_outdoor": bool(row["is_outdoor"]),
        "thumb_url": None,
    }
