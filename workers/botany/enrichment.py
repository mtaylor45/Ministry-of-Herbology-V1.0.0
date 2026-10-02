"""Cited care synthesis — selection, never generation.

the design in one module. Every connector reports what its source said; this
decides what to publish, and records for each field *where it came from* and
*how much to trust it*. It may rank and select among sourced values. It may
never originate one:

* a field no source stated is published as ``value: None`` with
  ``confidence: unknown`` — not as a plausible default. Engine fallbacks are
  the engines' own documented assumptions, not facts about the plant;
* a citation always supports the value it is attached to, which is why the
  toxicity rule below picks the source that made the claim rather than the
  highest-ranked source overall;
* the raw payload behind every citation is kept, so a synthesis can be redone
  and an auditor can check a unit conversion against what was actually said.

Confidence comes from ``choose()`` in ``tasks.py`` — the same precedence table
an earlier release resolution uses — and is then lowered, never raised.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from .connectors.base import ConnectorResult, FactRecord, SpeciesRef
from .sources import SourceRecord
from .tasks import SOURCE_RANK, SourcedValue, choose, downgrade

#: Units for the fields that have one. SI internally (the project conventions); the display
#: unit is a user preference and none of this module's business.
FIELD_UNITS: dict[str, str] = {
    "min_temp_c": "C",
    "max_temp_c": "C",
    "water_interval_days": "days",
    "humidity_min_pct": "%",
    "light_min_lux": "lux",
    "light_max_lux": "lux",
}

#: The care profile: every one of these gets a ``care_value`` row when a source
#: states it, carrying the source and the confidence.
CARE_FIELDS: tuple[str, ...] = (
    "light_label",
    "light_min_lux",
    "light_max_lux",
    "water_k_c",
    "water_interval_days",
    "soil_ph_min",
    "soil_ph_max",
    "soil_type",
    "fertilizer_note",
    "humidity_min_pct",
    "min_temp_c",
    "max_temp_c",
    "usda_zone_min",
    "usda_zone_max",
    "dormancy_months",
    "toxic_to_pets",
    "toxic_to_children",
    "toxicity_note",
)

#: Prose and taxonomy. Cited the same way, because "where did this paragraph
#: come from" is the same question as "where did this number come from".
DESCRIPTIVE_FIELDS: tuple[str, ...] = ("summary", "common_names", "native_range")

#: Identifiers, written to the species row but not shown as care values.
IDENTIFIER_FIELDS: tuple[str, ...] = (
    "gbif_key",
    "powo_id",
    "wikidata_id",
    "family",
    "genus",
)

#: Reported even when nothing is sourced, so the gap is visible rather than
#: silent. ``water_k_c`` and ``min_temp_c`` drive engines that move real plants
#: and,, nothing measures the soil to catch them being wrong;
#: the toxicity flags are a safety feature. The UI renders "we don't know"
#: and the user can fill it in.
ALWAYS_REPORT: tuple[str, ...] = (
    "water_k_c",
    "min_temp_c",
    "water_interval_days",
    "light_label",
    "toxic_to_pets",
    "toxic_to_children",
)

#: Toxicity. Under-reporting is the dangerous direction, so a claim of "toxic"
#: is published even when a higher-precedence source says otherwise — with the
#: confidence lowered to record that the sources disagree.
SAFETY_FIELDS: frozenset[str] = frozenset({"toxic_to_pets", "toxic_to_children"})


@dataclass(frozen=True, slots=True)
class CareValue:
    """One ``care_value`` row, in the contract's ``CareValue`` shape."""

    field: str
    value: Any
    confidence: str
    source_id: str | None = None
    unit: str | None = None
    note: str | None = None
    is_user_override: bool = False

    def __post_init__(self) -> None:
        # The database enforces this with a CHECK; failing here means a bug in
        # synthesis rather than a bad row reaching Postgres.
        if (
            self.source_id is None
            and not self.is_user_override
            and self.confidence != "unknown"
        ):
            raise ValueError(
                f"{self.field}: a value with no source must be confidence 'unknown', "
                f"not {self.confidence!r}"
            )

    def to_dict(self, source: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "unit": self.unit,
            "source": source,
            "confidence": self.confidence,
            "is_user_override": self.is_user_override,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Enrichment:
    """Everything one enrichment produced, ready to persist."""

    species: SpeciesRef
    #: Column updates for the ``species`` row. Only fields somebody sourced.
    columns: dict[str, Any] = dataclass_field(default_factory=dict)
    care_values: tuple[CareValue, ...] = ()
    #: Every call made, payload included, for the ``source`` table.
    sources: tuple[SourceRecord, ...] = ()
    #: Source kind → why it could not be asked.
    errors: dict[str, str] = dataclass_field(default_factory=dict)

    @property
    def state(self) -> str:
        """``species.enrichment_state``: failed only if nobody answered."""
        return "complete" if self.sources else "failed"

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(cv.field for cv in self.care_values if cv.confidence == "unknown")

    def source_by_id(self, source_id: str | None) -> SourceRecord | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def to_care_value_dicts(self) -> list[dict[str, Any]]:
        """The contract's ``CareValue`` list, each with its citation resolved."""
        out = []
        for care_value in self.care_values:
            source = self.source_by_id(care_value.source_id)
            out.append(care_value.to_dict(source.to_ref() if source else None))
        return out


def _facts_by_field(results: Sequence[ConnectorResult]) -> dict[str, list[FactRecord]]:
    facts: dict[str, list[FactRecord]] = {}
    for result in results:
        for fact in result.facts:
            facts.setdefault(fact.field, []).append(fact)
    return facts


def _source_id_for(kind: str, results: Sequence[ConnectorResult]) -> str | None:
    """The citation for a value: the last call that source made about it.

    Connectors put the detail call after the search call, and the detail call is
    the one carrying the payload the value was read out of.
    """
    for result in results:
        if result.kind == kind and result.sources:
            return result.sources[-1].id
    return None


def pick(field: str, facts: Sequence[FactRecord]) -> tuple[FactRecord | None, str]:
    """Choose the value to publish for one field, and say how much to trust it.

    Plain source precedence, with one documented exception: for a safety flag,
    a source claiming toxicity outranks a source denying it, whatever the table
    says. The citation then points at the source that made the claim, because a
    citation that does not support its value is not a citation.
    """
    if not facts:
        return None, "unknown"

    candidates = list(facts)
    disagreement_penalty = 0
    if field in SAFETY_FIELDS:
        toxic = [f for f in facts if bool(f.value)]
        if toxic and len(toxic) != len(facts):
            candidates, disagreement_penalty = toxic, 1

    values = [
        SourcedValue(field=field, value=f.value, source_kind=f.source_kind, unit=f.unit)
        for f in candidates
    ]
    best_value, confidence = choose(values)
    if best_value is None:
        return None, "unknown"

    best = min(
        (f for f in candidates if f.source_kind == best_value.source_kind),
        key=lambda f: SOURCE_RANK.get(f.source_kind, 9),
    )
    return best, downgrade(confidence, disagreement_penalty)


def synthesise(species: SpeciesRef, results: Sequence[ConnectorResult]) -> Enrichment:
    """Turn what every source said into columns, cited care values and sources."""
    facts = _facts_by_field(results)
    sources = tuple(s for result in results for s in result.sources)
    errors = {r.kind: r.error for r in results if r.error}

    columns: dict[str, Any] = {}
    care_values: list[CareValue] = []

    for field in (*CARE_FIELDS, *DESCRIPTIVE_FIELDS):
        best, confidence = pick(field, facts.get(field, ()))
        if best is None and field not in ALWAYS_REPORT:
            continue
        if best is not None:
            columns[field] = best.value
        care_values.append(
            CareValue(
                field=field,
                value=best.value if best else None,
                confidence=confidence,
                source_id=_source_id_for(best.source_kind, results) if best else None,
                unit=(best.unit if best else None) or FIELD_UNITS.get(field),
                note=best.note if best else None,
            )
        )

    for field in IDENTIFIER_FIELDS:
        best, _ = pick(field, facts.get(field, ()))
        if best is not None and not getattr(species, field, None):
            columns[field] = best.value

    return Enrichment(
        species=species,
        columns=columns,
        care_values=tuple(care_values),
        sources=sources,
        errors=errors,
    )
