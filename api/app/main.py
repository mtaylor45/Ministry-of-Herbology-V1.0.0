"""API entrypoint.

are owned by the inventory API, the botany worker, the weather engine, the hub, the scheduler, the
maps module and the journal; each ships fixture-backed mocks until its
real implementation lands.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# The botany worker's routes live under workers/, which the API image puts on
# PYTHONPATH alongside api/.
from workers.botany.router import router as botany_router
from workers.hub.router import router as hub_router
from workers.plates.router import router as journal_router

from almanac.router import router as almanac_router
from app.auth import AuthMiddleware
from app.auth import router as auth_router
from app.log_redaction import install as install_log_redaction
from app.settings import get_settings
from grounds.router import router as grounds_router
from inventory.router import router as inventory_router
from tending.router import router as tending_router

CONTRACT_VERSION = (
    (Path(__file__).resolve().parents[2] / "contracts" / "VERSION").read_text().strip()
)

# The calendar token rides in the URL because Google's and Apple's fetchers
# carry no session. Redact it out of the access log before anything
# serves a request, so the promise that it "is never logged" is true of this
# process and not only of the package that issues it.
install_log_redaction()

app = FastAPI(
    title="The Ministry of Herbology API",
    version=CONTRACT_VERSION,
    description="Implementation of contracts/openapi/openapi.yaml.",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

# The household's sign-in: every request under /api/v1 passes
# through this before any router runs. Added before CORS so that CORS wraps it
# and a browser's preflight is answered rather than refused.
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory_router, prefix="/api/v1")
app.include_router(botany_router, prefix="/api/v1")
app.include_router(almanac_router, prefix="/api/v1")
app.include_router(tending_router, prefix="/api/v1")
app.include_router(grounds_router, prefix="/api/v1")
app.include_router(journal_router, prefix="/api/v1")
app.include_router(hub_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


@app.get("/api/v1/healthz", tags=["platform"])
async def healthz() -> dict[str, str | None]:
    """Liveness, and the three facts a client keys a cache on.

    ``scenario`` joined in 1.7.0: the offline worker names its
    cache after ``contract_version``, ``mode`` and ``scenario`` so a Morning
    Rounds cached under the frost fixture is dropped when an operator switches
    to drought. It is the selector's name, never the recording.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "mode": "mock" if settings.mock_mode else "live",
        "scenario": os.environ.get("MOH_SCENARIO") or None,
    }
