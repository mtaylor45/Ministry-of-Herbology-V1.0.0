"""Plants of the World Online (Kew) connector.

POWO is the nomenclatural authority in the precedence table: where Kew and an
aggregator disagree about which name is accepted, Kew wins and GBIF's answer
becomes corroboration. POWO's public API 2 is the one ``pykew`` speaks:

* ``/api/2/search?q=<name>`` — full-text search over accepted names and synonyms;
* ``/api/2/taxon/{fqId}`` — one taxon by its IPNI LSID.

A synonym comes back as ``accepted: false`` carrying a ``synonymOf`` block, which
is how *Sansevieria trifasciata* arrives at *Dracaena trifasciata* with Kew's
name for it rather than ours.

Reachability: powo.science.kew.org sits behind a bot challenge that answers some
clients with HTML instead of JSON. ``HttpFetcher`` treats that as *unreachable*,
never as "no such plant", so a challenged call lowers confidence and leaves GBIF
to answer — it can never invent one. See ``mocks/recorded/PROVENANCE.md``.
"""

from __future__ import annotations

from typing import Any

from ..names import ParsedName, similarity
from ..sources import build_source
from .base import ConnectorResult, Fetcher, TaxonRecord
from .base import register as _register

KIND = "powo"

#: POWO's ranks in the vocabulary the schema uses (``species.rank``).
RANKS = {
    "species": "species",
    "subspecies": "subspecies",
    "subsp.": "subspecies",
    "variety": "variety",
    "var.": "variety",
    "form": "variety",
    "f.": "variety",
    "genus": "genus",
    "hybrid": "hybrid",
}

#: An IPNI LSID is POWO's taxon id; the URL carries it and so does ``fqId``.
_LSID_PREFIX = "urn:lsid:ipni.org:names:"


def _text(entry: dict[str, Any], key: str) -> str | None:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def powo_id(entry: dict[str, Any]) -> str | None:
    """The IPNI LSID, from ``fqId`` or dug out of the taxon URL."""
    fq_id = _text(entry, "fqId")
    if fq_id:
        return fq_id
    url = _text(entry, "url") or ""
    marker = "/taxon/"
    if marker in url:
        candidate = url.split(marker, 1)[1].strip("/")
        if candidate.startswith(_LSID_PREFIX):
            return candidate
    return None


def taxon_url(entry: dict[str, Any]) -> str | None:
    identifier = powo_id(entry)
    return f"https://powo.science.kew.org/taxon/{identifier}" if identifier else None


def _rank(entry: dict[str, Any], parsed: ParsedName) -> str:
    raw = (_text(entry, "rank") or "").lower()
    return RANKS.get(raw, raw or parsed.rank_hint)


def _record(entry: dict[str, Any], parsed: ParsedName) -> TaxonRecord | None:
    name = _text(entry, "name")
    if not name:
        return None

    accepted_flag = entry.get("accepted")
    synonym_of = (
        entry.get("synonymOf") if isinstance(entry.get("synonymOf"), dict) else None
    )

    if accepted_flag is False and synonym_of:
        accepted_name = _text(synonym_of, "name") or name
        status = "synonym"
        identifier = powo_id(synonym_of) or powo_id(entry)
        authorship = _text(synonym_of, "author")
    elif accepted_flag is False:
        # Kew does not accept this name and did not say what replaces it. That is
        # a weaker answer, not a licence to pick a replacement ourselves.
        accepted_name, status = name, "unknown"
        identifier, authorship = powo_id(entry), _text(entry, "author")
    else:
        accepted_name, status = name, "accepted"
        identifier, authorship = powo_id(entry), _text(entry, "author")

    score = similarity(parsed.lookup, name)
    match_kind = "exact" if score > 0.999 else ("fuzzy" if score >= 0.82 else "partial")
    if status == "unknown":
        score *= 0.8

    return TaxonRecord(
        accepted_name=accepted_name,
        source_kind=KIND,
        rank=_rank(entry, parsed),
        family=_text(entry, "family"),
        genus=_text(entry, "genus") or accepted_name.split(" ")[0] or None,
        common_name=None,
        gbif_key=None,
        powo_id=identifier,
        authorship=authorship,
        matched_name=name,
        status=status,
        match_kind=match_kind,
        source_score=round(min(score, 1.0), 4),
    )


def parse_search(
    payload: dict[str, Any], parsed: ParsedName
) -> tuple[TaxonRecord, ...]:
    """Records from ``/api/2/search``, best first, as POWO ordered them."""
    records = []
    for entry in payload.get("results") or []:
        if not isinstance(entry, dict):
            continue
        record = _record(entry, parsed)
        if record:
            records.append(record)
    return tuple(records)


def parse_taxon(payload: dict[str, Any], parsed: ParsedName) -> TaxonRecord | None:
    """One record from ``/api/2/taxon/{fqId}``."""
    if not isinstance(payload, dict) or not payload.get("name"):
        return None
    entry = dict(payload)
    classification = payload.get("classification")
    if isinstance(classification, dict):
        entry.setdefault("family", classification.get("family"))
        entry.setdefault("genus", classification.get("genus"))
    if payload.get("synonym") and isinstance(payload.get("accepted"), dict):
        entry["accepted"] = False
        entry["synonymOf"] = payload["accepted"]
    return _record(entry, parsed)


class PowoConnector:
    """Asks Kew, and cites the call whether or not it answered."""

    kind = KIND

    def __init__(
        self, fetcher: Fetcher, base_url: str = "https://powo.science.kew.org/api/2"
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def resolve(self, parsed: ParsedName) -> ConnectorResult:
        from .http import SourceUnavailable

        if not parsed.lookup:
            return ConnectorResult(kind=KIND)
        try:
            fetched = await self.fetcher.get_json(
                KIND, f"{self.base_url}/search", {"q": parsed.lookup, "perPage": 10}
            )
        except SourceUnavailable as exc:
            return ConnectorResult(kind=KIND, error=str(exc))

        source = build_source(
            KIND,
            fetched.url,
            fetched.payload,
            title_suffix=f"search for {parsed.lookup}",
            retrieved_at=fetched.retrieved_at,
            is_mock=fetched.is_mock,
        )
        return ConnectorResult(
            kind=KIND, records=parse_search(fetched.payload, parsed), sources=(source,)
        )


_register(KIND, PowoConnector)
