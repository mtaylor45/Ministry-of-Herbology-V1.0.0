"""Wikidata connector — the structured half of the encyclopaedia.

Where Wikipedia has a paragraph, Wikidata has statements: common names in a
named language, the native range as items rather than adjectives, and the GBIF
and POWO identifiers, which is how a Wikidata answer can be checked against the
authorities that outrank it.

Endpoints, both on ``/w/api.php`` and neither needing a key:

* ``wbgetentities`` by item id, or by ``enwiki`` page title when Wikipedia has
  not already handed us the id;
* a second ``wbgetentities`` for the labels of the items a range statement
  points at — ``Q96`` means nothing to a gardener, ``Mexico`` does.
"""

from __future__ import annotations

from typing import Any

from ..sources import build_source
from .base import ConnectorResult, FactRecord, Fetcher, SpeciesRef
from .base import register as _register

KIND = "wikidata"

#: Taxon common name. Language-tagged, so "cheese plant" and "Gatenplant" are
#: separable without guessing.
P_COMMON_NAME = "P1843"
#: Indigenous to — the closest Wikidata has to a native range.
P_INDIGENOUS_TO = "P2341"
#: The identifiers that let an aggregator's answer be checked against Kew.
P_GBIF_ID = "P846"
#: POWO id, as a full IPNI LSID.
P_POWO_ID = "P5037"
P_TAXON_NAME = "P225"

#: One language. A Compendium in mixed languages is worse than none.
LANGUAGE = "en"

#: More than this and it is a list, not a name.
MAX_COMMON_NAMES = 6


def _claims(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict):
        return None, {}
    for item_id, entity in entities.items():
        if not isinstance(entity, dict) or "missing" in entity:
            continue
        claims = entity.get("claims")
        return item_id, claims if isinstance(claims, dict) else {}
    return None, {}


def _values(claims: dict[str, Any], prop: str) -> list[Any]:
    out: list[Any] = []
    for statement in claims.get(prop) or []:
        if not isinstance(statement, dict):
            continue
        # A deprecated statement is one Wikidata itself no longer stands behind.
        if statement.get("rank") == "deprecated":
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        value = snak.get("datavalue", {}).get("value")
        if value is not None:
            out.append(value)
    return out


def _strings(claims: dict[str, Any], prop: str) -> list[str]:
    return [v for v in _values(claims, prop) if isinstance(v, str)]


def common_names(claims: dict[str, Any]) -> list[str]:
    """English common names, in the order Wikidata lists them."""
    names: list[str] = []
    for value in _values(claims, P_COMMON_NAME):
        if isinstance(value, dict) and value.get("language") == LANGUAGE:
            text = str(value.get("text", "")).strip()
            if text and text not in names:
                names.append(text)
    return names[:MAX_COMMON_NAMES]


def range_item_ids(claims: dict[str, Any]) -> list[str]:
    """The items a native-range statement points at, for a label lookup."""
    ids: list[str] = []
    for value in _values(claims, P_INDIGENOUS_TO):
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            ids.append(value["id"])
    return ids


def parse_labels(payload: dict[str, Any], item_ids: list[str]) -> list[str]:
    """Turn ``Q96`` into ``Mexico``, keeping the statement's own order."""
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict):
        return []
    labels: list[str] = []
    for item_id in item_ids:
        entity = entities.get(item_id)
        if not isinstance(entity, dict):
            continue
        label = entity.get("labels", {}).get(LANGUAGE, {}).get("value")
        if isinstance(label, str) and label and label not in labels:
            labels.append(label)
    return labels


def parse_entity(
    payload: dict[str, Any], species: SpeciesRef
) -> tuple[FactRecord, ...]:
    """Everything Wikidata states that maps to a ``species`` column."""
    item_id, claims = _claims(payload)
    if not claims:
        return ()

    facts: list[FactRecord] = []

    names = common_names(claims)
    if names:
        facts.append(
            FactRecord(
                field="common_names",
                value=names,
                source_kind=KIND,
                raw=names,
                note=f"{P_COMMON_NAME} (taxon common name), language {LANGUAGE}.",
            )
        )

    for prop, field in ((P_GBIF_ID, "gbif_key"), (P_POWO_ID, "powo_id")):
        values = _strings(claims, prop)
        if values:
            facts.append(
                FactRecord(
                    field=field, value=values[0], source_kind=KIND, raw=values[0]
                )
            )

    taxon_name = _strings(claims, P_TAXON_NAME)
    if taxon_name:
        facts.append(
            FactRecord(
                field="accepted_name",
                value=taxon_name[0],
                source_kind=KIND,
                raw=taxon_name[0],
            )
        )

    if item_id:
        facts.append(
            FactRecord(
                field="wikidata_id", value=item_id, source_kind=KIND, raw=item_id
            )
        )
    return tuple(facts)


class WikidataConnector:
    """Two calls at most: the entity, then the labels its range points at."""

    kind = KIND

    def __init__(
        self, fetcher: Fetcher, base_url: str = "https://www.wikidata.org/w/api.php"
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url

    def _entity_params(self, species: SpeciesRef) -> dict[str, Any]:
        common = {
            "action": "wbgetentities",
            "format": "json",
            "props": "labels|claims",
            "languages": LANGUAGE,
        }
        if species.wikidata_id:
            return {**common, "ids": species.wikidata_id}
        # No id from Wikipedia: ask by the article title instead.
        return {**common, "sites": "enwiki", "titles": species.accepted_name}

    async def enrich(self, species: SpeciesRef) -> ConnectorResult:
        from .http import SourceUnavailable

        sources = []
        try:
            fetched = await self.fetcher.get_json(
                KIND, self.base_url, self._entity_params(species)
            )
            sources.append(
                build_source(
                    KIND,
                    fetched.url,
                    fetched.payload,
                    title_suffix=species.accepted_name,
                    retrieved_at=fetched.retrieved_at,
                    is_mock=fetched.is_mock,
                )
            )
            facts = list(parse_entity(fetched.payload, species))

            _, claims = _claims(fetched.payload)
            item_ids = range_item_ids(claims)
            if item_ids:
                labels_fetched = await self.fetcher.get_json(
                    KIND,
                    self.base_url,
                    {
                        "action": "wbgetentities",
                        "format": "json",
                        "props": "labels",
                        "languages": LANGUAGE,
                        "ids": "|".join(item_ids[:20]),
                    },
                )
                sources.append(
                    build_source(
                        KIND,
                        labels_fetched.url,
                        labels_fetched.payload,
                        title_suffix=f"native range of {species.accepted_name}",
                        retrieved_at=labels_fetched.retrieved_at,
                        is_mock=labels_fetched.is_mock,
                    )
                )
                labels = parse_labels(labels_fetched.payload, item_ids)
                if labels:
                    facts.append(
                        FactRecord(
                            field="native_range",
                            value=labels,
                            source_kind=KIND,
                            raw=item_ids,
                            note=f"{P_INDIGENOUS_TO} (indigenous to), labels in {LANGUAGE}.",
                        )
                    )
        except SourceUnavailable as exc:
            return ConnectorResult(kind=KIND, sources=tuple(sources), error=str(exc))

        return ConnectorResult(kind=KIND, facts=tuple(facts), sources=tuple(sources))


_register(KIND, WikidataConnector)
