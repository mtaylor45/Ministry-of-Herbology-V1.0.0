"""Asking every source about one species, and handing the answers to synthesis.

The earlier counterpart of ``resolve.TaxonResolver``: it gathers, it does not decide.
Deciding is ``enrichment.synthesise``.

One ordering constraint, and it is a saving rather than a rule: Wikipedia's
summary payload carries the Wikidata item id, so Wikipedia is asked first and
Wikidata is handed the id instead of searching for the article again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .connectors.base import ConnectorResult, SpeciesRef
from .connectors.wikipedia import KIND as WIKIPEDIA_KIND
from .connectors.wikipedia import wikidata_id
from .enrichment import Enrichment, synthesise


class SpeciesEnricher:
    """A resolved species in, a cited care profile out."""

    def __init__(self, connectors: Sequence[Any]) -> None:
        self.connectors = tuple(connectors)

    def _split(self) -> tuple[list[Any], list[Any]]:
        first = [
            c for c in self.connectors if getattr(c, "kind", None) == WIKIPEDIA_KIND
        ]
        return first, [c for c in self.connectors if c not in first]

    async def enrich(self, species: SpeciesRef) -> Enrichment:
        results: list[ConnectorResult] = []
        wikipedia, rest = self._split()

        for connector in wikipedia:
            result = await self._ask(connector, species)
            results.append(result)
            found = _wikidata_id_from(result)
            if found and not species.wikidata_id:
                species = replace(species, wikidata_id=found)

        gathered = await asyncio.gather(
            *(self._ask(connector, species) for connector in rest),
            return_exceptions=True,
        )
        for connector, outcome in zip(rest, gathered, strict=True):
            if isinstance(outcome, BaseException):
                # A connector that raises is a source that is down, not a source
                # that said the plant has no care requirements.
                results.append(
                    ConnectorResult(
                        kind=getattr(connector, "kind", "other"),
                        error=f"{type(outcome).__name__}: {outcome}",
                    )
                )
            else:
                results.append(outcome)

        return synthesise(species, results)

    @staticmethod
    async def _ask(connector: Any, species: SpeciesRef) -> ConnectorResult:
        try:
            return await connector.enrich(species)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            return ConnectorResult(
                kind=getattr(connector, "kind", "other"),
                error=f"{type(exc).__name__}: {exc}",
            )


def _wikidata_id_from(result: ConnectorResult) -> str | None:
    for source in result.sources:
        found = wikidata_id(source.payload if isinstance(source.payload, dict) else {})
        if found:
            return found
    return None
