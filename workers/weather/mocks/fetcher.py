"""Replay the recordings, and synthesise Open-Meteo from the frozen fixtures.

The build-against-mocks rule: every service ships a mock matching the contract, so no agent waits on
another and the whole stack runs with no network at all. Two rules from
The botany worker's mock are worth restating because they are what keep a mock
honest:

* **A recording is never invented.** Everything under ``recorded/`` was
  fetched; see ``recorded/PROVENANCE.md``, including why Open-Meteo's success
  payloads are not there.
* **A synthesised payload says so.** Anything built from the fixtures carries a
  ``_synthetic`` key naming where it came from, so it cannot quietly pass for a
  fetch — in a test, in a log, or in a citation.

The synthesised Open-Meteo responses are the *shape* Open-Meteo returns with
the *story* the fixtures tell, so the Almanac's mock, the scenario suite and
the parser tests all describe the same weather.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..settings import WeatherSettings, get_settings
from ..sources.base import FetchResult, SourceUnavailable

RECORDED_DIR = Path(__file__).resolve().parent / "recorded"

#: The day everything in ``recorded/`` was fetched. Replays are cited with
#: this, not with the clock: a checkout's file timestamps say nothing about
#: when a payload was retrieved. Re-record, bump this, and say so in
#: ``recorded/PROVENANCE.md``.
RECORDED_ON = datetime(2026, 9, 23, 20, 9, tzinfo=UTC)

#: WMO codes for the fixtures' condition vocabulary, so a synthesised payload
#: round-trips through the real parser rather than past it.
_WMO_FOR_CONDITION = {
    "clear": 0,
    "partly_cloudy": 2,
    "cloudy": 3,
    "fog": 45,
    "rain": 63,
    "snow": 73,
    "storm": 95,
}


def recording_name(kind: str, url: str, params: Mapping[str, Any]) -> str | None:
    """Which file under ``recorded/`` answers this request, if any."""
    path = url.split("?", 1)[0].rstrip("/")
    if kind == "nws":
        if path.endswith("/alerts/active"):
            zone = str(params.get("zone") or "").lower()
            return f"nws/alerts__{zone}.json" if zone else None
        if "/points/" in path:
            return "nws/points__the-grounds.json"
        if path.endswith("/forecast/hourly"):
            return "nws/forecast-hourly__the-grounds.json"
        if path.endswith("/forecast"):
            return "nws/forecast__the-grounds.json"
        if "/observations/latest" in path:
            return "nws/observation__kind-latest.json"
    return None


class RecordedFetcher:
    """A ``Fetcher`` that never opens a socket."""

    def __init__(
        self,
        settings: WeatherSettings | None = None,
        recorded_dir: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.recorded_dir = recorded_dir or RECORDED_DIR
        #: Every request this fetcher served, for tests that count calls.
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._baseline: dict[str, Any] | None = None

    @property
    def baseline(self) -> dict[str, Any]:
        if self._baseline is None:
            path = self.settings.fixtures_dir / "weather" / "baseline_30d.json"
            self._baseline = (
                json.loads(path.read_text()) if path.exists() else {"days": []}
            )
        return self._baseline

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        params = dict(params or {})
        self.calls.append((kind, url, params))

        name = recording_name(kind, url, params)
        if name:
            path = self.recorded_dir / name
            if path.exists():
                return FetchResult(
                    url=url,
                    payload=json.loads(path.read_text()),
                    retrieved_at=RECORDED_ON,
                    is_mock=True,
                )
            # A zone with no recording is not an error: NWS answers with an
            # empty collection, and so does this.
            if "/alerts/active" in url:
                return FetchResult(
                    url=url,
                    payload={
                        "type": "FeatureCollection",
                        "features": [],
                        **_synthetic(),
                    },
                    retrieved_at=RECORDED_ON,
                    is_mock=True,
                )

        if kind == "open_meteo":
            return FetchResult(
                url=url,
                payload=self._open_meteo(params),
                retrieved_at=RECORDED_ON,
                is_mock=True,
            )

        raise SourceUnavailable(
            f"{kind}: nothing recorded for {url} and nothing to synthesise from"
        )

    # ------------------------------------------------------------ open-meteo

    def _open_meteo(self, params: dict[str, Any]) -> dict[str, Any]:
        days = self._days_for(params)
        payload: dict[str, Any] = {
            "latitude": float(params.get("latitude") or 0.0),
            "longitude": float(params.get("longitude") or 0.0),
            "generationtime_ms": 0.0,
            "utc_offset_seconds": 0,
            "timezone": "GMT",
            "timezone_abbreviation": "GMT",
            "elevation": 218.0,
            **_synthetic(),
        }
        if params.get("daily"):
            payload["daily_units"] = _daily_units()
            payload["daily"] = _daily_block(days)
        if params.get("hourly"):
            payload["hourly_units"] = _hourly_units()
            payload["hourly"] = _hourly_block(days)
        return payload

    def _days_for(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Which fixture days this request is asking about.

        An archive request names real dates, so it gets the fixture days inside
        that window and nothing if the window falls outside — the archive really
        does return nothing for a range it has not reached yet. A forecast
        request has no dates, so it gets the head of the baseline, which is the
        same weather the Almanac's mock already shows.
        """
        days: list[dict[str, Any]] = list(self.baseline.get("days") or [])
        start = _as_date(params.get("start_date"))
        end = _as_date(params.get("end_date"))
        if start and end:
            return [d for d in days if start <= _as_date(d["date"]) <= end]  # type: ignore[operator]
        if params.get("past_days") is not None:
            span = int(params["past_days"]) + int(params.get("forecast_days") or 1)
            return days[-span:] if span else []
        horizon = int(params.get("forecast_days") or len(days))
        return days[:horizon]


