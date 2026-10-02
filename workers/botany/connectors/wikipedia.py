"""Wikipedia connector — the Compendium's prose.

Wikipedia is last in the precedence table and it earns its place there: it is
the one source that writes a readable paragraph about a plant. It is *not* a
source of numbers. This connector takes the lead extract and the page's own
description, and nothing else — no watering interval inferred from a sentence,
no frost threshold read out of a range map. the design forbids originating a
value, and reading a number out of prose is originating one with extra steps.

Endpoint: ``/api/rest_v1/page/summary/{title}`` — one call, no key, and it
returns the Wikidata item id, which saves the Wikidata connector a lookup.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..sources import build_source
from .base import ConnectorResult, FactRecord, Fetcher, SpeciesRef
from .base import register as _register

KIND = "wikipedia"

#: Below this the extract is a stub ("X is a species of plant.") and not worth
#: showing as a Compendium entry.
MIN_SUMMARY_CHARS = 80

#: Pages the summary endpoint answers with but which are not about one plant.
_NON_ARTICLE_TYPES = {"disambiguation", "no-extract", "mainpage"}


def page_title(species: SpeciesRef) -> str:
    """Wikipedia titles the article at the accepted name, underscored."""
    return species.accepted_name.replace(" ", "_")


def parse_summary(
    payload: dict[str, Any], species: SpeciesRef
) -> tuple[FactRecord, ...]:
    """The lead paragraph, if the page is an article about this plant."""
    if not isinstance(payload, dict) or payload.get("type") in _NON_ARTICLE_TYPES:
        return ()
    extract = payload.get("extract")
    if not isinstance(extract, str) or len(extract.strip()) < MIN_SUMMARY_CHARS:
        return ()

    facts = [
        FactRecord(
            field="summary",
            value=extract.strip(),
            source_kind=KIND,
            raw=extract,
            note="Lead extract, quoted as written; not paraphrased.",
        )
    ]
    return tuple(facts)


def wikidata_id(payload: dict[str, Any]) -> str | None:
    """The Wikidata item this page is about, so Wikidata needs no search."""
    value = payload.get("wikibase_item") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value.startswith("Q") else None


def page_url(payload: dict[str, Any]) -> str | None:
    urls = payload.get("content_urls") if isinstance(payload, dict) else None
    if isinstance(urls, dict):
        desktop = urls.get("desktop")
        if isinstance(desktop, dict) and isinstance(desktop.get("page"), str):
            return desktop["page"]
    return None


class WikipediaConnector:
    """One call for the prose, and the Wikidata id that comes free with it."""

    kind = KIND

    def __init__(
        self, fetcher: Fetcher, base_url: str = "https://en.wikipedia.org/api/rest_v1"
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def enrich(self, species: SpeciesRef) -> ConnectorResult:
        from .http import SourceUnavailable

        title = page_title(species)
        try:
            fetched = await self.fetcher.get_json(
                KIND, f"{self.base_url}/page/summary/{quote(title, safe='')}"
            )
        except SourceUnavailable as exc:
            # A 404 here means "no article", which is an answer; the fetcher
            # cannot tell those apart, so an unreachable Wikipedia is reported
            # as unreachable and synthesis simply has no prose to publish.
            return ConnectorResult(kind=KIND, error=str(exc))

        source = build_source(
            KIND,
            page_url(fetched.payload) or fetched.url,
            fetched.payload,
            title_suffix=species.accepted_name,
            retrieved_at=fetched.retrieved_at,
            is_mock=fetched.is_mock,
        )
        return ConnectorResult(
            kind=KIND,
            facts=parse_summary(fetched.payload, species),
            sources=(source,),
        )


_register(KIND, WikipediaConnector)
