"""USDA PLANTS connector — the frost threshold, where it exists.

USDA is the one free source that publishes *measured* growth requirements: a
minimum temperature in °F, a soil pH range, a toxicity rating. Under the design
the water balance is the sole authority on outdoor watering, with no soil probe
to catch it being wrong, which makes ``min_temp_c`` one of the two values where
a guess does real damage. This connector is where a cited one comes from.

Two endpoints, no key:

* ``/api/PlantSearch?searchText=`` — scientific name to a numeric plant id;
* ``/api/PlantCharacteristics/{id}`` — the characteristics themselves.

**Coverage is the thing to know about this source.** Every plant has a profile;
only a minority have characteristics, largely species of agricultural or
conservation interest. All eight fixture species return an empty list. An empty
list is a real answer and is reported as one: the fields stay uncited, and
synthesis publishes ``confidence: unknown`` rather than a plausible number.
"""

from __future__ import annotations

import re
from typing import Any

from ..names import merge_key, strip_authorship
from ..sources import build_source
from .base import ConnectorResult, FactRecord, Fetcher, SpeciesRef
from .base import register as _register

KIND = "usda"

_TAGS = re.compile(r"<[^>]+>")

#: USDA characteristic names, spelled exactly as the API returns them.
C_MIN_TEMP_F = "Temperature, Minimum (°F)"
C_PH_MIN = "pH, Minimum"
C_PH_MAX = "pH, Maximum"
C_TOXICITY = "Toxicity"
C_SHADE = "Shade Tolerance"

#: USDA rates shade tolerance for a plant growing outdoors; it is not a
#: houseplant light level. The mapping is deliberately coarse, and never claims
#: ``bright_indirect`` or ``low_light`` — neither is a thing USDA measured.
#: The service answers Low/Medium/High; the older PLANTS vocabulary
#: (Intolerant/Intermediate/Tolerant) means the same thing and is accepted too.
#: *Low shade tolerance* means the plant wants sun, not that it wants shade.
SHADE_TO_LIGHT = {
    "low": "full_sun",
    "intolerant": "full_sun",
    "medium": "part_shade",
    "intermediate": "part_shade",
    "high": "part_shade",
    "tolerant": "part_shade",
}

#: USDA's toxicity rating. Anything above ``None`` is treated as toxic to both
#: pets and children: the rating does not distinguish them, and under-reporting
#: is the dangerous direction for a safety flag.
TOXICITY_LEVELS = {"none": False, "slight": True, "moderate": True, "severe": True}


def clean_name(raw: str | None) -> str:
    """``<i>Rosa gallica</i> L.`` → ``Rosa gallica``."""
    if not isinstance(raw, str):
        return ""
    return strip_authorship(_TAGS.sub("", raw).strip())


def _number(raw: Any) -> float | None:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def fahrenheit_to_celsius(value: float) -> float:
    """SI internally (the project conventions). The conversion is exact; the datum is USDA's."""
    return round((value - 32.0) * 5.0 / 9.0, 1)


def pick_plant(payload: Any, species: SpeciesRef) -> dict[str, Any] | None:
    """The search hit whose scientific name is the one we asked about.

    Never the first hit for its own sake: a search for *Citrus limon* also
    returns every *Citrus limon* variety, and enriching a species from a
    variety's record would be citing a source that was talking about something
    else.
    """
    if not isinstance(payload, list):
        return None
    wanted = merge_key(species.accepted_name)
    for entry in payload:
        plant = entry.get("Plant") if isinstance(entry, dict) else None
        if (
            isinstance(plant, dict)
            and merge_key(clean_name(plant.get("ScientificName"))) == wanted
        ):
            return plant
    return None


