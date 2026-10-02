"""Assembling engine inputs from whatever this deployment actually has.

The engines in ``tasks.py`` are pure functions over explicit inputs. Something
has to build those inputs, and in mock mode that something reads
``fixtures/``, which is why this module exists rather than the API doing it: a
specimen's cover factor and the confidence of its coefficient must be derived
the same way for the worker that writes ``water_balance`` rows and the endpoint
that serves them, or the two will disagree and only one of them will be right.

Nothing here decides anything. It reads, joins and converts — with one
exception that has to live somewhere: :func:`active_scenario` is the single
place that answers "which recorded weather is this deployment standing in".
The API and the worker both come through here, so they cannot disagree about
it; a second reading of the setting in ``api/almanac/`` is how the endpoint and
the row it serves start describing different days.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from .ingest import Site
from .settings import WeatherSettings, get_settings
from .tasks import DayWeather, FrostNight, FrostSubject, WaterCoefficient, capacity_mm


@lru_cache(maxsize=32)
def _load(fixtures_dir: Path, relative: str) -> Any:
    path = fixtures_dir / relative
    return json.loads(path.read_text()) if path.exists() else []


def site(settings: WeatherSettings | None = None) -> Site:
    settings = settings or get_settings()
    return Site.from_fixture(_load(settings.fixtures_dir, "site.json"))


@dataclass(frozen=True, slots=True)
class SpecimenContext:
    """One plant, with everything both engines need about it."""

    specimen_id: str
    display_name: str
    is_outdoor: bool
    in_container: bool
    is_covered: bool
    capacity_mm: float
    k_c: WaterCoefficient
    min_temp_c: float | None
    min_temp_confidence: str
    #: No soil hardware exists, so this is ``None`` for every plant
    #: today. It is carried anyway, because the day it stops being ``None`` the
    #: override has to already work.
    sensor_override_pct: float | None = None

    @property
    def cover_factor(self) -> float:
        """0 under a roof, 1 under open sky. The most-got-wrong term."""
        return 0.0 if self.is_covered else 1.0

    def frost_subject(self) -> FrostSubject:
        return FrostSubject(
            specimen_id=self.specimen_id,
            is_outdoor=self.is_outdoor,
            in_container=self.in_container,
            min_temp_c=self.min_temp_c,
            min_temp_confidence=self.min_temp_confidence,
            display_name=self.display_name,
        )


def specimen_contexts(
    settings: WeatherSettings | None = None,
) -> dict[str, SpecimenContext]:
    """Every specimen, joined to its species' care values and its location."""
    settings = settings or get_settings()
    fixtures_dir = settings.fixtures_dir
    species = {row["id"]: row for row in _load(fixtures_dir, "species/species.json")}
    locations = {
        row["id"]: row for row in _load(fixtures_dir, "locations/locations.json")
    }
    sources = {row["id"]: row for row in _load(fixtures_dir, "species/sources.json")}

    contexts: dict[str, SpecimenContext] = {}
    for specimen in _load(fixtures_dir, "specimens/specimens.json"):
        plant = species.get(specimen.get("species_id") or "") or {}
        location = locations.get(specimen.get("location_id") or "") or {}
        care_values = {row["field"]: row for row in plant.get("care_values") or []}

        k_c_row = care_values.get("water_k_c")
        k_c = WaterCoefficient.from_care_value(
            k_c_row, sources.get((k_c_row or {}).get("source_id") or "")
        )
        min_temp_row = care_values.get("min_temp_c") or {}

        contexts[specimen["id"]] = SpecimenContext(
            specimen_id=specimen["id"],
            display_name=_display_name(specimen, plant),
            is_outdoor=bool(specimen.get("is_outdoor")),
            in_container=bool(specimen.get("in_container")),
            is_covered=bool(location.get("is_covered")),
            capacity_mm=capacity_mm(
                bool(specimen.get("in_container")), specimen.get("container_litres")
            ),
            k_c=k_c,
            min_temp_c=_as_float(plant.get("min_temp_c")),
            min_temp_confidence=str(min_temp_row.get("confidence") or "unknown"),
        )
    return contexts


def active_scenario(settings: WeatherSettings | None = None) -> str | None:
    """The scenario this deployment is standing in, or ``None`` for baseline.

    ``MOH_SCENARIO``.
    Unset in every shipped deployment, and unset is the baseline recording.
    """
    settings = settings or get_settings()
    return settings.scenario


def as_of_day(settings: WeatherSettings | None = None) -> date | None:
    """Which day of the recording counts as today, or ``None`` for its last."""
    settings = settings or get_settings()
    return settings.scenario_day


