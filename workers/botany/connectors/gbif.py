"""GBIF Backbone Taxonomy connector.

GBIF is the aggregator: a little less authoritative than Kew on nomenclature,
but it fuzzy-matches misspellings, knows vernacular names in fifty languages,
and answers without an API key. It is what makes "snake plant" and "Monstra
deliciosa" resolve at all.

Endpoints used, all public and documented at https://techdocs.gbif.org/:

* ``/species/match`` — one name in, GBIF's best backbone match out, with
  ``alternatives`` when ``verbose=true``;
* ``/species/search`` — free text over the backbone, including vernacular names,
  which is the path a common name takes;
* ``/species/{key}/vernacularNames`` — the common name to show for a match.
"""

from __future__ import annotations

from typing import Any

from ..names import ParsedName, similarity
from ..sources import build_source
from .base import ConnectorResult, Fetcher, TaxonRecord
from .base import register as _register

KIND = "gbif"

#: The GBIF Backbone Taxonomy dataset. Searching without it returns checklists
#: of every quality, including ones that disagree with the backbone.
BACKBONE_DATASET_KEY = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"

#: GBIF's ranks in the vocabulary the schema uses (``species.rank``). Anything
#: unlisted is passed through lowercased rather than rounded to a rank GBIF did
#: not report.
RANKS = {
    "SPECIES": "species",
    "SUBSPECIES": "subspecies",
    "VARIETY": "variety",
    "SUBVARIETY": "variety",
    "FORM": "variety",
    "GENUS": "genus",
}

_MATCH_KINDS = {
    "EXACT": "exact",
    "FUZZY": "fuzzy",
    "HIGHERRANK": "higher_rank",
    "NONE": None,
}

#: Below this, GBIF's own match confidence is weak enough to be worth a second
#: look through the vernacular index before we answer.
WEAK_MATCH_CONFIDENCE = 90


def _text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _key(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) or (isinstance(value, str) and value):
            return str(value)
    return None


def _status(raw: str | None) -> str:
    if raw in {"ACCEPTED", "DOUBTFUL"}:
        return "accepted" if raw == "ACCEPTED" else "unknown"
    if raw in {
        "SYNONYM",
        "HETEROTYPIC_SYNONYM",
        "HOMOTYPIC_SYNONYM",
        "PROPARTE_SYNONYM",
    }:
        return "synonym"
    return "unknown"


def _accepted_name(entry: dict[str, Any], status: str) -> str | None:
    """What GBIF says the *accepted* name is, never what we would guess it is."""
    if status == "synonym":
        # ``species`` on a match carries the accepted species name; on a search
        # result the synonym's accepted parent is what ``species`` holds too.
        return _text(entry, "species") or None
    return _text(entry, "canonicalName") or _text(entry, "species")


def _record_from_entry(
    entry: dict[str, Any],
    parsed: ParsedName,
    *,
    match_kind: str,
    source_score: float,
    common_name: str | None = None,
) -> TaxonRecord | None:
    status = _status(_text(entry, "status") or _text(entry, "taxonomicStatus"))
    accepted = _accepted_name(entry, status)
    if not accepted:
        return None
    rank_raw = _text(entry, "rank") or ""
    return TaxonRecord(
        accepted_name=accepted,
        source_kind=KIND,
        rank=RANKS.get(rank_raw, rank_raw.lower() or parsed.rank_hint),
        family=_text(entry, "family"),
        genus=_text(entry, "genus"),
        common_name=common_name,
        gbif_key=_key(entry, "acceptedUsageKey", "speciesKey", "usageKey", "key"),
        powo_id=None,
        authorship=_text(entry, "authorship"),
        matched_name=_text(entry, "canonicalName") or _text(entry, "scientificName"),
        status=status,
        match_kind=match_kind,
        source_score=source_score,
    )


def parse_match(payload: dict[str, Any], parsed: ParsedName) -> tuple[TaxonRecord, ...]:
    """Records from ``/species/match``: the best match, then its alternatives."""
    records: list[TaxonRecord] = []
    for entry, is_alternative in [(payload, False)] + [
        (alt, True) for alt in payload.get("alternatives") or []
    ]:
        match_kind = _MATCH_KINDS.get(_text(entry, "matchType") or "", "partial")
        if match_kind is None:
            continue
        confidence = entry.get("confidence")
        score = (
            float(confidence) / 100.0 if isinstance(confidence, int | float) else 0.5
        )
        if is_alternative:
            # GBIF ranks its alternatives below its pick; so do we.
            score *= 0.9
        record = _record_from_entry(
            entry, parsed, match_kind=match_kind, source_score=min(score, 1.0)
        )
        if record:
            records.append(record)
    return tuple(records)


def _best_vernacular(
    names: list[dict[str, Any]], parsed: ParsedName
) -> tuple[str | None, float]:
    """The English common name closest to what the user typed, and how close.

    GBIF checklists sometimes pack a dozen names into one comma-separated
    string, so each part is considered separately.
    """
    best: tuple[str | None, float] = (None, 0.0)
    wanted = parsed.text
    for entry in names:
        if entry.get("language") not in {"eng", None}:
            continue
        raw = entry.get("vernacularName")
        if not isinstance(raw, str):
            continue
        for part in (p.strip() for p in raw.split(",")):
            if not part:
                continue
            score = similarity(wanted, part)
            if entry.get("preferred"):
                score = min(1.0, score + 0.02)
            if score > best[1]:
                best = (part, score)
    return best