class UnavailableFetcher:
    """A ``Fetcher`` for which every source is down.

    The engines' behaviour with no data at all is a shipping path, not a
    hypothetical — it is what a household sees during an Open-Meteo outage, and
    the design exists because the first version of it failed closed and looked
    healthy. Having this here means that path is exercised rather than reasoned
    about.
    """

    def __init__(self, reason: str = "mock: the source is unreachable") -> None:
        self.reason = reason
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        self.calls.append((kind, url, dict(params or {})))
        raise SourceUnavailable(f"{kind}: {self.reason}")


# ------------------------------------------------------------------ synthesis


def _synthetic() -> dict[str, Any]:
    """Stamped into every fixture-derived payload, so a mock cannot pass for a fetch."""
    return {
        "_synthetic": {
            "from": "fixtures/weather/baseline_30d.json",
            "note": (
                "Mock mode. Built from the frozen fixtures in Open-Meteo's response "
                "shape, not fetched from Open-Meteo."
            ),
        }
    }


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _daily_units() -> dict[str, str]:
    return {
        "time": "iso8601",
        "weather_code": "wmo code",
        "temperature_2m_max": "°C",
        "temperature_2m_min": "°C",
        "precipitation_sum": "mm",
        "precipitation_probability_max": "%",
        "et0_fao_evapotranspiration": "mm",
        "wind_speed_10m_max": "km/h",
        "sunrise": "iso8601",
        "sunset": "iso8601",
    }


