"""Map layers, calibration and specimen pins.

contract declares: upload a plan or a survey, calibrate it, and place a pin.
The handlers are thin; the work is in ``grounds.repository`` (fixtures in mock
mode, Postgres when a database is attached), ``grounds.domain`` (what a
calibration has to be before it is stored) and ``grounds.storage`` (where an
uploaded image actually goes).

**An unbounded multipart endpoint is a disk-filling hole**, and on a
self-hosted box the disk it fills is somebody's home server. Four things stand
between this endpoint and that, and each is here rather than in a proxy the
operator may not have run:

* the body is read in chunks against ``MOH_GROUNDS_MAX_UPLOAD_BYTES`` and
  abandoned the moment it exceeds it, so an over-long upload costs the bound
  and not the file;
* the format is decided by the file's own magic bytes, never by the
  ``Content-Type`` the client wrote;
* header-declared dimensions are checked against
  ``MOH_GROUNDS_MAX_IMAGE_PIXELS`` before anything would decode them;
* a full volume answers **507** and leaves nothing half-written.

**Escalation — the image URL is not in the contract.** ``MapLayer.image_url``
is a string the contract does not constrain, and until now the mock pointed it
at a static file that no build produced. Uploaded bytes have to be served from
somewhere, so this router serves them at
``GET /grounds/layers/{layer_id}/image``, hidden from the OpenAPI document and
declared in ``tests/contract/test_api_matches_spec.py``'s
``UNDOCUMENTED_ON_PURPOSE`` so the exemption is reviewed rather than invisible.
It wants the maintainers' decision and a contract line, not a quiet precedent: see
``api/grounds/README.md``.
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from grounds import images, storage
from grounds.config import get_grounds_settings
from grounds.domain import CalibrationError, validate_calibration
from grounds.repository import (
    GroundsRepository,
    PinOutsideLayerError,
    UnknownLayerError,
    UnknownSpecimenError,
    get_repository,
)
from grounds.schemas import CalibrationIn, PinIn, layer_out, pin_out

router = APIRouter(prefix="/grounds", tags=["grounds"])

Repo = Depends(get_repository)

#: Read the body in 64 KiB bites. Small enough that the bound is enforced long
#: before a hostile upload is resident, large enough not to be a syscall storm.
_CHUNK = 64 * 1024

LAYER_KINDS = {"floor_plan", "survey"}


# ------------------------------------------------------------------- layers


@router.get("/layers")
async def list_map_layers(
    site_id: str | None = None, repo: GroundsRepository = Repo
) -> list[dict[str, Any]]:
    """Every floor plan and property survey, in the order they are stacked."""
    return [layer_out(row) for row in await repo.list_layers(site_id)]


@router.post("/layers", status_code=status.HTTP_201_CREATED)
async def create_map_layer(
    response: Response,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    site_id: Annotated[str | None, Form()] = None,
    repo: GroundsRepository = Repo,
) -> dict[str, Any]:
    """Upload a floor plan or a survey. PNG and JPEG, raster only."""
    if kind not in LAYER_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"`kind` must be one of {sorted(LAYER_KINDS)}; got {kind!r}.",
        )
    if not name.strip():
        raise HTTPException(status_code=422, detail="A layer needs a name.")

    settings = get_grounds_settings()
    store = _image_store(repo)
    data = await _read_bounded(file, settings.max_upload_bytes)

    try:
        probed = images.probe(data)
        images.check_within(probed, settings.max_image_pixels)
    except images.UnsupportedImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    except images.ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None

    resolved_site = site_id or await repo.default_site_id()
    if not resolved_site:
        raise HTTPException(
            status_code=422,
            detail="No site exists yet; register the grounds before adding a map layer.",
        )

    import uuid as _uuid

    layer_id = str(_uuid.uuid4())
    key = storage.key_for(layer_id, probed.extension)
    try:
        store.put(key, data)
    except storage.ImageStoreFull as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from None

    try:
        row = await repo.create_layer(
            {
                "id": layer_id,
                "site_id": resolved_site,
                "name": name.strip(),
                "kind": kind,
                "image_key": key,
                "image_width_px": probed.width_px,
                "image_height_px": probed.height_px,
            }
        )
    except Exception:
        # Don't leave an orphan on the operator's volume because a write failed.
        store.delete(key)
        raise

    body = layer_out(row)
    response.headers["Location"] = f"/api/v1/grounds/layers/{layer_id}"
    return body


@router.get("/layers/{layer_id}/image")
async def get_layer_image(layer_id: str, repo: GroundsRepository = Repo) -> Response:
    """The stored bytes of one layer.

    Visible in the generated document since contract 1.5.0. The maps module raised this as an
    escalation rather than letting the exemption settle — `UNDOCUMENTED_ON_PURPOSE`
    is for operational endpoints with no client contract, and the map fetches this
    for every layer, so it was never one. The maintainers agreed and declared it.
    """
    row = await repo.get_layer(layer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such map layer.")
    key = row.get("image_key")
    if not key:
        raise HTTPException(status_code=404, detail="That layer has no stored image.")
    try:
        data = _image_store(repo).get(key)
    except storage.ImageStoreUnconfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except (storage.ImageNotFound, storage.BadImageKey):
        raise HTTPException(
            status_code=404,
            detail=(
                "That layer's image is not on the volume. If this deployment was "
                "moved, restore the map-layer volume alongside the database."
            ),
        ) from None
    media_type = "image/png" if key.endswith(".png") else "image/jpeg"
    # Immutable: the key carries the layer id and a layer's bytes never change
    # in place — a recalibration rewrites numbers, never the picture.
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@router.put("/layers/{layer_id}/calibration")
async def set_calibration(
    layer_id: str, body: CalibrationIn, repo: GroundsRepository = Repo
) -> dict[str, Any]:
    """Set a plan's px→mm scale, or a survey's pixel↔world control points."""
    row = await repo.get_layer(layer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such map layer.")
    try:
        calibration = validate_calibration(
            row["kind"],
            body.model_dump(exclude_none=False),
            row["image_width_px"],
            row["image_height_px"],
        )
    except CalibrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    updated = await repo.set_calibration(layer_id, calibration)
    if updated is None:
        raise HTTPException(status_code=404, detail="No such map layer.")
    return layer_out(updated)


# --------------------------------------------------------------------- pins


@router.get("/pins")
async def list_pins(
    layer_id: str | None = None, repo: GroundsRepository = Repo
) -> list[dict[str, Any]]:
    """Every specimen pin, optionally narrowed to one layer."""
    return [pin_out(row) for row in await repo.list_pins(layer_id)]


@router.put("/pins")
async def set_pin(body: PinIn, repo: GroundsRepository = Repo) -> dict[str, Any]:
    """Place or move a specimen's pin. ``px: null`` lifts it off the map."""
    px = None if body.px is None else {"x": body.px.x, "y": body.px.y}
    try:
        row = await repo.set_pin(body.specimen_id, body.layer_id, px)
    except UnknownSpecimenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except UnknownLayerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except PinOutsideLayerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return pin_out(row)


# ------------------------------------------------------------------ plumbing


def _image_store(repo: GroundsRepository) -> storage.LayerImageStore:
    """Mock mode keeps images beside its rows; live mode uses the operator's volume."""
    held = getattr(repo, "images", None)
    if held is not None:
        return held  # type: ignore[no-any-return]
    directory = get_grounds_settings().image_dir
    if directory is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "This deployment has nowhere to keep map layers. Set "
                "MOH_GROUNDS_IMAGE_DIR to a path on a volume that survives a "
                "redeploy, and mount that volume into the API service (the design "
                "— the repository carries the name, never a value)."
            ),
        )
    return storage.FilesystemImageStore(directory)


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
                    f"A map layer may be at most {limit:,} bytes "
                    f"({limit / (1024 * 1024):.0f} MiB) in this deployment."
                ),
            )
    if not buffer:
        raise HTTPException(status_code=422, detail="No file was uploaded.")
    return bytes(buffer)
