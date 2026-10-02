"""Ranking what the sources said. The only place an answer is chosen.

Connectors report; this module decides. Deciding means two things and no third:
which of the names the sources returned to put first, and how much to trust it.
It never writes a name, a key or a family that no source returned — the design,
and the reason the whole path is testable against recorded payloads.

Confidence comes out of the precedence table in ``tasks.py`` (``choose``), then
gets *lowered* for anything that weakens the match: a fuzzy hit, a name only an
aggregator knows, an ambiguous common name, a runner-up. It is never raised.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .connectors.base import MATCH_WEIGHT, Connector, ConnectorResult, TaxonRecord
from .names import ParsedName, merge_key, parse_name
from .sources import SourceRecord
from .tasks import SOURCE_RANK, SourcedValue, choose, downgrade

#: Below this a candidate is noise, not a suggestion.
SCORE_FLOOR = 0.35

#: More than this many candidates is a list nobody reads.
MAX_CANDIDATES = 8

#: Two candidates closer than this are, for the user's purposes, a tie — which
#: is a reason to trust the top one less, not to hide the second.
AMBIGUITY_MARGIN = 0.1

#: Corroboration is worth something, but not as much as the match itself.
QUALITY_WEIGHT = 0.85
CORROBORATION_WEIGHT = 0.15


@dataclass(frozen=True, slots=True)
class TaxonCandidate:
    """One ranked answer, in the shape of the contract's ``TaxonCandidate``."""

    accepted_name: str
    confidence: str
    rank: str = "species"
    common_name: str | None = None
    family: str | None = None
    gbif_key: str | None = None
    powo_id: str | None = None
    score: float = 0.0
    #: The citation for this candidate: the highest-precedence source backing it.
    source: dict[str, Any] | None = None
    #: Split off the typed name, not returned by any source. POWO and GBIF index
    #: species, not cultivars, so ``'Hidcote'`` comes back here for the caller to
    #: store on the specimen (``specimen.cultivar``).
    cultivar: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_name": self.accepted_name,
            "common_name": self.common_name,
            "family": self.family,
            "rank": self.rank,
            "gbif_key": self.gbif_key,
            "powo_id": self.powo_id,
            "score": self.score,
            "confidence": self.confidence,
            "source": self.source,
            "cultivar": self.cultivar,
        }


@dataclass(frozen=True, slots=True)
class Resolution:
    """Everything one resolve produced, including what it would cite."""

    query: str
    parsed: ParsedName
    candidates: tuple[TaxonCandidate, ...] = ()
    #: Every call made, payload included, ready for the ``source`` table.
    sources: tuple[SourceRecord, ...] = ()
    #: Source kind → why it could not be asked. A source that is down must never
    #: read as a source that said "no such plant".
    errors: dict[str, str] | None = None

    @property
    def reachable(self) -> bool:
        return not self.errors or len(self.errors) < len(self._kinds)

    @property
    def _kinds(self) -> set[str]:
        return {s.kind for s in self.sources} | set(self.errors or {})

    def to_list(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.candidates]


def _record_quality(record: TaxonRecord) -> float:
    """How good this one source's match is, 0..1."""
    return round(MATCH_WEIGHT.get(record.match_kind, 0.6) * record.source_score, 4)


def _lead(records: Sequence[TaxonRecord]) -> TaxonRecord:
    """The record that speaks for a group: best source first, best match second."""
    return min(
        records,
        key=lambda r: (SOURCE_RANK.get(r.source_kind, 9), -_record_quality(r)),
    )


def _first(records: Sequence[TaxonRecord], attribute: str) -> Any:
    """The first non-empty value for an attribute, in source-precedence order."""
    for record in sorted(records, key=lambda r: SOURCE_RANK.get(r.source_kind, 9)):
        value = getattr(record, attribute)
        if value:
            return value
    return None


def _source_for(
    record: TaxonRecord, results: Sequence[ConnectorResult]
) -> dict[str, Any] | None:
    for result in results:
        if result.kind == record.source_kind and result.sources:
            return result.sources[0].to_ref()
    return None


def _group(results: Sequence[ConnectorResult]) -> dict[str, list[TaxonRecord]]:
    groups: dict[str, list[TaxonRecord]] = {}
    for result in results:
        for record in result.records:
            groups.setdefault(merge_key(record.accepted_name), []).append(record)
    return groups


