"""Naturalist's Journal plate pipeline — the journal.

The earlier skeleton named the shape and an earlier release fills it in. Its two constants have
moved to the modules that own them and are re-exported here, because the Arq
worker is this package's front door and two releases' worth of references point
at these names:

* ``PUBLIC_DOMAIN_SOURCES`` and the connectors → `sources.py`
* ``HOUSE_STYLE``, and the marks a generated plate must not wear → `style.py`
* ``ACCEPTABLE_LICENCES`` / ``is_usable_licence`` → `domain.py`

The skeleton's docstring made the promise this release had to keep — *"a
generated plate is always labelled as such and never carries a
botanical attribution it did not earn"* — and `domain.py` is where it is now
enforced rather than hoped for.

## What the jobs do, and what they refuse to do

:func:`source_plate` sources one species and stores the plate if a catalogue
stated a licence. :func:`generate_plate` draws one, if and only if an operator
configured a generator. :func:`refresh_journal` walks every species that has no
plate and tries both, in order.

None of them approve anything. ``approved`` is a member's act and this module
has no member (see `repository.py`), so the honest end state of a fully
successful run is *"every species has an unapproved plate"* — which is the
releases's exit criterion minus the one step a program must not take.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from workers.runtime import ArqBootstrap

from .config import get_plate_settings
from .domain import ACCEPTABLE_LICENCES, is_usable_licence
from .fetcher import HttpPlateFetcher
from .generation import HttpPlateGenerator
from .pipeline import (
    PlateOutcome,
    SourcingRun,
    source_or_generate,
)
from .pipeline import (
    source_plate as _source,
)
from .sources import (
    IMPLEMENTED_SOURCES,
    PUBLIC_DOMAIN_SOURCES,
    BiodiversityHeritageLibrarySource,
    PlateSource,
    WikimediaCommonsSource,
)
from .storage import FilesystemPlateStore, PlateImageStore
from .style import HOUSE_STYLE

__all__ = [
    "ACCEPTABLE_LICENCES",
    "HOUSE_STYLE",
    "IMPLEMENTED_SOURCES",
    "PUBLIC_DOMAIN_SOURCES",
    "WorkerSettings",
    "generate_plate",
    "is_usable_licence",
    "refresh_journal",
    "source_plate",
]

log = logging.getLogger(__name__)


def build_sources(fetcher: Any) -> list[PlateSource]:
    """The roster, in order, as `sources.PUBLIC_DOMAIN_SOURCES` declares it.

    **Commons first, because it is the one a deployment can use without asking
    anybody for anything**. BHL follows and is asked only when
    ``MOH_PLATES_BHL_API_KEY`` is set; without a key it reports itself
    unavailable and the reason is recorded, never treated as a source that had
    nothing. A reader of this list should not come away assuming a keyed BHL is
    the normal state — it is the exception, and an earlier release had the order the other way
    round, which made the exception look like the rule.

    Scanned literature is still the better provenance when it is available.
    That is a statement about quality, not availability, and the preference
    rule is unchanged: whichever source answers first with a clearly licensed
    image wins.
    """
    settings = get_plate_settings()
    return [
        WikimediaCommonsSource(fetcher),
        BiodiversityHeritageLibrarySource(fetcher, settings.bhl_api_key),
    ]


def _store() -> PlateImageStore:
    """The operator's volume, or a refusal that names the variable."""
    from .storage import PlateStoreUnconfigured

    directory = get_plate_settings().image_dir
    if directory is None:
        raise PlateStoreUnconfigured(
            "This deployment has nowhere to keep plates. Set "
            "MOH_PLATES_IMAGE_DIR to a path on a volume that survives a "
            "redeploy, and mount that volume into the worker service "
            "."
        )
    return FilesystemPlateStore(directory)


def _fetcher() -> HttpPlateFetcher:
    settings = get_plate_settings()
    return HttpPlateFetcher(
        timeout_seconds=settings.source_timeout_seconds,
        max_image_bytes=settings.max_image_bytes,
    )


async def source_plate(ctx: dict, species_id: str, name: str) -> dict[str, Any]:
    """Try the public-domain catalogues for one species. No generation."""
    fetcher = _fetcher()
    run = SourcingRun(name, species_id=species_id)
    outcome = await _source(run, build_sources(fetcher), fetcher, _store())
    return _record(ctx, outcome, name)


async def generate_plate(ctx: dict, species_id: str, name: str) -> dict[str, Any]:
    """Source first, then draw — but only if an operator chose a generator.

    Named ``generate_plate`` because the earlier skeleton did and the queue holds
    that name, but it is deliberately *not* a generate-only job: a job that
    skipped sourcing would be a way to get a drawn plate for a plant that has a
    real one, which is the wrong answer in a book of plates.
    """
    fetcher = _fetcher()
    run = SourcingRun(name, species_id=species_id)
    outcome = await source_or_generate(
        run,
        build_sources(fetcher),
        fetcher,
        _store(),
        generator=HttpPlateGenerator(fetcher),
    )
    return _record(ctx, outcome, name)


async def refresh_journal(ctx: dict, plants: list[dict[str, str]]) -> dict[str, Any]:
    """Walk a list of ``{species_id, name}`` and report real coverage.

    Returns counts, not a boolean. A run that got nine of twelve is a run that
    got nine of twelve, and the three that failed each carry their reason — the
    caller is an operator looking at a journal with gaps in it, and "done" is
    not an answer they can act on.
    """
    outcomes: list[tuple[str, PlateOutcome]] = []
    for plant in plants:
        outcome = await generate_plate(
            ctx, plant["species_id"], plant["name"]
        )  # type: ignore[assignment]
        outcomes.append((plant["name"], outcome))  # type: ignore[arg-type]
    return {"attempted": len(plants), "results": [kind for _, kind in outcomes]}


def _record(ctx: dict, outcome: PlateOutcome, name: str) -> dict[str, Any]:
    """Log what happened and hand back something a caller can report.

    Every rejection and every skipped source is logged, because the question an
    operator asks about a journal with holes in it is *why*, and a pipeline that
    only logs its successes cannot answer.
    """
    if outcome.has_plate:
        log.info("plate for %s: %s", name, outcome.kind)
    else:
        log.info("no plate for %s: %s", name, outcome.reason)
    for rejection in outcome.rejections:
        log.info("  refused: %s", rejection)
    for skipped in outcome.skipped_sources:
        log.info("  not asked: %s", skipped)
    plate = outcome.plate
    return {
        "kind": outcome.kind,
        "plate_id": plate.id if plate else None,
        "origin": plate.origin if plate else None,
        # Always false. Stated rather than omitted, so a caller reading this
        # dict cannot mistake silence for approval.
        "approved": False,
        "reason": outcome.reason,
        "rejections": list(outcome.rejections),
        "skipped_sources": list(outcome.skipped_sources),
    }


class WorkerSettings(metaclass=ArqBootstrap):
    functions: ClassVar[list] = [source_plate, generate_plate, refresh_journal]