def _hourly_units() -> dict[str, str]:
    return {
        "time": "iso8601",
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "precipitation": "mm",
        "precipitation_probability": "%",
        "weather_code": "wmo code",
        "cloud_cover": "%",
        "wind_speed_10m": "km/h",
        "shortwave_radiation": "W/m²",
        "et0_fao_evapotranspiration": "mm",
    }


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _daily_block(days: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        "time": [d["date"] for d in days],
        "weather_code": [_WMO_FOR_CONDITION.get(d["condition"], 0) for d in days],
        "temperature_2m_max": [d["tmax_c"] for d in days],
        "temperature_2m_min": [d["tmin_c"] for d in days],
        "precipitation_sum": [d["precip_mm"] for d in days],
        "precipitation_probability_max": [80 if d["precip_mm"] else 10 for d in days],
        "et0_fao_evapotranspiration": [d["et0_mm"] for d in days],
        "wind_speed_10m_max": [12.0 for _ in days],
        # UTC, like everything else stored. At this site sunset falls after
        # midnight UTC, so it belongs to the following calendar day — writing it
        # as 01:00 of the same day would put sunset ten hours before sunrise.
        "sunrise": [f"{d['date']}T11:00" for d in days],
        "sunset": [_next_day(d["date"]) + "T01:00" for d in days],
    }


def _hourly_block(days: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """A day's summary spread over 24 hours.

    Not a weather model — a defensible shape. Temperature follows a cosine
    between the day's min and max with the minimum near dawn; ET₀ and solar
    radiation follow daylight; rain falls in the afternoon. The daily totals are
    preserved exactly, because the rollups sum these hours and a mock whose
    hours do not add up to its own days would make ``weather_daily`` look broken.
    """
    block: dict[str, list[Any]] = {name: [] for name in _hourly_units()}
    for day in days:
        code = _WMO_FOR_CONDITION.get(day["condition"], 0)
        daylight = [_daylight_weight(hour) for hour in range(24)]
        total_daylight = sum(daylight) or 1.0
        rain_hours = [14, 15, 16, 17]
        for hour in range(24):
            share = daylight[hour] / total_daylight
            block["time"].append(f"{day['date']}T{hour:02d}:00")
            block["temperature_2m"].append(
                round(_diurnal_temperature(day["tmin_c"], day["tmax_c"], hour), 1)
            )
            block["relative_humidity_2m"].append(
                round(_humidity(day["condition"], hour), 1)
            )
            block["precipitation"].append(
                round(day["precip_mm"] / len(rain_hours), 2)
                if hour in rain_hours
                else 0.0
            )
            block["precipitation_probability"].append(80 if day["precip_mm"] else 10)
            # On a wet day only the wet hours carry the wet code; the rest
            # of the day was cloudy, not raining for 24 hours.
            wet_day = code >= 51
            block["weather_code"].append(
                code
                if (not wet_day or hour in rain_hours)
                else _WMO_FOR_CONDITION["cloudy"]
            )
            block["cloud_cover"].append(_cloud_pct(day["condition"]))
            block["wind_speed_10m"].append(12.0)
            block["shortwave_radiation"].append(round(820.0 * daylight[hour], 1))
            block["et0_fao_evapotranspiration"].append(round(day["et0_mm"] * share, 3))
    return block


def _daylight_weight(hour: int) -> float:
    """A half-sine over a 14-hour day, zero at night. Peaks at solar noon."""
    if hour < 6 or hour > 19:
        return 0.0
    return math.sin(math.pi * (hour - 6) / 13.0)


def _diurnal_temperature(tmin: float, tmax: float, hour: int) -> float:
    """Coldest at 05:00, warmest at 15:00, cosine between."""
    span = (tmax - tmin) / 2.0
    middle = (tmax + tmin) / 2.0
    return middle - span * math.cos(math.pi * ((hour - 5) % 24) / 10.0)


def _humidity(condition: str, hour: int) -> float:
    """Higher overnight and in rain; nothing here is a measurement."""
    base = 82.0 if condition in {"rain", "storm", "fog"} else 58.0
    return base + 12.0 * math.cos(math.pi * ((hour - 5) % 24) / 12.0)


def _cloud_pct(condition: str) -> float:
    return {
        "clear": 5.0,
        "partly_cloudy": 40.0,
        "cloudy": 90.0,
        "fog": 100.0,
        "rain": 95.0,
        "storm": 100.0,
        "snow": 95.0,
    }.get(condition, 50.0)


def day_range(start: date, days: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(days)]
