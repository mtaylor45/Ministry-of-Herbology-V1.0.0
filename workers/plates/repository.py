"""The storage seam for plates and field notes.

Two implementations answer the same protocol, as everywhere else in this API:
``FixtureRepository`` keeps the journal in memory, seeded from ``fixtures/``
(``MOH_MOCK_MODE=true``, how every other parts of the project runs the stack), and
``DatabaseRepository`` talks to Postgres. The router knows only this interface.

## `approve` is a repository operation, and that is the point

The protocol below has ``approve_plate(plate_id, member_id)`` and no way to set
``approved`` any other way. ``create_plate`` takes a :class:`~.domain.Plate`,
which refuses to exist in an approved state without an approver, so there is no
path from "the pipeline made a plate" to "the plate is approved" — not through
this seam, and not through the row.

**What `approved` means, and who does it.** A plate is approved when a named
member has looked at it and accepted it as this plant's portrait. It is a
*person vouching for a likeness*, which is the only thing the field could mean
that is worth storing: a pipeline can tell you an image is licensed and of the
right species name, and cannot tell you it is a good picture of your plant, or
that it is the right cultivar, or that it is a photograph of a different plant
somebody mislabelled in 1890. If the pipeline set the flag, the column would
record "a program fetched this", which `origin` and `license` already say
better.

So the pipeline writes `approved: false` always, and this seam is where a
member's decision lands. That makes the earlier exit criterion — *"each specimen has
an approved plate"* — partly a human task by construction, and the honest
reading is that the releases delivers *approvable* plates and the approvals that
mock mode's fixtures record. See `README.md` for the escalation this forces:
**the frozen contract declares no endpoint that approves a plate.**
"""

from __future__ import annotations

from typing import Any, Protocol

from app.settings import get_settings

from .coverage import Coverage
from .domain import Plate

Record = dict[str, Any]


class UnknownPlateError(LookupError):
    """A write or a read named a plate that does not exist. The router answers 404."""

    def __init__(self, plate_id: Any) -> None:
        super().__init__(f"No such plate: {plate_id}")
        self.plate_id = str(plate_id)


class UnknownSpecimenError(LookupError):
    """A note named a specimen nothing matches. The router answers 404."""

    def __init__(self, specimen_id: Any) -> None:
        super().__init__(f"No such specimen: {specimen_id}")
        self.specimen_id = str(specimen_id)


class UnknownMemberError(LookupError):
    """An approval or a note named a member nothing matches. The router answers 422."""

    def __init__(self, member_id: Any) -> None:
        super().__init__(f"No such member: {member_id}")
        self.member_id = str(member_id)


class EmptyNoteError(ValueError):
    """A field note with nothing in it. The router answers 422.

    A note is somebody's observation. An empty one is a row that implies an
    observation was made, which is the small version of the thing this project
    keeps refusing to do.
    """


class JournalRepository(Protocol):
    """Everything the journal router needs from storage."""

    async def list_plates(self, approved: bool | None = None) -> list[Record]: ...

    async def get_plate(self, plate_id: str) -> Record | None: ...

    async def create_plate(self, plate: Plate) -> Record: ...

    async def approve_plate(self, plate_id: str, member_id: str) -> Record: ...

    async def plate_image(self, plate_id: str, *, thumb: bool = False) -> bytes: ...

    async def list_notes(self, specimen_id: str) -> list[Record]: ...

    async def create_note(
        self, specimen_id: str, body: str, member_id: str | None = None
    ) -> Record: ...

    async def coverage(self) -> Coverage: ...

    async def generated_for_report(self) -> int: ...


async def get_repository() -> JournalRepository:
    """FastAPI dependency: fixtures when mocking, Postgres when not.

    Mock mode stays a *writable* journal — notes can be written and plates
    approved — so the app's screens can build the Specimen journal facet and the demo can be
    driven end to end before anyone attaches a database.
    """
    if get_settings().mock_mode:
        from .fixture_repository import fixture_repository

        return fixture_repository()

    from .database_repository import DatabaseRepository
    from .db import get_engine

    return DatabaseRepository(get_engine())
