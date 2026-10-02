"""Request and response shapes for the Grounds.

The contract fixes these in ``contracts/openapi/openapi.yaml`` and they are
built in exactly one place, so mock mode and live mode cannot drift.

Two notes on ``MapLayer.calibration``:

* It is a bare ``$ref`` in the frozen contract, so ``null`` would be a
  violation. An uncalibrated layer therefore serves an **empty**
  ``Calibration`` — ``{"scale_mm_per_px": null, "points": []}`` — which the
  schema permits because ``Calibration`` declares nothing required. That is
  the state this API serves from the moment a layer is uploaded until somebody
  calibrates it, and `grounds.domain.is_calibrated` is how anything decides
  which it is looking at.
* ``image_url`` is a URL, not a key. The database column is ``image_key`` and
  the volume is the operator's; the two are joined here and nowhere else.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Where an uploaded layer's bytes are served from. See the note in
#: ``grounds.router`` — this path is not in the frozen contract and is
#: escalated to the maintainers rather than invented quietly.
IMAGE_URL_TEMPLATE = "/api/v1/grounds/layers/{layer_id}/image"


class PixelPoint(BaseModel):
    x: float
    y: float


class CalibrationPoint(BaseModel):
    px: list[float] = Field(min_length=2, max_length=2)
    world: list[float] = Field(min_length=2, max_length=2)


class CalibrationIn(BaseModel):
    """``PUT /grounds/layers/{id}/calibration``.

    Deliberately loose here and strict in ``grounds.domain``: which half of
    this schema applies depends on the layer's ``kind``, which the body does
    not carry, so the cross-field rule cannot live in the model.
    """

    scale_mm_per_px: float | None = None
    points: list[CalibrationPoint] | None = None


class PinIn(BaseModel):
    """``PUT /grounds/pins``. ``px: null`` lifts a pin off the map."""

    specimen_id: str
    layer_id: str
    px: PixelPoint | None = None


def calibration_out(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The always-an-object encoding of "calibrated" and "not yet"."""
    stored = stored or {}
    return {
        "scale_mm_per_px": stored.get("scale_mm_per_px"),
        "points": list(stored.get("points") or []),
    }


def layer_out(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "site_id": record["site_id"],
        "name": record["name"],
        "kind": record["kind"],
        "image_url": record.get("image_url")
        or IMAGE_URL_TEMPLATE.format(layer_id=record["id"]),
        "image_width_px": record["image_width_px"],
        "image_height_px": record["image_height_px"],
        "scale_mm_per_px": record.get("scale_mm_per_px"),
        "calibration": calibration_out(record.get("calibration")),
        "ordinal": record.get("ordinal", 0),
    }


def pin_out(record: dict[str, Any]) -> dict[str, Any]:
    px = record.get("px")
    return {
        "specimen_id": record["specimen_id"],
        "layer_id": record["layer_id"],
        "px": None if px is None else {"x": px["x"], "y": px["y"]},
        "specimen": record.get("specimen"),
    }
