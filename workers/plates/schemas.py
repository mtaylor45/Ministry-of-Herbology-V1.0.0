"""Request and response shapes for the journal.

The contract fixes these in ``contracts/openapi/openapi.yaml`` and they are
built in exactly one place, so mock mode and live mode cannot drift.

Three notes:

* ``image_url`` is a URL, not a key. The database columns are ``image_key``
  and ``thumb_key`` and the volume is the operator's; the two are joined here
  and nowhere else. The path itself is not in the frozen contract — see the
  escalation in ``router.py``.
* ``FieldNote.written_by`` is a bare ``$ref`` to ``Member`` in the frozen
  contract, so ``null`` would be a violation — the same trap the design names
  for ``MapLayer.calibration``. A note whose author is unknown therefore
  **omits the key**, because `written_by` is not in `FieldNote`'s `required`
  list and an absent optional property is the contract-legal way to say "there
  isn't one". Serving `null` would have been the easy wrong answer.
* ``Plate`` carries no field for *why* a species has no plate, because the
  contract has nowhere to put one. That gap is escalated rather than invented
  around; see ``README.md``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .coverage import Coverage, Entry

#: Where a plate's bytes are served from. Not in the frozen contract; see the
#: escalation in ``router.py`` rather than treating this as settled.
IMAGE_URL_TEMPLATE = "/api/v1/journal/plates/{plate_id}/image"
THUMB_URL_TEMPLATE = "/api/v1/journal/plates/{plate_id}/image?variant=thumb"


class FieldNoteIn(BaseModel):
    """``POST /journal/{specimen_id}/notes``.

    The contract's body requires ``body`` and declares nothing else. ``member_id``
    is served **additively** — the design picks the member at write time, and the
    frozen body has no field for them, so a note written through the contract as
    frozen cannot record its author even though ``field_note.written_by`` exists
    to hold it. The scheduler hit the same shape and asked rather than
    reshaped; this does the same. A client that sends only ``body`` is
    unaffected, and the note's author is then absent rather than invented.
    """

    body: str
    member_id: str | None = None


def plate_out(row: dict[str, Any]) -> dict[str, Any]:
    """One ``Plate``, with its keys turned into URLs.

    ``license`` and ``attribution`` are passed through exactly as stored, which
    for a generated plate means both are ``null``. Nothing here fills them in
    with a style string or a model name: see ``domain.py``.
    """
    plate_id = str(row["id"])
    return {
        "id": plate_id,
        "species_id": _or_none(row.get("species_id")),
        "specimen_id": _or_none(row.get("specimen_id")),
        "image_url": IMAGE_URL_TEMPLATE.format(plate_id=plate_id),
        "thumb_url": (
            THUMB_URL_TEMPLATE.format(plate_id=plate_id)
            if row.get("thumb_key")
            else None
        ),
        "origin": row["origin"],
        "license": row.get("license"),
        "attribution": row.get("attribution"),
        "approved": bool(row.get("approved")),
        # Declared in 1.6.0. Null while nobody has approved it —
        # the domain object refuses to hold one without the other, so this is a
        # straight read rather than a derived value.
        "approved_by": _or_none(row.get("approved_by")),
    }


def note_out(row: dict[str, Any]) -> dict[str, Any]:
    """One ``FieldNote``. The author is omitted when unknown, never ``null``."""
    out: dict[str, Any] = {
        "id": str(row["id"]),
        "body": row["body"],
        "written_at": _isoformat(row["written_at"]),
    }
    member = row.get("member")
    if member:
        out["written_by"] = member_out(member)
    return out


def member_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "role": row["role"],
        "notify_prefs": row.get("notify_prefs") or {},
    }


def coverage_out(coverage: Coverage, generated: int) -> dict[str, Any]:
    """`PlateCoverage`: the five counts the book prints, and one entry per plant.

    The counts are computed from the entries rather than passed in beside them,
    so `total` cannot disagree with `len(specimens)` — which is the one thing a
    reader would never check and would always believe.
    """
    return {
        "total": coverage.total,
        "approved": coverage.approved,
        "waiting": coverage.waiting,
        "absent": coverage.absent,
        "generated": generated,
        "specimens": [entry_out(entry) for entry in coverage.entries],
    }


def entry_out(entry: Entry) -> dict[str, Any]:
    """One `PlateCoverageEntry`.

    `specimen` is a required bare `$ref` to `SpecimenBrief`, so it is always
    present — the design rule that the panel exists to name the plant. The
    four nullable fields are always *written*, null when they do not apply,
    because `PlateCoverageEntry` declares them nullable rather than optional.
    """
    specimen = entry.specimen
    return {
        "specimen": {
            "id": str(specimen["id"]),
            "display_name": specimen["display_name"],
            "is_outdoor": bool(specimen.get("is_outdoor")),
            "thumb_url": specimen.get("thumb_url") or specimen.get("primary_photo_url"),
        },
        "state": entry.state,
        "plate_id": entry.plate_id,
        "reason_kind": entry.absence.kind if entry.absence else None,
        "reason": entry.absence.reason if entry.absence else None,
    }


class ApprovalIn(BaseModel):
    """Who is approving. Not a contracted body — see ``router.py``.

    ``member_id`` is required and has no default. An approval with no approver
    is the one thing this field exists to prevent, so there is nothing to fall
    back to.
    """

    member_id: str = Field(min_length=1)


def _or_none(value: Any) -> str | None:
    return str(value) if value else None


def _isoformat(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