def parse_characteristics(payload: Any, species: SpeciesRef) -> tuple[FactRecord, ...]:
    """Map USDA's characteristics onto ``species`` columns.

    Only the characteristics that *are* a care value are mapped. ``Moisture
    Use`` (Low/Medium/High) is deliberately not turned into a ``water_k_c``:
    inventing a crop coefficient from an adjective is exactly the kind of
    plausible number the design exists to prevent, and the design made that field
    load-bearing.
    """
    if not isinstance(payload, list):
        return ()
    values = {
        entry.get("PlantCharacteristicName"): entry.get("PlantCharacteristicValue")
        for entry in payload
        if isinstance(entry, dict)
    }
    facts: list[FactRecord] = []

    raw_temp = values.get(C_MIN_TEMP_F)
    temp_f = _number(raw_temp)
    if temp_f is not None:
        facts.append(
            FactRecord(
                field="min_temp_c",
                value=fahrenheit_to_celsius(temp_f),
                source_kind=KIND,
                unit="C",
                raw=raw_temp,
                note=f"USDA '{C_MIN_TEMP_F}' = {raw_temp}°F, converted to °C.",
            )
        )

    for name, field in ((C_PH_MIN, "soil_ph_min"), (C_PH_MAX, "soil_ph_max")):
        number = _number(values.get(name))
        if number is not None:
            facts.append(
                FactRecord(
                    field=field,
                    value=number,
                    source_kind=KIND,
                    raw=values.get(name),
                    note=f"USDA '{name}'.",
                )
            )

    shade = str(values.get(C_SHADE, "")).strip().lower()
    if shade in SHADE_TO_LIGHT:
        facts.append(
            FactRecord(
                field="light_label",
                value=SHADE_TO_LIGHT[shade],
                source_kind=KIND,
                raw=values.get(C_SHADE),
                note=f"USDA '{C_SHADE}' = {values.get(C_SHADE)!r}, read as an outdoor light level.",
            )
        )

    facts.extend(_toxicity_facts(values))
    return tuple(facts)


def _toxicity_facts(values: dict[Any, Any]) -> list[FactRecord]:
    raw = values.get(C_TOXICITY)
    level = str(raw).strip().lower() if raw is not None else ""
    if level not in TOXICITY_LEVELS:
        return []
    toxic = TOXICITY_LEVELS[level]
    note = f"USDA toxicity rating: {str(raw).strip()}."
    facts = [
        FactRecord(field=field, value=toxic, source_kind=KIND, raw=raw, note=note)
        for field in ("toxic_to_pets", "toxic_to_children")
    ]
    facts.append(
        FactRecord(
            field="toxicity_note",
            value=(
                f"USDA rates this plant's toxicity as {str(raw).strip()}. The rating does not "
                "distinguish pets from children."
            ),
            source_kind=KIND,
            raw=raw,
        )
    )
    return facts


class UsdaConnector:
    """Search for the plant, then read its characteristics — two calls, or one."""

    kind = KIND

    def __init__(
        self,
        fetcher: Fetcher,
        base_url: str = "https://plantsservices.sc.egov.usda.gov/api",
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def enrich(self, species: SpeciesRef) -> ConnectorResult:
        from .http import SourceUnavailable

        sources = []
        try:
            found = await self.fetcher.get_json(
                KIND,
                f"{self.base_url}/PlantSearch",
                {"searchText": species.accepted_name},
            )
            sources.append(
                build_source(
                    KIND,
                    found.url,
                    found.payload,
                    title_suffix=f"search for {species.accepted_name}",
                    retrieved_at=found.retrieved_at,
                    is_mock=found.is_mock,
                )
            )
            plant = pick_plant(found.payload, species)
            if plant is None or not plant.get("Id"):
                return ConnectorResult(kind=KIND, sources=tuple(sources))

            characteristics = await self.fetcher.get_json(
                KIND, f"{self.base_url}/PlantCharacteristics/{plant['Id']}"
            )
            symbol = plant.get("Symbol")
            sources.append(
                build_source(
                    KIND,
                    (
                        f"https://plants.usda.gov/plant-profile/{symbol}"
                        if symbol
                        else characteristics.url
                    ),
                    characteristics.payload,
                    title_suffix=(
                        f"{species.accepted_name} ({symbol})"
                        if symbol
                        else species.accepted_name
                    ),
                    retrieved_at=characteristics.retrieved_at,
                    is_mock=characteristics.is_mock,
                )
            )
        except SourceUnavailable as exc:
            return ConnectorResult(kind=KIND, sources=tuple(sources), error=str(exc))

        return ConnectorResult(
            kind=KIND,
            facts=parse_characteristics(characteristics.payload, species),
            sources=tuple(sources),
        )


_register(KIND, UsdaConnector)