def parse_search(
    payload: dict[str, Any], parsed: ParsedName
) -> tuple[TaxonRecord, ...]:
    """Records from ``/species/search`` — the path a common name takes."""
    records: list[TaxonRecord] = []
    for entry in payload.get("results") or []:
        common_name, vernacular_score = _best_vernacular(
            entry.get("vernacularNames") or [], parsed
        )
        name_score = similarity(parsed.lookup, _text(entry, "canonicalName") or "")
        if vernacular_score >= name_score:
            match_kind, score = "vernacular", vernacular_score
        else:
            match_kind, score = (
                "exact" if name_score > 0.999 else "partial"
            ), name_score
        record = _record_from_entry(
            entry,
            parsed,
            match_kind=match_kind,
            source_score=round(score, 4),
            common_name=common_name,
        )
        if record:
            records.append(record)
    return tuple(records)


#: Below this, the closest vernacular name is not an answer to what was typed —
#: it is just the nearest string — so the list's own first choice is better.
_VERNACULAR_ECHO_FLOOR = 0.6


def parse_vernacular_names(payload: dict[str, Any], parsed: ParsedName) -> str | None:
    """The common name to show beside a match, or ``None`` if GBIF has no English one.

    Somebody who typed a scientific name gets the name the checklists lead with,
    not whichever vernacular happens to look most like Latin.
    """
    entries = payload.get("results") or []
    best, score = _best_vernacular(entries, parsed)
    if best and not parsed.scientific and score >= _VERNACULAR_ECHO_FLOOR:
        return best
    for entry in sorted(entries, key=lambda e: not e.get("preferred")):
        if entry.get("language") not in {"eng", None}:
            continue
        raw = entry.get("vernacularName")
        if isinstance(raw, str) and raw.strip():
            return raw.split(",")[0].strip()
    return best


def needs_vernacular_lookup(records: tuple[TaxonRecord, ...]) -> bool:
    """True when ``/species/match`` answered but nothing carries a common name."""
    return bool(records) and all(r.common_name is None for r in records)


def _is_weak(records: tuple[TaxonRecord, ...]) -> bool:
    if not records:
        return True
    best = records[0]
    return (
        best.match_kind in {"higher_rank", "partial"}
        or best.source_score < WEAK_MATCH_CONFIDENCE / 100.0
    )


class GbifConnector:
    """Asks GBIF, twice at most, and cites every call."""

    kind = KIND

    def __init__(
        self, fetcher: Fetcher, base_url: str = "https://api.gbif.org/v1"
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def resolve(self, parsed: ParsedName) -> ConnectorResult:
        from .http import SourceUnavailable

        records: list[TaxonRecord] = []
        sources = []
        try:
            if parsed.scientific:
                fetched = await self.fetcher.get_json(
                    KIND,
                    f"{self.base_url}/species/match",
                    {"name": parsed.scientific, "strict": "false", "verbose": "true"},
                )
                sources.append(
                    build_source(
                        KIND,
                        fetched.url,
                        fetched.payload,
                        title_suffix=f"name match for {parsed.scientific}",
                        retrieved_at=fetched.retrieved_at,
                        is_mock=fetched.is_mock,
                    )
                )
                records.extend(parse_match(fetched.payload, parsed))

            if _is_weak(tuple(records)):
                fetched = await self.fetcher.get_json(
                    KIND,
                    f"{self.base_url}/species/search",
                    {
                        "q": parsed.text,
                        "rank": "SPECIES",
                        "datasetKey": BACKBONE_DATASET_KEY,
                        "limit": 5,
                    },
                )
                sources.append(
                    build_source(
                        KIND,
                        fetched.url,
                        fetched.payload,
                        title_suffix=f"search for {parsed.text}",
                        retrieved_at=fetched.retrieved_at,
                        is_mock=fetched.is_mock,
                    )
                )
                records.extend(parse_search(fetched.payload, parsed))

            if needs_vernacular_lookup(tuple(records)) and records[0].gbif_key:
                fetched = await self.fetcher.get_json(
                    KIND,
                    f"{self.base_url}/species/{records[0].gbif_key}/vernacularNames",
                    {"limit": 100},
                )
                sources.append(
                    build_source(
                        KIND,
                        fetched.url,
                        fetched.payload,
                        title_suffix=f"vernacular names for {records[0].accepted_name}",
                        retrieved_at=fetched.retrieved_at,
                        is_mock=fetched.is_mock,
                    )
                )
                common = parse_vernacular_names(fetched.payload, parsed)
                if common:
                    first, rest = records[0], records[1:]
                    records = [
                        TaxonRecord(**{**_as_dict(first), "common_name": common}),
                        *rest,
                    ]
        except SourceUnavailable as exc:
            return ConnectorResult(
                kind=KIND,
                records=tuple(records),
                sources=tuple(sources),
                error=str(exc),
            )

        return ConnectorResult(
            kind=KIND, records=tuple(records), sources=tuple(sources)
        )


def _as_dict(record: TaxonRecord) -> dict[str, Any]:
    return {f: getattr(record, f) for f in TaxonRecord.__slots__}


_register(KIND, GbifConnector)
