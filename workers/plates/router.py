"""The Naturalist's Journal: plates and field notes.

``web/src/routes/journal/`` README and gives the app's screens' Specimen page something other
than a 404 to link to. The handlers are thin; the work is in
``workers.plates.domain`` (what a plate may claim), ``workers.plates.pipeline``
(what becomes a plate and what becomes a named absence) and
``workers.plates.repository`` (fixtures in mock mode, Postgres when a database
is attached).

This router lives under ``workers/`` and is mounted by the API image, which
puts ``workers`` on ``PYTHONPATH`` alongside ``api``. That is
The botany worker's arrangement for ``workers/botany/router.py``, reused rather than
reinvented — the contract gives ``/journal/*`` to the journal, and the journal's owned directory is
``workers/plates/``.

## Two routes that joined the contract in 1.6.0

``GET /journal/plates/{plate_id}/image`` and ``POST /journal/plates/{plate_id}/approve``
were served ahead of the contract, declared in
``tests/contract/test_api_matches_spec.py``'s ``UNDOCUMENTED_ON_PURPOSE`` so the
exemption was reviewed rather than invisible, and escalated to the maintainers. the design
and §2 declared both — the image route on the design reasoning (the book
fetches it for every plate, so it has a client contract), the approval route
because without it ``approved`` could never become true in a live deployment.
Both exemptions are struck; the routes below are the contract's.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from . import storage
from .config import get_plate_settings
from .repository import (
    EmptyNoteError,
    JournalRepository,
    UnknownMemberError,
    UnknownPlateError,
    UnknownSpecimenError,
    get_repository,
)
from .schemas import (
    ApprovalIn,
    FieldNoteIn,
    coverage_out,
    note_out,
    plate_out,
)

router = APIRouter(prefix="/journal", tags=["journal"])

Repo = Depends(get_repository)


# ------------------------------------------------------------------- plates


@router.get("/plates")
async def list_plates(
    approved: bool | None = None, repo: JournalRepository = Repo
) -> list[dict[str, Any]]:
    """Every plate, or only the approved ones.

    ``?approved=false`` is as useful as ``?approved=true`` here: it is the
    queue of plates waiting for somebody to vouch for them, and the book view
    needs to be able to show that a page is not yet signed off rather than
    silently leaving it out.
    """
    return [plate_out(row) for row in await repo.list_plates(approved)]


@router.get("/plates/{plate_id}/image", response_class=Response)
async def plate_image(
    plate_id: str,
    variant: str | None = Query(default=None, pattern="^thumb$"),
    repo: JournalRepository = Repo,
) -> Response:
    """A plate's bytes, from the operator's volume.

    503 when no volume is configured, naming the variable — #46's shape, and
    the reason it matters is the same: writing into a container layer the next
    redeploy discards is worse than saying there is nowhere to write.
    """
    try:
        data = await repo.plate_image(plate_id, thumb=variant == "thumb")
    except UnknownPlateError:
        raise HTTPException(
            status_code=404, detail=f"No such plate: {plate_id}"
        ) from None
    except storage.PlateNotFound:
        raise HTTPException(
            status_code=404,
            detail=(
                "This plate's row exists but its image is not on the volume. "
                "Nothing is served rather than a stand-in, because a stand-in "
                "in a book of plates is a plate."
            ),
        ) from None
    except storage.PlateStoreUnconfigured:
        raise HTTPException(status_code=503, detail=_nowhere_to_keep_plates()) from None
    media_type = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=data, media_type=media_type)


@router.post("/plates/{plate_id}/approve")
async def approve_plate(
    plate_id: str, body: ApprovalIn, repo: JournalRepository = Repo
) -> dict[str, Any]:
    """The maintainers named member accepts this plate as this plant's portrait.

    Not in the frozen contract — see this module's docstring. ``member_id`` is
    required and there is no default: an approval whose author is unknown is
    the one state the field exists to rule out, so there is nothing sensible to
    fall back to and this answers 422 rather than guessing a member.
    """
    try:
        row = await repo.approve_plate(plate_id, body.member_id)
    except UnknownPlateError:
        raise HTTPException(
            status_code=404, detail=f"No such plate: {plate_id}"
        ) from None
    except UnknownMemberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return plate_out(row)


@router.get("/coverage")
async def plate_coverage(repo: JournalRepository = Repo) -> dict[str, Any]:
    """Every plant in the register, and why its leaf is blank if it is.

    Declared in 1.6.0 and the reason the book can now say more
    than *"there is no plate"*. The counts are computed from the entries, so
    `total` cannot disagree with how many plants are listed.

    `generated` is counted per **plant**, not per plate: two specimens of one
    species sharing one drawn plate are two plants being shown a drawn picture,
    which is what a reader of the coverage line is being told.
    """
    coverage = await repo.coverage()
    return coverage_out(coverage, await repo.generated_for_report())


# -------------------------------------------------------------- field notes


@router.get("/{specimen_id}/notes")
async def list_field_notes(
    specimen_id: str, repo: JournalRepository = Repo
) -> list[dict[str, Any]]:
    """This specimen's field notes, oldest first."""
    try:
        rows = await repo.list_notes(specimen_id)
    except UnknownSpecimenError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return [note_out(row) for row in rows]


@router.post("/{specimen_id}/notes", status_code=status.HTTP_201_CREATED)
async def create_field_note(
    specimen_id: str, body: FieldNoteIn, repo: JournalRepository = Repo
) -> dict[str, Any]:
    """Write an observation down.

    ``member_id`` is accepted additively (see ``schemas.FieldNoteIn``). Sent, the
    note records who wrote it; omitted, the note's author is absent in the
    response rather than invented — the design picks the member at write time and
    the frozen body has no field for them.
    """
    try:
        row = await repo.create_note(specimen_id, body.body, body.member_id)
    except UnknownSpecimenError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except UnknownMemberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except EmptyNoteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return note_out(row)


# ---------------------------------------------------------------- plumbing


def _nowhere_to_keep_plates() -> str:
    return (
        "This deployment has nowhere to keep plates. Set MOH_PLATES_IMAGE_DIR "
        "to a path on a volume that survives a redeploy, and mount that volume "
        "into the API and worker services (the design — the repository carries "
        "the name, never a value)."
    )


def plate_store() -> storage.PlateImageStore:
    """The live store, or a 503 that names the variable.

    Mock mode never reaches this: its repository holds its own
    :class:`~workers.plates.storage.MemoryPlateStore`, which is what lets the
    stack come up with no volume attached.
    """
    directory = get_plate_settings().image_dir
    if directory is None:
        raise storage.PlateStoreUnconfigured(_nowhere_to_keep_plates())
    return storage.FilesystemPlateStore(directory)
