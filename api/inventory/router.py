"""Specimens, locations and members.

and the work happens in ``inventory.repository`` — ``FixtureRepository`` when
``MOH_MOCK_MODE=true``, ``DatabaseRepository`` when a Postgres is attached. Both
answer the same protocol and both serialise through ``inventory.schemas``, so
the shapes the contract fixes in ``contracts/openapi/openapi.yaml`` are built in
exactly one place.

Photographs and the growth log joined. The upload is the shape
The maps module built for map layers in #46 and the reasons are the same: the
body is read in bounded chunks and abandoned the moment it is over
``MOH_PHOTOS_MAX_UPLOAD_BYTES``; the format is decided by the file's own magic
bytes and never by the ``Content-Type`` the client wrote; the header's
dimensions are checked against ``MOH_PHOTOS_MAX_IMAGE_PIXELS`` before anything
would decode them; and a full volume answers 507 with nothing half-written.
The bytes go through the shared store under
``MOH_PHOTOS_IMAGE_DIR``, which has no default.

**The image URL.** ``Photo.url`` and ``thumb_url`` point at
``GET /specimens/{specimen_id}/photos/{photo_id}/image`` (``?variant=thumb``).
C served it ahead of the document and A declared it in contract 1.8.0
(``getPhotoImage``, the design), the maps module's and the journal's case exactly.

The ``/species`` endpoints at the foot of the file belong to the botany worker
(``x-parts of the project: D``); they are still the earlier fixture mock and are left alone.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app import fixtures
from grounds import images as probe_images
from inventory import enrichment, photos
from inventory.config import get_photo_settings
from inventory.repository import (
    InventoryRepository,
    SpecimenQuery,
    UnknownLocationError,
    UnknownMemberError,
    UnknownPhotoError,
    UnknownSpeciesError,
    UnknownSpecimenError,
    get_repository,
)
from inventory.schemas import (
    ListOrder,
    LocationCreate,
    LogEntryCreate,
    SpecimenCreate,
    SpecimenUpdate,
    location_out,
    log_entry_out,
    photo_out,
    specimen_out,
)

router = APIRouter(tags=["inventory"])

Repo = Depends(get_repository)

#: Read the body in 64 KiB bites, so the bound is enforced long before a
#: hostile upload is resident.
_CHUNK = 64 * 1024


def _offset_from(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise HTTPException(status_code=422, detail="Malformed cursor") from None
    if offset < 0:
        raise HTTPException(status_code=422, detail="Malformed cursor")
    return offset


# ------------------------------------------------------------------ specimens


@router.get("/specimens")
async def list_specimens(
    q: str | None = None,
    location_id: str | None = None,
    outdoor: bool | None = None,
    status_: str | None = Query(default=None, alias="status"),
    toxic_to_pets: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """The Register. Archived plants are kept out unless asked for by status."""
    page = await repo.list_specimens(
        SpecimenQuery(
            q=q,
            location_id=location_id,
            outdoor=outdoor,
            status=status_,
            toxic_to_pets=toxic_to_pets,
            limit=limit,
            offset=_offset_from(cursor),
        )
    )
    return {
        "items": [specimen_out(row) for row in page.items],
        "next_cursor": page.next_cursor,
        "total": page.total,
    }


@router.post("/specimens", status_code=status.HTTP_201_CREATED)
async def create_specimen(
    body: SpecimenCreate,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """Add a plant by name.

    The typed name is matched against the species already known; if nothing
    matches, the name becomes the specimen's nickname so it appears in the
    Register under what the keeper actually typed, and resolution is left to
    The botany worker's queue. The response never waits on that.
    """
    species_id: str | None = str(body.species_id) if body.species_id else None
    if species_id is None:
        species_id = await repo.resolve_species_by_name(body.name)

    data = body.model_dump(exclude={"name", "image_key"})
    data["species_id"] = species_id
    # An unmatched name has nowhere else to live in the frozen schema; see the
    # PR notes. A matched one leaves the nickname empty so the display name
    # falls through to the common name, as the contract describes.
    data["nickname"] = body.nickname or (None if species_id else body.name)

    try:
        row = await repo.create_specimen(data)
    except UnknownLocationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownSpeciesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await enrichment.queue(
        enrichment.EnrichmentRequest(
            specimen_id=str(row["id"]),
            typed_name=body.name,
            species_id=species_id,
            image_key=body.image_key,
            queued_at=datetime.now(UTC),
        )
    )
    return specimen_out(row)


@router.get("/specimens/{specimen_id}")
async def get_specimen(
    specimen_id: str, repo: InventoryRepository = Repo
) -> dict[str, Any]:
    row = await repo.get_specimen(specimen_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such specimen")
    return specimen_out(row)


@router.patch("/specimens/{specimen_id}")
async def update_specimen(
    specimen_id: str,
    body: SpecimenUpdate,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """Edit a plant. Omitted fields are left alone; an explicit null clears one.

    Moving a specimen to another location re-derives ``is_outdoor`` from it, so
    a plant brought in for the winter leaves the frost alerts the moment it is
    moved on the Register rather than the next time something recomputes.
    """
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        row = await repo.get_specimen(specimen_id)
        if not row:
            raise HTTPException(status_code=404, detail="No such specimen")
        return specimen_out(row)

    try:
        row = await repo.update_specimen(specimen_id, changes)
    except UnknownLocationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="No such specimen")
    return specimen_out(row)


@router.delete("/specimens/{specimen_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_specimen(
    specimen_id: str, repo: InventoryRepository = Repo
) -> Response:
    """Archive, do not delete. A lost plant is part of the record.

    The row keeps its logs, its photos and its history; it simply stops being
    listed by the Register unless asked for with ``?status=archived``.
    """
    if not await repo.archive_specimen(specimen_id):
        raise HTTPException(status_code=404, detail="No such specimen")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- photographs


@router.get("/specimens/{specimen_id}/photos")
async def list_photos(
    specimen_id: str,
    order: ListOrder = "newest",
    repo: InventoryRepository = Repo,
) -> list[dict[str, Any]]:
    """This plant's photographs. ``newest`` is ``taken_at`` descending and the
    default; ``oldest`` is ascending, how a growth log is read."""
    rows = await repo.list_photos(specimen_id, order)
    if rows is None:
        raise HTTPException(status_code=404, detail="No such specimen")
    return [photo_out(row) for row in rows]


@router.post("/specimens/{specimen_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    specimen_id: str,
    response: Response,
    file: Annotated[UploadFile, File()],
    caption: Annotated[str | None, Form()] = None,
    taken_at: Annotated[datetime | None, Form()] = None,
    is_primary: Annotated[bool, Form()] = False,
    member_id: Annotated[uuid.UUID | None, Form()] = None,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """Add a photograph of this plant. PNG or JPEG, judged from the bytes.

    ``caption``, ``taken_at`` (defaulting to now), ``is_primary`` (exclusive per
    specimen: the Register has one portrait) and ``member_id`` (who took it)
    are optional form fields; the contract declares the first and the others
    are additive, asked for and never required.
    """
    # Nowhere to keep photographs is a deployment fact, so it is said first:
    # before the database is asked anything and before the body is read.
    store = _photo_store(repo)
    if await repo.get_specimen(specimen_id) is None:
        raise HTTPException(status_code=404, detail="No such specimen")
    settings = get_photo_settings()
    data = await _read_bounded(file, settings.max_upload_bytes)

    try:
        extension = photos.sniff_extension(data, what="a photograph")
        # Read-only reuse of the maps module's header probe: a
        # second parser is the thing §1 just removed. It reads the declared
        # dimensions out of the header so a decompression bomb is refused
        # before anything would decode it.
        probed = probe_images.probe(data)
        probe_images.check_within(probed, settings.max_image_pixels)
    except photos.UnsupportedImageFormat as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    except probe_images.UnsupportedImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    except probe_images.ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None

    photo_id = str(uuid.uuid4())
    key = photos.key_for(photo_id, extension)
    try:
        store.put(key, data)
    except photos.ImageStoreFull as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from None

    try:
        row = await repo.create_photo(
            specimen_id,
            {
                "id": photo_id,
                "image_key": key,
                "caption": (caption or "").strip() or None,
                "taken_at": _utc(taken_at),
                "is_primary": is_primary,
                "member_id": str(member_id) if member_id else None,
            },
        )
    except UnknownSpecimenError:
        store.delete(key)
        raise HTTPException(status_code=404, detail="No such specimen") from None
    except UnknownMemberError as exc:
        store.delete(key)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        # Don't leave an orphan on the operator's volume because a write failed.
        store.delete(key)
        raise

    body = photo_out(row)
    response.headers["Location"] = body["url"]
    return body


@router.get(
    "/specimens/{specimen_id}/photos/{photo_id}/image",
    response_class=Response,
)
async def get_photo_image(
    specimen_id: str,
    photo_id: str,
    variant: str | None = Query(default=None, pattern="^thumb$"),
    repo: InventoryRepository = Repo,
) -> Response:
    """The stored bytes of one photograph; ``?variant=thumb`` for its thumbnail.

    In the contract since 1.8.0 (``getPhotoImage``, the design), after C
    served it ahead of the document as the maps module and the journal did. A photograph is
    served only under its own specimen: the same id under another
    plant's path is a 404. A thumbnail that was never made falls back to the
    original, the journal's shape; a file missing from the volume is a 404 and never a
    stand-in.
    """
    row = await repo.get_photo(specimen_id, photo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such photograph.")
    key = (row.get("thumb_key") if variant == "thumb" else None) or row["image_key"]
    try:
        data = _photo_store(repo).get(key)
    except (photos.ImageNotFound, photos.BadImageKey):
        raise HTTPException(
            status_code=404,
            detail=(
                "This photograph's record exists but its file is not on the "
                "volume. If this deployment was moved, restore the photo volume "
                "alongside the database. Nothing is served in its place."
            ),
        ) from None
    # Immutable: the key carries the photo id and a photograph's bytes never
    # change in place — a caption edit rewrites words, never the picture.
    return Response(
        content=data,
        media_type=photos.media_type_for(data),
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


# ----------------------------------------------------------------- growth log


@router.get("/specimens/{specimen_id}/log")
async def list_log_entries(
    specimen_id: str,
    order: ListOrder = "newest",
    repo: InventoryRepository = Repo,
) -> list[dict[str, Any]]:
    """Growth, pest, disease, repotting, pruning, move and note entries, over
    ``occurred_at`` in the requested order."""
    rows = await repo.list_log_entries(specimen_id, order)
    if rows is None:
        raise HTTPException(status_code=404, detail="No such specimen")
    return [log_entry_out(row) for row in rows]


@router.post("/specimens/{specimen_id}/log", status_code=status.HTTP_201_CREATED)
async def create_log_entry(
    specimen_id: str,
    body: LogEntryCreate,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """Add an entry. ``photo_id`` must be one of this plant's own photographs.

    A move made on the Register (``PATCH`` with a new ``location_id``) writes
    its own ``relocate`` entry with ``data: {from_location_id, to_location_id}``;
    this route is for entries a keeper writes by hand, and a hand-written
    ``relocate`` may carry the same two keys in the additive ``data``.
    """
    data = body.model_dump()
    data["occurred_at"] = _utc(body.occurred_at)
    try:
        row = await repo.create_log_entry(specimen_id, data)
    except UnknownSpecimenError:
        raise HTTPException(status_code=404, detail="No such specimen") from None
    except UnknownPhotoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except UnknownMemberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return log_entry_out(row)


# ------------------------------------------------------------------ locations


@router.get("/locations")
async def list_locations(
    site_id: str | None = None,
    outdoor: bool | None = None,
    repo: InventoryRepository = Repo,
) -> list[dict[str, Any]]:
    rows = await repo.list_locations(site_id=site_id, outdoor=outdoor)
    return [out for out in (location_out(r) for r in rows) if out is not None]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
async def create_location(
    body: LocationCreate, repo: InventoryRepository = Repo
) -> dict[str, Any]:
    """Add a place: a room, a shelf, a bed, or a zone drawn on a plan.

    ``is_outdoor`` and ``is_covered`` are the two flags the weather engines
    read — a covered outdoor zone collects no rain, an indoor one raises no
    frost alerts — so both are recorded here rather than inferred later.
    """
    try:
        row = await repo.create_location(body.model_dump())
    except (UnknownLocationError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out = location_out(row)
    assert out is not None
    return out


@router.patch("/locations/{location_id}")
async def update_location(
    location_id: str,
    body: LocationCreate,
    repo: InventoryRepository = Repo,
) -> dict[str, Any]:
    """Edit a place.

    Changing ``is_outdoor`` carries every specimen standing in this location
    with it, in one transaction: the denormalised flag on a specimen may never
    disagree with its location's.
    """
    try:
        row = await repo.update_location(location_id, body.model_dump())
    except UnknownLocationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="No such location")
    out = location_out(row)
    assert out is not None
    return out


# -------------------------------------------------------------------- members


@router.get("/members")
async def list_members(repo: InventoryRepository = Repo) -> list[dict[str, Any]]:
    rows = await repo.list_members()
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "role": row["role"],
            "notify_prefs": row.get("notify_prefs") or {},
        }
        for row in rows
    ]


# ------------------------------------------------------------------ plumbing


def _photo_store(repo: InventoryRepository) -> photos.PhotoImageStore:
    """Mock mode keeps photographs beside its rows; live mode uses the volume."""
    store = repo.photo_images
    if store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "This deployment has nowhere to keep photographs. Set "
                "MOH_PHOTOS_IMAGE_DIR to a path on a volume that survives a "
                "redeploy, and mount that volume into the API service (the design "
                "— the repository carries the name, never a value)."
            ),
        )
    return store


def _utc(value: datetime | None) -> datetime | None:
    """A client's timestamp as UTC; a naive one is taken as UTC rather than
    guessed at. ``None`` stays ``None`` so the store can default to now."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, and refuse the moment there is one more."""
    buffer = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"A photograph may be at most {limit:,} bytes "
                    f"({limit / (1024 * 1024):.0f} MiB) in this deployment."
                ),
            )
    if not buffer:
        raise HTTPException(status_code=422, detail="No file was uploaded.")
    return bytes(buffer)