def _base_confidence(results: Sequence[ConnectorResult]) -> str:
    """Trust in the query as a whole, from the precedence table in ``tasks.py``.

    One ``SourcedValue`` per source kind, carrying that source's own best answer.
    ``choose`` knows the precedence order and knows to lower the confidence when
    two trusted sources disagree, which is precisely the case where POWO and GBIF
    return different accepted names.
    """
    values: list[SourcedValue] = []
    for result in results:
        if not result.records:
            continue
        best = min(result.records, key=lambda r: -_record_quality(r))
        values.append(
            SourcedValue(
                field="accepted_name",
                value=merge_key(best.accepted_name),
                source_kind=result.kind,
            )
        )
    return choose(values)[1]


def _candidate_confidence(
    base: str, lead: TaxonRecord, *, is_top: bool, ambiguous: bool, score: float
) -> str:
    """Lower ``base`` for everything that makes this particular candidate weaker."""
    steps = 0
    if lead.match_kind in {"fuzzy", "higher_rank", "partial"}:
        steps += 1
    if lead.match_kind == "vernacular":
        # A common name is a nickname, not a citation: "snake plant" is several
        # plants in several countries, and no authority was asked by that name.
        steps += 1
        if ambiguous:
            # Four species answer to "mandrake". That is a suggestion, not a fact.
            steps += 1
    if not is_top:
        steps += 1
    confidence = downgrade(base, steps)
    if score < 0.5 and confidence in {"high", "medium"}:
        confidence = "low"
    return confidence


def rank_candidates(
    parsed: ParsedName, results: Sequence[ConnectorResult]
) -> tuple[TaxonCandidate, ...]:
    """Merge every source's records into one ranked list of candidates."""
    groups = _group(results)
    if not groups:
        return ()

    base = _base_confidence(results)
    scored: list[tuple[float, list[TaxonRecord]]] = []
    for records in groups.values():
        lead = _lead(records)
        kinds = {r.source_kind for r in records}
        corroborated = 1.0 if len(kinds) > 1 else 0.0
        score = round(
            QUALITY_WEIGHT * _record_quality(lead)
            + CORROBORATION_WEIGHT * corroborated,
            4,
        )
        scored.append((score, records))

    scored.sort(key=lambda pair: (-pair[0], _lead(pair[1]).accepted_name))
    top_score = scored[0][0]

    candidates: list[TaxonCandidate] = []
    for index, (score, records) in enumerate(scored):
        if score < SCORE_FLOOR:
            continue
        lead = _lead(records)
        ambiguous = len(scored) > 1 and abs(top_score - scored[1][0]) < AMBIGUITY_MARGIN
        candidates.append(
            TaxonCandidate(
                accepted_name=_first(records, "accepted_name") or lead.accepted_name,
                confidence=_candidate_confidence(
                    base, lead, is_top=index == 0, ambiguous=ambiguous, score=score
                ),
                rank=_first(records, "rank") or "species",
                common_name=_first(records, "common_name"),
                family=_first(records, "family"),
                gbif_key=_first(records, "gbif_key"),
                powo_id=_first(records, "powo_id"),
                score=score,
                source=_source_for(lead, results),
                cultivar=parsed.cultivar,
            )
        )
        if len(candidates) == MAX_CANDIDATES:
            break
    return tuple(candidates)


class TaxonResolver:
    """A typed name in, a ranked list of accepted names out."""

    def __init__(self, connectors: Sequence[Connector]) -> None:
        self.connectors = tuple(connectors)

    async def resolve(self, name: str) -> Resolution:
        parsed = parse_name(name)
        if not parsed.text:
            return Resolution(query=name, parsed=parsed)

        gathered = await asyncio.gather(
            *(connector.resolve(parsed) for connector in self.connectors),
            return_exceptions=True,
        )

        results: list[ConnectorResult] = []
        errors: dict[str, str] = {}
        sources: list[SourceRecord] = []
        for connector, outcome in zip(self.connectors, gathered, strict=True):
            if isinstance(outcome, BaseException):
                # A connector that raises is a connector that is down. Say so;
                # do not let it read as an absence of plants.
                errors[connector.kind] = f"{type(outcome).__name__}: {outcome}"
                continue
            results.append(outcome)
            sources.extend(outcome.sources)
            if outcome.error:
                errors[outcome.kind] = outcome.error

        return Resolution(
            query=name,
            parsed=parsed,
            candidates=rank_candidates(parsed, results),
            sources=tuple(sources),
            errors=errors or None,
        )
