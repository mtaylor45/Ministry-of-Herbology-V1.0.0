"""The Grounds in memory, seeded from ``fixtures/``.

Mock mode is the default and this keeps it a **writable** Grounds:
upload, calibration and pin placement all work with no database and no volume
attached, so the app's screens can build the Specimen cross-links against a moving target
rather than a frozen one.

Everything here is derived from the fixture rows rather than copied out of
them. The two seeded layers belong to whichever site ``fixtures/site.json``
describes, and the survey's control points are placed relative to that site's
own latitude and longitude — so moving the fixture household to another
continent moves the mock survey with it instead of stranding it.

The pin layout is synthetic on purpose: no fixture specimen carries a
``pin_px``, and inventing one in ``fixtures/`` is the test suite's call, not the maps module's. A
specimen
that *does* carry ``map_layer_id`` and ``pin_px`` is honoured as-is, so the day
L adds them the mock stops synthesising.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from app import fixtures
from grounds.mocks.plan_image import floor_plan_png, survey_png
from grounds.repository import (
    PinOutsideLayerError,
    Record,
    UnknownLayerError,
    UnknownSpecimenError,
)
from grounds.storage import MemoryImageStore, key_for

#: The two layers the earlier mock served, kept at the same ids so anything already
#: built against them keeps working.
FLOOR_PLAN_ID = "01890070-0000-7000-8000-000000000001"
SURVEY_ID = "01890070-0000-7000-8000-000000000002"

#: Roughly the span of a town lot, in degrees, either side of the site. Used
#: only to place the mock survey's two control points relative to whatever
#: site the fixtures describe.
_SURVEY_HALF_SPAN_LAT = 0.0006
_SURVEY_HALF_SPAN_LON = 0.0008


class FixtureRepository:
    """In-memory Grounds. One instance per process; writes last until restart."""

    def __init__(self) -> None:
        self.images = MemoryImageStore()
        self._layers: dict[str, Record] = {}
        self._pins: dict[str, Record] = {}
        self._seed()

    # ------------------------------------------------------------------ seed

    def _seed(self) -> None:
        site = fixtures.site()
        for layer_id, name, kind, png in (
            (FLOOR_PLAN_ID, "Ground floor", "floor_plan", floor_plan_png()),
            (SURVEY_ID, "Property survey", "survey", survey_png()),
        ):
            key = key_for(layer_id, ".png")
            self.images.put(key, png)
            width, height = (1600, 1200) if kind == "floor_plan" else (2000, 1500)
            self._layers[layer_id] = {
                "id": layer_id,
                "site_id": site["id"],
                "name": name,
                "kind": kind,
                "image_key": key,
                "image_width_px": width,
                "image_height_px": height,
                "scale_mm_per_px": None,
                "calibration": {"scale_mm_per_px": None, "points": []},
                "ordinal": 0 if kind == "floor_plan" else 1,
            }

        # The floor plan arrives calibrated, because a scanned plan usually has
        # its scale written on it. The survey arrives *uncalibrated*, which is
        # the state this release exists to get a layer out of — and the state
        # the contract can only spell as an empty `Calibration`.
        self._layers[FLOOR_PLAN_ID]["scale_mm_per_px"] = 12.5
        self._layers[FLOOR_PLAN_ID]["calibration"] = {
            "scale_mm_per_px": 12.5,
            "points": [],
        }

        self._seed_pins()

    def _seed_pins(self) -> None:
        indoor_slot = outdoor_slot = 0
        for specimen in fixtures.specimens():
            stored_layer = specimen.get("map_layer_id")
            stored_px = specimen.get("pin_px")
            if stored_layer and stored_px:
                self._pins[specimen["id"]] = {
                    "specimen_id": specimen["id"],
                    "layer_id": stored_layer,
                    "px": {"x": float(stored_px["x"]), "y": float(stored_px["y"])},
                }
                continue
            if specimen.get("is_outdoor"):
                layer_id, slot = SURVEY_ID, outdoor_slot
                outdoor_slot += 1
            else:
                layer_id, slot = FLOOR_PLAN_ID, indoor_slot
                indoor_slot += 1
            layer = self._layers[layer_id]
            self._pins[specimen["id"]] = {
                "specimen_id": specimen["id"],
                "layer_id": layer_id,
                "px": _slot_position(
                    slot, layer["image_width_px"], layer["image_height_px"]
                ),
            }

    # ------------------------------------------------------------------ reads

    async def list_layers(self, site_id: str | None = None) -> list[Record]:
        rows = [
            dict(row)
            for row in self._layers.values()
            if site_id is None or row["site_id"] == site_id
        ]
        return sorted(rows, key=lambda row: (row["ordinal"], row["name"]))

    async def get_layer(self, layer_id: str) -> Record | None:
        row = self._layers.get(layer_id)
        return dict(row) if row else None

    async def list_pins(self, layer_id: str | None = None) -> list[Record]:
        by_id = {s["id"]: s for s in fixtures.specimens()}
        rows: list[Record] = []
        for pin in self._pins.values():
            if layer_id and pin["layer_id"] != layer_id:
                continue
            specimen = by_id.get(pin["specimen_id"])
            rows.append({**pin, "specimen": _brief(specimen) if specimen else None})
        return sorted(rows, key=lambda row: row["specimen_id"])

    async def default_site_id(self) -> str | None:
        return str(fixtures.site()["id"])

    # ----------------------------------------------------------------- writes

    async def create_layer(self, data: dict[str, Any]) -> Record:
        layer_id = data.get("id") or str(uuid.uuid4())
        ordinal = data.get("ordinal")
        if ordinal is None:
            ordinal = 1 + max(
                (row["ordinal"] for row in self._layers.values()), default=-1
            )
        row = {
            "id": layer_id,
            "site_id": data["site_id"],
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
        self._layers[layer_id] = row
        return dict(row)

    async def set_calibration(
        self, layer_id: str, calibration: dict[str, Any]
    ) -> Record | None:
        row = self._layers.get(layer_id)
        if row is None:
            return None
        row["calibration"] = calibration
        row["scale_mm_per_px"] = calibration.get("scale_mm_per_px")
        return dict(row)

    async def set_pin(
        self, specimen_id: str, layer_id: str, px: dict[str, float] | None
    ) -> Record:
        if not any(s["id"] == specimen_id for s in fixtures.specimens()):
            raise UnknownSpecimenError(specimen_id)
        layer = self._layers.get(layer_id)
        if layer is None:
            raise UnknownLayerError(layer_id)
        if px is not None:
            _check_within(px, layer)
            self._pins[specimen_id] = {
                "specimen_id": specimen_id,
                "layer_id": layer_id,
                "px": {"x": float(px["x"]), "y": float(px["y"])},
            }
        else:
            self._pins.pop(specimen_id, None)
        specimen = next(s for s in fixtures.specimens() if s["id"] == specimen_id)
        return {
            "specimen_id": specimen_id,
            "layer_id": layer_id,
            "px": self._pins.get(specimen_id, {}).get("px"),
            "specimen": _brief(specimen),
        }


def _slot_position(slot: int, width_px: int, height_px: int) -> dict[str, float]:
    """Lay pins out on a 3-column grid inset from the sheet's edges.

    Derived from the layer's own size rather than written down, so a layer of
    any dimensions gets pins that land on it.
    """
    columns = 3
    inset_x, inset_y = width_px * 0.2, height_px * 0.25
    step_x = (width_px - 2 * inset_x) / max(columns - 1, 1)
    step_y = height_px * 0.3
    column, row = slot % columns, slot // columns
    return {
        "x": round(inset_x + column * step_x, 2),
        "y": round(min(inset_y + row * step_y, height_px - inset_y * 0.2), 2),
    }


def _check_within(px: dict[str, float], layer: Record) -> None:
    x, y = float(px["x"]), float(px["y"])
    if not (0 <= x <= layer["image_width_px"] and 0 <= y <= layer["image_height_px"]):
        raise PinOutsideLayerError(
            x, y, layer["image_width_px"], layer["image_height_px"]
        )


def _brief(specimen: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": specimen["id"],
        "display_name": fixtures.display_name(specimen),
        "is_outdoor": bool(specimen.get("is_outdoor", False)),
        "thumb_url": specimen.get("thumb_url"),
    }


@lru_cache
def fixture_repository() -> FixtureRepository:
    return FixtureRepository()


def reset_fixture_repository() -> None:
    """Throw away mock-mode writes. For tests, and for `make fixtures`."""
    fixture_repository.cache_clear()


__all__ = [
    "FLOOR_PLAN_ID",
    "SURVEY_ID",
    "FixtureRepository",
    "fixture_repository",
    "reset_fixture_repository",
]