# ------------------------------------------- species


@router.get("/species")
async def list_species(q: str | None = None) -> list[dict[str, Any]]:
    rows = fixtures.species()
    if q:
        needle = q.casefold()
        rows = [
            r
            for r in rows
            if needle in r["accepted_name"].casefold()
            or any(needle in c.casefold() for c in r.get("common_names", []))
        ]
    return [_species_out(r) for r in rows]


@router.get("/species/{species_id}")
async def get_species(species_id: str) -> dict[str, Any]:
    row = fixtures.by_id(fixtures.species(), species_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such species")
    return _species_out(row)


@router.get("/species/{species_id}/care-values")
async def list_care_values(species_id: str) -> list[dict[str, Any]]:
    row = fixtures.by_id(fixtures.species(), species_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such species")
    out = []
    for cv in row.get("care_values", []):
        source = fixtures.by_id(fixtures.sources(), cv.get("source_id") or "")
        out.append(
            {
                "field": cv["field"],
                "value": cv["value"],
                "unit": cv.get("unit"),
                "source": source,
                "confidence": cv["confidence"],
                "is_user_override": False,
                "note": cv.get("note"),
            }
        )
    return out


def _species_out(row: dict[str, Any]) -> dict[str, Any]:
    cited = {cv.get("source_id") for cv in row.get("care_values", [])} - {None}
    return {
        **{k: v for k, v in row.items() if k != "care_values"},
        "common_name": (row.get("common_names") or [None])[0],
        "sources": [s for s in fixtures.sources() if s["id"] in cited],
    }
