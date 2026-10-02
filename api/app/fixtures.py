"""Fixture loading for mock mode.

Mocks are driven by ``fixtures/`` so that every parts of the project's mock tells the same
story as every other's, and so the scenario suite and the mocks cannot drift.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.settings import get_settings


def _load(relative: str) -> Any:
    path: Path = get_settings().fixtures_dir / relative
    with path.open() as fh:
        return json.load(fh)


@lru_cache
def site() -> dict[str, Any]:
    return _load("site.json")


@lru_cache
def locations() -> list[dict[str, Any]]:
    return _load("locations/locations.json")


@lru_cache
def species() -> list[dict[str, Any]]:
    return _load("species/species.json")


@lru_cache
def sources() -> list[dict[str, Any]]:
    return _load("species/sources.json")


@lru_cache
def specimens() -> list[dict[str, Any]]:
    return _load("specimens/specimens.json")


@lru_cache
def scenario(name: str) -> dict[str, Any]:
    return _load(f"scenarios/{name}.json")


@lru_cache
def baseline_weather() -> dict[str, Any]:
    return _load("weather/baseline_30d.json")


def by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any] | None:
    return next((r for r in rows if r["id"] == row_id), None)


def display_name(specimen: dict[str, Any]) -> str:
    """Nickname, else the species' first common name, else the accepted name."""
    if specimen.get("nickname"):
        return str(specimen["nickname"])
    sp = by_id(species(), specimen.get("species_id") or "")
    if sp:
        if sp.get("common_names"):
            return str(sp["common_names"][0]).capitalize()
        return str(sp["accepted_name"])
    return "Unnamed specimen"
