"""Replay recorded payloads, and fall back to the frozen fixtures."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode

from ..connectors.base import Connector, FetchResult
from ..connectors.gbif import GbifConnector
from ..connectors.powo import PowoConnector
from ..names import fold, parse_name, similarity
from ..settings import BotanySettings, get_settings

RECORDED_DIR = Path(__file__).resolve().parent / "recorded"

#: The day every payload in ``recorded/`` was fetched. A replay is cited with
#: this, not with the clock: a citation that claims to be fresh is a citation
#: that lies, and a git checkout's file timestamps say nothing about the source.
#: Re-record the directory, bump this, and say so in ``recorded/PROVENANCE.md``.
RECORDED_ON = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

#: A fixture name has to be this close to the query before the mock offers it.
FIXTURE_MATCH_FLOOR = 0.82


def slug(text: str) -> str:
    """``Citrus × limon`` → ``citrus-limon``; the filename half of a recording."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-") or "empty"


def recording_name(kind: str, url: str, params: dict[str, Any]) -> str | None:
    """Which file in ``recorded/`` answers this request, if any."""
    path = url.split("?", 1)[0].rstrip("/")
    if kind == "gbif":
        if path.endswith("/species/match"):
            return f"gbif/match__{slug(str(params.get('name', '')))}.json"
        if path.endswith("/species/search"):
            return f"gbif/search__{slug(str(params.get('q', '')))}.json"
        if path.endswith("/vernacularNames"):
            return f"gbif/vernacular__{path.split('/')[-2]}.json"
    if kind == "powo" and path.endswith("/search"):
        return f"powo/search__{slug(str(params.get('q', '')))}.json"
    if kind == "wikipedia" and "/page/summary/" in path:
        return f"wikipedia/summary__{slug(unquote(path.rsplit('/', 1)[-1]))}.json"
    if kind == "wikidata":
        if params.get("props") == "labels":
            return f"wikidata/labels__{slug(str(params.get('ids', '')))}.json"
        subject = params.get("titles") or params.get("ids") or ""
        return f"wikidata/entity__{slug(str(subject))}.json"
    if kind == "usda":
        if path.endswith("/PlantSearch"):
            return f"usda/search__{slug(str(params.get('searchText', '')))}.json"
        if "/PlantCharacteristics/" in path:
            return f"usda/characteristics__{path.rsplit('/', 1)[-1]}.json"
    return None


