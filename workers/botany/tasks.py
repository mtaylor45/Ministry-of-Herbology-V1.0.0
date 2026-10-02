"""Botanical knowledge worker — the botany worker.

Taxon resolution landed; the remaining source connectors and the cited
care synthesis land. the design governs everything here: this worker may
rank and select among sourced values and may write prose, but it may never
originate a number.

This module holds the two things every part of the worker shares — the source
precedence table and the confidence arithmetic — plus the Arq jobs. The pieces
live next door: ``names`` parses what was typed, ``connectors/`` asks the
sources, ``resolve`` ranks what they said.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from workers.runtime import ArqBootstrap

#: Preference order when two sources disagree about the same field. Taxonomic
#: authorities outrank aggregators; an aggregator outranks an encyclopaedia.
SOURCE_RANK = {
    "user": 0,
    "powo": 1,
    "gbif": 2,
    "usda": 3,
    "perenual": 4,
    "wikidata": 5,
    "wikipedia": 6,
    "other": 9,
}

CONFIDENCE_BY_RANK = {
    0: "high",
    1: "high",
    2: "high",
    3: "high",
    4: "medium",
    5: "medium",
}

#: Best to worst. the design allows exactly these four, and the database enforces
#: them with a CHECK.
CONFIDENCE_ORDER = ("high", "medium", "low", "unknown")


def downgrade(confidence: str, steps: int = 1) -> str:
    """Lower a confidence by ``steps``, never below ``unknown``.

    The only direction this arithmetic runs. Doubt about a source, a fuzzy match
    or a disagreement may lower what we claim; nothing raises it, because there
    is no evidence that arrives by inference.
    """
    if steps <= 0:
        return confidence
    try:
        index = CONFIDENCE_ORDER.index(confidence)
    except ValueError:
        return "unknown"
    return CONFIDENCE_ORDER[min(index + steps, len(CONFIDENCE_ORDER) - 1)]


@dataclass(frozen=True, slots=True)
class SourcedValue:
    field: str
    value: object
    source_kind: str
    unit: str | None = None


def choose(values: list[SourcedValue]) -> tuple[SourcedValue | None, str]:
    """Pick the value to publish for a field, and say how much to trust it.

    Returns ``(None, "unknown")`` when nothing is sourced, which is a legitimate
    answer the UI must render — not a gap to fill with a plausible guess.
    """
    if not values:
        return None, "unknown"
    best = min(values, key=lambda v: SOURCE_RANK.get(v.source_kind, 9))
    rank = SOURCE_RANK.get(best.source_kind, 9)
    confidence = CONFIDENCE_BY_RANK.get(rank, "low")
    # Disagreement between two otherwise trusted sources is itself information.
    others = [v for v in values if v is not best]
    if others and any(
        v.value != best.value and SOURCE_RANK.get(v.source_kind, 9) <= 3 for v in others
    ):
        confidence = "medium" if confidence == "high" else "low"
    return best, confidence


async def resolve_taxon(ctx: dict, name: str) -> list[dict[str, Any]]:
    """an earlier release: a typed name in, ranked accepted names out, each with a citation.

    The Arq entry point. ``ctx`` may carry a prepared ``resolver`` (the API does,
    so one process keeps one HTTP client and one payload cache); otherwise one is
    built from the settings.
    """
    from .factory import get_resolver

    resolver = ctx.get("resolver") or get_resolver()
    resolution = await resolver.resolve(name)
    return resolution.to_list()


async def enrich_species(
    ctx: dict, species_id: str, accepted_name: str = ""
) -> dict[str, Any]:
    """an earlier release: fill a species' care profile from the free sources, every value cited.

    Returns the species column updates, the ``care_value`` rows and the
    ``source`` rows (payloads included) for the caller to persist — this worker
    decides what is true and what it is worth, and does not own the database.

    ``accepted_name`` is what an earlier release resolution settled on. Without it there is
    nothing to look up, and enrichment says so rather than guessing from an id.
    """
    from .connectors.base import SpeciesRef
    from .factory import get_enricher

    if not accepted_name.strip():
        return {
            "species_id": species_id,
            "enrichment_state": "failed",
            "errors": {
                "input": "enrich_species needs the accepted name an earlier release resolved"
            },
            "columns": {},
            "care_values": [],
            "sources": [],
        }

    enricher = ctx.get("enricher") or get_enricher()
    enrichment = await enricher.enrich(SpeciesRef(accepted_name=accepted_name.strip()))
    return {
        "species_id": species_id,
        "enrichment_state": enrichment.state,
        "errors": enrichment.errors,
        "columns": enrichment.columns,
        "care_values": enrichment.to_care_value_dicts(),
        "sources": [s.to_row() for s in enrichment.sources],
    }


class WorkerSettings(metaclass=ArqBootstrap):
    functions: ClassVar[list] = [resolve_taxon, enrich_species]