def weather_rows(
    settings: WeatherSettings | None = None, *, scenario: str | None = None
) -> list[dict[str, Any]]:
    """The recording's day rows, exactly as the fixture writes them.

    The balance wants :class:`DayWeather`; the Almanac's forecast and history
    want ``condition`` too, which is not a term in the equation and so is not
    on ``DayWeather``. Both come from here rather than from two loaders, so a
    deployment under ``storm`` cannot show a balance cleared by rain beside a
    forecast that never mentions it.
    """
    settings = settings or get_settings()
    name = scenario if scenario is not None else active_scenario(settings)
    relative = f"scenarios/{name}.json" if name else "weather/baseline_30d.json"
    if name and not (settings.fixtures_dir / relative).exists():
        # A typo in MOH_SCENARIO must not read as "fine, no weather".
        # An Almanac with no days looks like a quiet garden, which is the one
        # failure mode the design says this package may never produce silently.
        available = sorted(
            path.stem for path in (settings.fixtures_dir / "scenarios").glob("*.json")
        )
        raise ValueError(
            f"MOH_SCENARIO={name!r} names no recording in "
            f"{settings.fixtures_dir / 'scenarios'}; available: "
            f"{', '.join(available) or 'none'}"
        )
    payload = _load(settings.fixtures_dir, relative)
    rows = list(payload.get("days") or []) if isinstance(payload, dict) else []
    if scenario is None:
        # Only when this *is* the active recording: an explicit argument may
        # legitimately ask for a different one (the frost guard does), and the
        # operator's day says nothing about that one.
        _check_as_of_is_in_range(settings, rows, relative)
    return rows


def _check_as_of_is_in_range(
    settings: WeatherSettings, rows: list[dict[str, Any]], relative: str
) -> None:
    """A day outside the recording would select no weather at all.

    Which is the quiet-garden failure the design names: an empty series advances
    no deficit, so every plant reads as comfortable and the app says nothing.
    A misconfigured date may not be able to produce that.
    """
    day = as_of_day(settings)
    if day is None or not rows:
        return
    first = date.fromisoformat(rows[0]["date"])
    last = date.fromisoformat(rows[-1]["date"])
    if not first <= day <= last:
        raise ValueError(
            f"MOH_SCENARIO_DAY={day.isoformat()} is outside {relative}, "
            f"which runs {first.isoformat()} to {last.isoformat()}. A day outside "
            "the recording selects no weather, and no weather reads as a garden "
            "that needs nothing."
        )


def weather_days(
    settings: WeatherSettings | None = None,
    *,
    scenario: str | None = None,
    limit: int | None = None,
    through: date | None = None,
) -> list[DayWeather]:
    """The site's daily weather, from a scenario or from the baseline.

    Truncated at ``through``, or at ``MOH_SCENARIO_DAY`` when that is
    set: the water balance is a history that ends *now*, and a recording
    replayed three days past its downpour honestly reports the deficit that has
    rebuilt since. Standing on the day the rain fell is what shows the rain.
    """
    settings = settings or get_settings()
    rows = weather_rows(settings, scenario=scenario)
    end = through if through is not None else as_of_day(settings)
    if end is not None:
        rows = [row for row in rows if date.fromisoformat(row["date"]) <= end]
    if limit is not None:
        rows = rows[-limit:]
    return [
        DayWeather(
            day=date.fromisoformat(day["date"]),
            precip_mm=float(day.get("precip_mm") or 0.0),
            et0_mm=_as_float(day.get("et0_mm")),
            tmin_c=_as_float(day.get("tmin_c")),
            tmax_c=_as_float(day.get("tmax_c")),
        )
        for day in rows
    ]


def frost_nights(
    settings: WeatherSettings | None = None, *, scenario: str | None = None
) -> list[FrostNight]:
    """The nights the frost guard reads.

    With no scenario selected this stays on ``frost``, which is where it has
    been: the baseline recording is a mild fortnight in May and a
    frost endpoint that answers "nothing, ever" is not a mock of anything. An
    operator who selects a scenario gets *that* one here too, so the Almanac's
    two halves describe one week of weather rather than two.

    Built from :func:`weather_rows` rather than :func:`weather_days`, and so
    deliberately **not** cut off at ``MOH_SCENARIO_DAY``. The water
    balance is a history and ends at today; the frost guard is a 72-hour
    lookahead and is about the nights still ahead of the reader. Truncating it
    at today would leave the guard blind to the freeze it exists to warn about,
    and the cost of that silence is a dead plant rather than a stale number.
    """
    nights: list[FrostNight] = []
    for row in weather_rows(settings, scenario=_frost_scenario(settings, scenario)):
        low = _as_float(row.get("tmin_c"))
        if low is None:
            continue
        nights.append(FrostNight(day=date.fromisoformat(row["date"]), low_c=low))
    return nights


def scenario_advisories(
    settings: WeatherSettings | None = None, *, scenario: str | None = None
) -> list[Any]:
    """The advisories a scenario declares, as ``sources.base.Advisory`` rows."""
    from .sources.base import Advisory, parse_time

    settings = settings or get_settings()
    name = _frost_scenario(settings, scenario)
    payload = _load(settings.fixtures_dir, f"scenarios/{name}.json")
    return [
        Advisory(
            external_id=str(row.get("external_id") or ""),
            event=str(row.get("event") or ""),
            severity=row.get("severity"),
            onset=parse_time(row.get("onset")),
            expires=parse_time(row.get("expires")),
            headline=row.get("headline"),
        )
        for row in payload.get("advisories") or []
    ]


def _frost_scenario(settings: WeatherSettings | None, scenario: str | None) -> str:
    """An explicit argument wins, then the operator's scenario, then ``frost``."""
    return scenario or active_scenario(settings) or "frost"


def _display_name(specimen: dict[str, Any], plant: dict[str, Any]) -> str:
    if specimen.get("nickname"):
        return str(specimen["nickname"])
    if plant.get("common_names"):
        return str(plant["common_names"][0]).capitalize()
    return str(plant.get("accepted_name") or "Unnamed specimen")


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