class RecordedFetcher:
    """A ``Fetcher`` that never opens a socket.

    Answers from ``recorded/`` first, then from the frozen species fixtures, then
    with the empty response each API returns when it knows nothing — which is a
    real answer the resolver has to handle, not an error.
    """

    def __init__(
        self, settings: BotanySettings | None = None, recorded_dir: Path | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.recorded_dir = recorded_dir or RECORDED_DIR
        #: Every request this fetcher served, for tests that count calls.
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._species: list[dict[str, Any]] | None = None

    @property
    def species(self) -> list[dict[str, Any]]:
        if self._species is None:
            path = self.settings.fixtures_dir / "species" / "species.json"
            self._species = json.loads(path.read_text()) if path.exists() else []
        return self._species

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        params = dict(params or {})
        self.calls.append((kind, url, params))
        full_url = f"{url}?{urlencode(params)}" if params else url

        name = recording_name(kind, url, params)
        if name:
            path = self.recorded_dir / name
            if path.exists():
                return FetchResult(
                    url=full_url,
                    payload=json.loads(path.read_text()),
                    retrieved_at=RECORDED_ON,
                    is_mock=True,
                )

        return FetchResult(
            url=full_url,
            payload=self._from_fixtures(kind, url, params),
            retrieved_at=RECORDED_ON,
            is_mock=True,
        )

    # ---------------------------------------------------------------- fixtures

    def _from_fixtures(self, kind: str, url: str, params: dict[str, Any]) -> Any:
        path = url.split("?", 1)[0].rstrip("/")
        query = str(params.get("name") or params.get("q") or "")

        if kind == "gbif" and path.endswith("/species/match"):
            row, score = self._best_fixture(query)
            return (
                _match_payload(row, score)
                if row
                else {
                    "confidence": 0,
                    "matchType": "NONE",
                    "synonym": False,
                    **_synthetic(),
                }
            )
        if kind == "gbif" and path.endswith("/species/search"):
            row, score = self._best_fixture(query)
            rows = [(row, score)] if row else []
            return {
                "offset": 0,
                "limit": 5,
                "endOfRecords": True,
                "count": len(rows),
                "results": [_search_result(r, s) for r, s in rows],
                **_synthetic(),
            }
        if kind == "gbif" and path.endswith("/vernacularNames"):
            return {
                "offset": 0,
                "limit": 100,
                "endOfRecords": True,
                "results": [],
                **_synthetic(),
            }
        if kind == "wikipedia":
            row, score = self._best_fixture(query or _title_from(path))
            return (
                _wikipedia_payload(row)
                if row
                else {"type": "no-extract", **_synthetic()}
            )
        if kind == "wikidata":
            return {"entities": {}, **_synthetic()}
        if kind == "usda":
            # USDA has a profile for most plants and characteristics for very
            # few. With nothing recorded, the mock says the same as the live
            # service does for seven of the eight fixture species: nothing.
            return []

        # POWO indexes names, not the fixtures' care profiles: for anything not
        # recorded it says nothing, and GBIF carries the mock on its own.
        return {
            "totalResults": 0,
            "page": 1,
            "perPage": 10,
            "totalPages": 0,
            "results": [],
            **_synthetic(),
        }

    def _best_fixture(self, query: str) -> tuple[dict[str, Any] | None, float]:
        parsed = parse_name(query)
        best: tuple[dict[str, Any] | None, float] = (None, 0.0)
        for row in self.species:
            scores = [similarity(parsed.lookup, row.get("accepted_name", ""))]
            scores += [
                similarity(parsed.text, c) for c in row.get("common_names") or []
            ]
            score = max(scores)
            if score > best[1]:
                best = (row, score)
        return best if best[1] >= FIXTURE_MATCH_FLOOR else (None, 0.0)


def _synthetic() -> dict[str, Any]:
    """Stamped into every fixture-derived payload, so a mock cannot pass for a source."""
    return {
        "_synthetic": {
            "from": "fixtures/species/species.json",
            "note": "Mock mode. Built from the frozen fixtures, not fetched from the API.",
        }
    }


def _match_payload(row: dict[str, Any], score: float) -> dict[str, Any]:
    name = row.get("accepted_name", "")
    return {
        "usageKey": row.get("gbif_key"),
        "scientificName": name,
        "canonicalName": name,
        "rank": (row.get("rank") or "species").upper(),
        "status": "ACCEPTED",
        # The match score is the fixture name's own similarity to the query, not
        # a number anybody made up.
        "confidence": round(score * 100),
        "matchType": "EXACT" if score > 0.999 else "FUZZY",
        "family": row.get("family"),
        "genus": row.get("genus"),
        "species": name,
        **_synthetic(),
    }


def _search_result(row: dict[str, Any], score: float) -> dict[str, Any]:
    payload = _match_payload(row, score)
    payload["taxonomicStatus"] = payload.pop("status")
    payload["key"] = row.get("gbif_key")
    payload["vernacularNames"] = [
        {"vernacularName": c, "language": "eng"} for c in row.get("common_names") or []
    ]
    return payload


def _title_from(path: str) -> str:
    return unquote(path.rsplit("/", 1)[-1]).replace("_", " ")


def _wikipedia_payload(row: dict[str, Any]) -> dict[str, Any]:
    """A summary payload carrying the fixture's own Compendium prose.

    The fixtures ship a `summary` for each species; mock mode serves that rather
    than a paragraph invented here.
    """
    name = row.get("accepted_name", "")
    return {
        "type": "standard",
        "title": name,
        "extract": row.get("summary") or "",
        "description": "Species of plant",
        "content_urls": {
            "desktop": {
                "page": f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}"
            }
        },
        **_synthetic(),
    }


def build_mock_connectors(settings: BotanySettings | None = None) -> list[Connector]:
    """POWO and GBIF, wired to recordings instead of the network."""
    settings = settings or get_settings()
    fetcher = RecordedFetcher(settings)
    return [
        PowoConnector(fetcher, settings.powo_base_url),
        GbifConnector(fetcher, settings.gbif_base_url),
    ]


def build_mock_enrichment_connectors(
    settings: BotanySettings | None = None,
) -> list[Any]:
    """USDA, Wikidata and Wikipedia, wired to recordings instead of the network.

    Perenual is absent rather than mocked: the design keeps it off, and a mock of
    a source nobody may call would only prove the mock works.
    """
    from ..connectors.usda import UsdaConnector
    from ..connectors.wikidata import WikidataConnector
    from ..connectors.wikipedia import WikipediaConnector

    settings = settings or get_settings()
    fetcher = RecordedFetcher(settings)
    return [
        UsdaConnector(fetcher),
        WikidataConnector(fetcher),
        WikipediaConnector(fetcher),
    ]
