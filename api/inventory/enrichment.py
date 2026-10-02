"""Handing a new plant to the botany worker, without making the keeper wait.

Adding a plant is three steps — name or photo, confirm the match, drop a pin —
and none of them is "wait for the internet". Taxon resolution and the source
connectors run on the Arq queue; this module posts the job and gets out of the
way. It never raises into the request path: a queue that is down must cost the
keeper a citation later, not the plant they just typed in.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.settings import get_settings

logger = logging.getLogger(__name__)

#: Arq jobs on the botany worker's worker (``workers/botany/tasks.py``).
RESOLVE_TAXON = "resolve_taxon"
ENRICH_SPECIES = "enrich_species"


@dataclass(frozen=True, slots=True)
class EnrichmentRequest:
    """What the botany worker is being asked to look up, and for which specimen."""

    specimen_id: str
    typed_name: str
    species_id: str | None = None
    image_key: str | None = None
    queued_at: datetime = datetime(1970, 1, 1, tzinfo=UTC)

    @property
    def job(self) -> str:
        """An unmatched name needs resolving first; a known species needs sources."""
        return ENRICH_SPECIES if self.species_id else RESOLVE_TAXON


#: The last few requests, so mock mode can show that a create queued work and
#: the tests can assert the response did not block on it.
_RECENT: deque[EnrichmentRequest] = deque(maxlen=50)
_POOL: Any = None


def recent() -> list[EnrichmentRequest]:
    return list(_RECENT)


def clear_recent() -> None:
    _RECENT.clear()


async def _pool() -> Any:
    global _POOL
    if _POOL is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _POOL = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _POOL


async def queue(request: EnrichmentRequest) -> bool:
    """Enqueue enrichment. Returns whether it reached the queue; never raises."""
    _RECENT.append(request)
    if get_settings().mock_mode:
        # No Redis in the mock stack. The request is recorded, not dispatched —
        # The botany worker's worker is the thing that would answer it.
        logger.debug(
            "mock mode: %s not dispatched for %s", request.job, request.specimen_id
        )
        return False
    try:
        pool = await _pool()
        await pool.enqueue_job(
            request.job,
            request.species_id or request.typed_name,
        )
        return True
    except Exception:  # noqa: BLE001 - enrichment must never fail a create
        logger.warning(
            "could not queue %s for specimen %s; it will need re-running",
            request.job,
            request.specimen_id,
            exc_info=True,
        )
        return False
