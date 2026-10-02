"""The journal every other parts of the project runs against.

The app's screens owns the Specimen page and is not running this release, so this mock exists so
that the app's screens is never blocked: the three contracted routes answer with fixture-shaped
data, plates have real image bytes behind them, notes can be written, and
plates can be approved.

## How the mock decides what has a plate

Nothing here is hard-coded out of `fixtures/`. The species are read
from `fixtures/species/species.json`, sorted by accepted name, and **every
outcome gets a turn in order**: two sourced, one generated, one where a
candidate was found with no usable licence, one where nothing was found, and
round again. That is arbitrary — mock mode is not a claim about what BHL
happens to hold — but it is arbitrary *on purpose and deterministically*, and
it guarantees that each state the book view has to render actually occurs. A
mock where everything has a plate would let the three states that matter most
ship untested.

## What these plates are allowed to say about themselves

The images are drawn by `mocks/plate_image.py`, so a plate in mock mode is a
schematic and not a scan. The attribution on a "sourced" mock plate says so, in
the words the reader sees: **nothing in mock mode names a real work, a real
library or a real lithographer.** A stand-in image under a real credit would be
precisely the fabricated artefact this release is about, and it would be worse
for being in our own fixtures rather than someone's model.

## Two states mock mode shows on purpose

* **A generated plate.** A fresh deployment cannot generate — no credential —
  so without this the "drawn, not collected" label would be unbuildable and
  unreviewable by hand. Mock mode therefore shows the state of a deployment
  whose operator *did* configure a generator. It is a state the default
  deployment cannot reach, which is fine; what would not be fine is reporting
  it as the default. See `README.md` for the real coverage figures.
* **Approvals, by a named fixture member.** They stand for a keeper having
  already looked at those plates. Deliberately partial: some plates with no
  approval, so "awaiting approval" is a state the book view must render rather
  than one nobody ever sees.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.fixtures import display_name as fixture_display_name
from app.fixtures import species as fixture_species
from app.fixtures import specimens as fixture_specimens
from app.settings import get_settings

from .coverage import Absence, Coverage, build, generated_count
from .domain import Plate
from .mocks.plate_image import plate_png, seed_for, thumb_png
from .repository import (
    EmptyNoteError,
    Record,
    UnknownMemberError,
    UnknownPlateError,
    UnknownSpecimenError,
)
from .storage import MemoryPlateStore, key_for
from .style import HOUSE_STYLE

#: The rotation described in the module docstring. Index into it with the
#: species' position in name order.
OUTCOMES = ("sourced", "sourced", "generated", "unlicensed", "nothing")

#: What a mock "sourced" plate credits. It credits the mock.
MOCK_ATTRIBUTION = (
    "Mock mode: a drawn stand-in, not a scanned plate. No historical work, "
    "library or artist is depicted or credited."
)

#: Why the species with no plate have none, as a contract `reason_kind` and the
#: sentence that goes with it. The rotation's two no-plate
#: outcomes map onto two of the closed set's kinds; the other four are
#: reachable only in a live deployment, which is the honest shape — mock mode
#: should not manufacture a full-volume error it never had.
NO_PLATE_REASONS: dict[str, tuple[str, str]] = {
    "unlicensed": (
        "unlicensed_candidate",
        (
            "A catalogue offered an illustration and stated no licence for it, "
            "so recording it as public domain would have been an unsupported "
            "claim. It was discarded rather than relabelled."
        ),
    ),
    "nothing": (
        "generation_unavailable",
        (
            "No public-domain catalogue this deployment asked had a plate of "
            "this species, and no image generator is configured, so it has none."
        ),
    ),
}


def _members() -> list[Record]:
    """Read the household from `fixtures/`.

    ``app.fixtures`` has no members accessor — it belongs to the inventory API's
    half of that module — so this reads the file through the same configured
    fixtures directory rather than hard-coding a member id.
    """
    path: Path = get_settings().fixtures_dir / "members" / "members.json"
    try:
        with path.open() as handle:
            rows: list[Record] = json.load(handle)
    except (OSError, json.JSONDecodeError):  # pragma: no cover - fixtures ship
        return []
    return rows


@lru_cache
def fixture_repository() -> FixtureRepository:
    """One instance per process, so a written note survives the next request."""
    return FixtureRepository()


class FixtureRepository:
    """An in-memory journal. Ordering is fixture order, then order of arrival."""

    def __init__(self) -> None:
        # Deep copies: ``app.fixtures`` caches the parsed JSON, and a mock that
        # mutated it would rewrite the fixture data for every other reader.
        self._species: list[Record] = copy.deepcopy(fixture_species())
        self._specimens: list[Record] = copy.deepcopy(fixture_specimens())
        self._members: list[Record] = copy.deepcopy(_members())
        self._images = MemoryPlateStore()
        self._plates: list[Record] = []
        self._notes: list[Record] = []
        self._absences: dict[str, Absence] = {}
        self._seed_plates()
        self._seed_notes()

    # ---------------------------------------------------------------- seeding

    def _approver(self) -> Record | None:
        """The member a mock approval is attributed to: the first in fixtures."""
        return self._members[0] if self._members else None

    def _seed_plates(self) -> None:
        approver = self._approver()
        in_name_order = sorted(self._species, key=lambda row: row["accepted_name"])
        for index, species in enumerate(in_name_order):
            outcome = OUTCOMES[index % len(OUTCOMES)]
            if outcome in NO_PLATE_REASONS:
                kind, reason = NO_PLATE_REASONS[outcome]
                self._absences[str(species["id"])] = Absence(kind=kind, reason=reason)
                continue
            plate = self._draw(species, generated=outcome == "generated")
            # Alternate approvals so "awaiting approval" is a real state.
            if approver and index % 2 == 0:
                plate = plate.approve(str(approver["id"]))
            self._plates.append(self._row(plate))

    def _draw(self, species: Record, *, generated: bool) -> Plate:
        """Build one mock plate, bytes and all, through the real invariants."""
        plate_id = str(uuid.uuid4())
        seed = seed_for(str(species["accepted_name"]))
        image_key = key_for(plate_id, ".png")
        thumb_key = key_for(plate_id, ".png", thumb=True)
        self._images.put(image_key, plate_png(seed))
        self._images.put(thumb_key, thumb_png(seed))
        if generated:
            # No licence, no attribution, no source. `Plate` enforces it.
            return Plate(
                id=plate_id,
                origin="generated",
                image_key=image_key,
                thumb_key=thumb_key,
                species_id=str(species["id"]),
                style=HOUSE_STYLE,
            )
        return Plate(
            id=plate_id,
            origin="public_domain",
            image_key=image_key,
            thumb_key=thumb_key,
            species_id=str(species["id"]),
            license="public domain",
            attribution=MOCK_ATTRIBUTION,
        )

    def _seed_notes(self) -> None:
        """A couple of notes, so the facet has something to page through.

        Attributed to a fixture member: a note that cannot say who wrote it is
        a worse record, and `field_note.written_by` exists to say.
        """
        author = self._approver()
        if not author or not self._specimens:
            return  # pragma: no cover - fixtures ship both
        first = self._specimens[0]
        written = datetime.now(UTC) - timedelta(days=3)
        self._notes.append(
            {
                "id": str(uuid.uuid4()),
                "specimen_id": str(first["id"]),
                "body": (
                    "New leaf unfurling on the north side; the aerial root has "
                    "found the moss pole."
                ),
                "written_at": written,
                "written_by": str(author["id"]),
            }
        )

    def _row(self, plate: Plate) -> Record:
        return {
            "id": plate.id,
            "species_id": plate.species_id,
            "specimen_id": plate.specimen_id,
            "image_key": plate.image_key,
            "thumb_key": plate.thumb_key,
            "origin": plate.origin,
            "source_id": plate.source_id,
            "license": plate.license,
            "attribution": plate.attribution,
            "style": plate.style,
            "approved": plate.approved,
            "approved_by": plate.approved_by,
            "created_at": datetime.now(UTC),
        }

    def _plate_row(self, plate_id: str) -> Record:
        row = next((p for p in self._plates if p["id"] == str(plate_id)), None)
        if row is None:
            raise UnknownPlateError(plate_id)
        return row

    # ------------------------------------------------------------------ reads

    async def list_plates(self, approved: bool | None = None) -> list[Record]:
        rows = [dict(p) for p in self._plates]
        if approved is None:
            return rows
        return [row for row in rows if bool(row["approved"]) is approved]

    async def get_plate(self, plate_id: str) -> Record | None:
        return next(
            (dict(p) for p in self._plates if p["id"] == str(plate_id)),
            None,
        )

    async def plate_image(self, plate_id: str, *, thumb: bool = False) -> bytes:
        row = self._plate_row(plate_id)
        key = row["thumb_key"] if thumb else row["image_key"]
        if not key:
            key = row["image_key"]
        return self._images.get(str(key))

    async def list_notes(self, specimen_id: str) -> list[Record]:
        if not self._specimen(specimen_id):
            raise UnknownSpecimenError(specimen_id)
        notes = [n for n in self._notes if n["specimen_id"] == str(specimen_id)]
        return [self._note_with_author(n) for n in sorted(notes, key=_written_at)]

    def member(self, member_id: str | None) -> Record | None:
        if not member_id:
            return None
        return next(
            (dict(m) for m in self._members if str(m["id"]) == str(member_id)), None
        )

    def absence_reason(self, species_id: str) -> Absence | None:
        """Why this species has no plate, with its contract `reason_kind`."""
        return self._absences.get(str(species_id))

    def _absence_for(self, specimen: Record) -> Absence:
        """The absence the coverage route reports for one plant.

        A specimen whose *species* the rotation gave a reason inherits it. A
        specimen with no species recorded at all cannot have been sourced for,
        so `not_run` is the truthful kind rather than a borrowed sentence.
        """
        species = specimen.get("species_id")
        recorded = self._absences.get(str(species)) if species else None
        if recorded is not None:
            return recorded
        return Absence(
            kind="not_run",
            reason=(
                "No species is recorded for this plant, so no catalogue has "
                "been asked about it."
            ),
        )

    def _named(self) -> list[Record]:
        """Fixture rows with `display_name` resolved.

        `SpecimenBrief.display_name` is required, and a fixture row carries a
        `nickname` that may be absent. The inventory API's rule — nickname, else the species'
        first common name, else the accepted name — lives in `app.fixtures`,
        and is reused rather than restated so the Register and the journal
        cannot call the same plant two different things.
        """
        return [
            {**row, "display_name": fixture_display_name(row)}
            for row in self._specimens
        ]

    async def coverage(self) -> Coverage:
        """One entry per specimen, in register order."""
        return build(self._named(), self._plates, self._absence_for)

    async def generated_for_report(self) -> int:
        return generated_count(self._specimens, self._plates)

    def _specimen(self, specimen_id: str) -> Record | None:
        return next(
            (s for s in self._specimens if str(s["id"]) == str(specimen_id)), None
        )

    def _note_with_author(self, note: Record) -> Record:
        out = dict(note)
        out["member"] = self.member(note.get("written_by"))
        return out

    # ----------------------------------------------------------------- writes

    async def create_plate(self, plate: Plate) -> Record:
        row = self._row(plate)
        self._plates.append(row)
        return dict(row)

    async def approve_plate(self, plate_id: str, member_id: str) -> Record:
        """The maintainers named member accepts this plate. The only way `approved` goes true."""
        row = self._plate_row(plate_id)
        if self.member(member_id) is None:
            raise UnknownMemberError(member_id)
        row["approved"] = True
        row["approved_by"] = str(member_id)
        return dict(row)

    async def create_note(
        self, specimen_id: str, body: str, member_id: str | None = None
    ) -> Record:
        if not self._specimen(specimen_id):
            raise UnknownSpecimenError(specimen_id)
        if not body or not body.strip():
            raise EmptyNoteError(
                "A field note is somebody's observation, and an empty one is a "
                "row implying an observation nobody made."
            )
        if member_id is not None and self.member(member_id) is None:
            raise UnknownMemberError(member_id)
        note = {
            "id": str(uuid.uuid4()),
            "specimen_id": str(specimen_id),
            "body": body.strip(),
            "written_at": datetime.now(UTC),
            "written_by": str(member_id) if member_id else None,
        }
        self._notes.append(note)
        return self._note_with_author(note)


def _written_at(note: Record) -> Any:
    return note["written_at"]


def reset_fixture_repository() -> None:
    """Throw away mock-mode writes. For tests, and for `make fixtures`."""
    fixture_repository.cache_clear()
