"""The shape every source connector has.

an earlier release ships two — POWO and GBIF. the earlier Wikipedia, Wikidata, USDA and Perenual
connectors slot into the same three parts, and so should anything after them:

1. a **fetcher**, which is the only thing that touches the network, so every
   parser is testable against a recorded payload;
2. **pure parse functions** over a payload, returning ``TaxonRecord``s;
3. a **connector** binding the two, returning the records *and* the
   ``SourceRecord`` that cites them.

A connector never decides what to publish. Ranking and confidence happen once,
in ``resolve.py``, over everything every connector returned.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from ..names import ParsedName
from ..sources import SourceRecord

#: How a source matched what the user typed. Ordered best to worst; the ranking
#: step turns these into a score, and a weaker kind lowers confidence.
MATCH_KINDS = ("exact", "vernacular", "fuzzy", "higher_rank", "partial")

MATCH_WEIGHT: dict[str, float] = {
    "exact": 1.0,
    "vernacular": 0.92,
    "fuzzy": 0.78,
    "higher_rank": 0.7,
    "partial": 0.6,
}


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One payload, and the request that produced it."""

    url: str
    payload: Any
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    from_cache: bool = False
    is_mock: bool = False


@runtime_checkable
class Fetcher(Protocol):
    """The only thing in the worker that is allowed to touch the network."""

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class TaxonRecord:
    """One source's answer about one taxon.

    Every field here was read out of a payload. Nothing on this record is
    computed, inferred or filled in with a likely value — that is the whole
    point, and it is why ranking lives somewhere else.
    """

    accepted_name: str
    source_kind: str
    rank: str = "species"
    family: str | None = None
    genus: str | None = None
    common_name: str | None = None
    gbif_key: str | None = None
    powo_id: str | None = None
    authorship: str | None = None
    #: The name the source actually matched, which may be a synonym of the
    #: accepted one — that is how "Sansevieria" arrives at "Dracaena".
    matched_name: str | None = None
    #: ``accepted`` | ``synonym`` | ``unknown``, as the source reported it.
    status: str = "unknown"
    match_kind: str = "exact"
    #: The source's own confidence in the match, 0..1, where it offers one.
    source_score: float = 1.0

    @property
    def is_synonym(self) -> bool:
        return self.status == "synonym"


@dataclass(frozen=True, slots=True)
class FactRecord:
    """One source's answer about one field of the care profile.

    ``field`` is a column on ``species`` (``min_temp_c``, ``soil_ph_min``,
    ``toxic_to_pets``, ``summary`` …) so synthesis never has to translate names.

    ``value`` is what we would publish; ``raw`` is what the source literally
    said, before any unit conversion or vocabulary mapping. Both are kept: the
    raw form is what an auditor checks the conversion against, and no field is
    ever filled from anything but a payload.
    """

    field: str
    value: object
    source_kind: str
    unit: str | None = None
    #: Exactly what the source said, pre-conversion (``'-43'`` °F, ``'Severe'``).
    raw: object = None
    #: How the value was arrived at, for the audit trail and the UI's tooltip.
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    """What one connector came back with, including the citation for it."""

    kind: str
    records: tuple[TaxonRecord, ...] = ()
    #: Care-profile facts. A taxon connector returns none and vice versa;
    #: one shape carries both so the registry and the citation path are shared.
    facts: tuple[FactRecord, ...] = ()
    #: One per call made. Kept even when a call returned nothing, so an empty
    #: answer is as auditable as a full one.
    sources: tuple[SourceRecord, ...] = ()
    #: Set when the source could not be reached. A source that is down must not
    #: look like a source that said "no such plant".
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class SpeciesRef:
    """What enrichment knows about a species before it asks anybody.

    The output of an earlier release resolution, and the input to every an earlier release
    connector: they look
    a species up by the name an authority accepted, not by what was typed.
    """

    accepted_name: str
    common_name: str | None = None
    family: str | None = None
    genus: str | None = None
    gbif_key: str | None = None
    powo_id: str | None = None
    #: Set once Wikipedia has been asked; Wikidata reuses it rather than
    #: searching again.
    wikidata_id: str | None = None


@runtime_checkable
class Connector(Protocol):
    """A source that can be asked to resolve a name."""

    kind: str

    async def resolve(self, parsed: ParsedName) -> ConnectorResult: ...


@runtime_checkable
class EnrichmentConnector(Protocol):
    """A source that can be asked what it knows about a resolved species."""

    kind: str

    async def enrich(self, species: SpeciesRef) -> ConnectorResult: ...


#: Connector factories by source kind, so a new source is a module and a
#: registration rather than another branch in the resolver. A source may answer
#: either question — ``resolve`` a name, ``enrich`` a species, or both — and the
#: registry holds them together because the citation path is the same.
AnyConnector = Connector | EnrichmentConnector

_REGISTRY: dict[str, Callable[..., AnyConnector]] = {}


def register(kind: str, factory: Callable[..., AnyConnector]) -> None:
    _REGISTRY[kind] = factory


def registered() -> Mapping[str, Callable[..., AnyConnector]]:
    return dict(_REGISTRY)


def build(kind: str, *args: Any, **kwargs: Any) -> AnyConnector:
    if kind not in _REGISTRY:
        raise KeyError(
            f"no connector registered for {kind!r}; registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[kind](*args, **kwargs)


def empty_result(kind: str, error: str | None = None) -> ConnectorResult:
    return ConnectorResult(kind=kind, records=(), sources=(), error=error)
