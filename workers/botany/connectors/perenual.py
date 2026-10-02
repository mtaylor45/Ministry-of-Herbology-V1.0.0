"""Perenual connector — off by default, and the free path does not need it.

the design settled this: free and openly licensed sources only. Perenual stays
behind ``MOH_PERENUAL_API_KEY``, unset, and enrichment must be *complete*
without it rather than degraded-but-shipping. Nothing here is on the path of a
default install; ``build_enrichment_connectors`` only constructs it when a key
is configured.

It is written anyway, for the day the decision is revisited: the parser is
real, it reads Perenual's documented ``/api/species-list`` and
``/api/species/details/{id}`` shapes, and it is covered by tests that use a
payload about a plant that does not exist — the shape is what is being tested,
and a recording of real Perenual data would be neither free nor openly licensed
to commit (see ``mocks/recorded/PROVENANCE.md``).

Two things it will never do, key or no key: publish a number Perenual did not
state, and rank above POWO, GBIF or USDA. Its place in ``SOURCE_RANK`` puts it
below all three.
"""

from __future__ import annotations

from typing import Any

from ..sources import build_source
from .base import ConnectorResult, FactRecord, Fetcher, SpeciesRef
from .base import register as _register

KIND = "perenual"

#: Perenual's watering vocabulary. Frequent/Average/Minimum are categories, and
#: they stay categories: there is no interval in days behind them to publish.
_UNMAPPED_CATEGORICALS = ("watering", "growth_rate", "care_level")

SUNLIGHT_TO_LIGHT = {
    "full sun": "full_sun",
    "part sun": "part_shade",
    "part shade": "part_shade",
    "part sun/part shade": "part_shade",
    "sun-part shade": "part_shade",
    "filtered shade": "part_shade",
    "full shade": "low_light",
    "deep shade": "low_light",
}


def _first_match(payload: dict[str, Any], species: SpeciesRef) -> dict[str, Any] | None:
    from ..names import merge_key

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    wanted = merge_key(species.accepted_name)
    for entry in data:
        if not isinstance(entry, dict):
            continue
        names = entry.get("scientific_name") or []
        names = names if isinstance(names, list) else [names]
        if any(merge_key(str(n)) == wanted for n in names):
            return entry
    return None


def parse_details(
    payload: dict[str, Any], species: SpeciesRef
) -> tuple[FactRecord, ...]:
    """Only the fields Perenual states outright. Categories stay categories."""
    if not isinstance(payload, dict):
        return ()
    facts: list[FactRecord] = []

    sunlight = payload.get("sunlight")
    if isinstance(sunlight, list) and sunlight:
        label = SUNLIGHT_TO_LIGHT.get(str(sunlight[0]).strip().lower())
        if label:
            facts.append(
                FactRecord(
                    field="light_label",
                    value=label,
                    source_kind=KIND,
                    raw=sunlight,
                    note=f"Perenual sunlight: {sunlight[0]!r}.",
                )
            )

    for key, field in (
        ("poisonous_to_pets", "toxic_to_pets"),
        ("poisonous_to_humans", "toxic_to_children"),
    ):
        value = payload.get(key)
        if value is None:
            continue
        # Perenual sends 0/1; anything truthy is a toxicity claim, and a
        # toxicity claim is believed in the safe direction.
        facts.append(
            FactRecord(field=field, value=bool(value), source_kind=KIND, raw=value)
        )

    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        facts.append(
            FactRecord(
                field="summary",
                value=description.strip(),
                source_kind=KIND,
                raw=description,
            )
        )
    return tuple(facts)


class PerenualConnector:
    """Search, then details. Constructed only when a key is configured."""

    kind = KIND

    def __init__(
        self, fetcher: Fetcher, api_key: str, base_url: str = "https://perenual.com/api"
    ) -> None:
        if not api_key:
            # Not an accident worth debugging later: the design says this source is
            # off, and an unkeyed Perenual call would just be a 401 in the logs.
            raise ValueError(
                "PerenualConnector needs an API key; the design keeps it off by default"
            )
        self.fetcher = fetcher
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def enrich(self, species: SpeciesRef) -> ConnectorResult:
        from .http import SourceUnavailable

        sources = []
        try:
            found = await self.fetcher.get_json(
                KIND,
                f"{self.base_url}/species-list",
                {"key": self.api_key, "q": species.accepted_name},
            )
            sources.append(
                build_source(
                    KIND,
                    _without_key(found.url),
                    found.payload,
                    title_suffix=f"search for {species.accepted_name}",
                    retrieved_at=found.retrieved_at,
                    is_mock=found.is_mock,
                )
            )
            match = _first_match(found.payload, species)
            if not match or not match.get("id"):
                return ConnectorResult(kind=KIND, sources=tuple(sources))

            details = await self.fetcher.get_json(
                KIND,
                f"{self.base_url}/species/details/{match['id']}",
                {"key": self.api_key},
            )
            sources.append(
                build_source(
                    KIND,
                    _without_key(details.url),
                    details.payload,
                    title_suffix=species.accepted_name,
                    retrieved_at=details.retrieved_at,
                    is_mock=details.is_mock,
                )
            )
        except SourceUnavailable as exc:
            return ConnectorResult(kind=KIND, sources=tuple(sources), error=str(exc))

        return ConnectorResult(
            kind=KIND,
            facts=parse_details(details.payload, species),
            sources=tuple(sources),
        )


def _without_key(url: str) -> str:
    """A citation is shown to the user and stored; the API key is not."""
    import re

    return re.sub(r"([?&])key=[^&]*", r"\1key=REDACTED", url)


_register(KIND, PerenualConnector)
