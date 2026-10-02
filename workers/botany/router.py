"""``POST /taxon/resolve`` — the contract's taxon endpoint, the botany worker's.

The route the OpenAPI document declares under ``x-parts of the project: D``. It lives here
because the botany worker owns ``workers/botany/``; mounting it on the app is a one-line change
in ``api/app/main.py``, which is the maintainers's file:

    from botany.router import router as botany_router # or workers.botany
    app.include_router(botany_router, prefix="/api/v1")

Responses, all in the contract's vocabulary:

* **200** — a ranked list of ``TaxonCandidate``, longest-odds last. An empty
  list is a real answer: nobody has heard of it, which the UI renders as such.
* **422** — neither ``name`` nor ``image_key`` was sent.
* **501** — a photo was sent and Pl@ntNet is off. Typed names are
  unaffected; the free path never depends on a flagged source.
* **503** — every source was unreachable. A source that is down must not be
  served to the user as "no such plant".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .factory import get_resolver
from .settings import get_settings

router = APIRouter(tags=["botany"])


class TaxonResolveRequest(BaseModel):
    """The request body the contract declares for ``resolveTaxon``."""

    name: str | None = Field(default=None, description="Common or scientific name")
    image_key: str | None = Field(
        default=None, description="Uploaded photo for Pl@ntNet ID"
    )


@router.post(
    "/taxon/resolve", summary="Resolve a typed name to an accepted scientific name"
)
async def resolve_taxon(body: TaxonResolveRequest) -> list[dict[str, Any]]:
    name = (body.name or "").strip()

    if not name:
        if body.image_key:
            raise HTTPException(
                status_code=501,
                detail=(
                    "Photo identification needs Pl@ntNet, which is off: the design keeps "
                    "this build on free and openly licensed sources. Type a name instead."
                ),
            )
        raise HTTPException(status_code=422, detail="Send a name to resolve.")

    resolution = await get_resolver().resolve(name)

    if not resolution.candidates and not resolution.reachable:
        # Everything we could ask was down. Saying "no such plant" here would be
        # a claim about the plant, and we have no evidence for one.
        raise HTTPException(
            status_code=503,
            detail=f"No taxonomic source could be reached: {resolution.errors}",
        )

    return resolution.to_list()


@router.get("/taxon/sources", include_in_schema=False)
async def taxon_sources() -> dict[str, Any]:
    """Which sources this deployment is actually asking. Not in the contract.

    Off the schema on purpose (``include_in_schema=False``) so it cannot count as
    a route outside the frozen contract; it exists because "why is this value
    unknown?" is the first question the answer raises, and mock mode versus live
    is the usual reason.
    """
    settings = get_settings()
    return {
        "mock_mode": settings.mock_mode,
        "connectors": [c.kind for c in get_resolver().connectors],
        "flagged_off": [
            kind
            for kind in ("perenual", "plantnet")
            if not getattr(settings, f"enable_{kind}")
        ],
    }
