"""The National Weather Service — the secondary source the contract names.

``weather_obs.source`` and ``weather_forecast.source`` default to
``open_meteo`` and NWS is the other value they take. It covers two jobs
Open-Meteo cannot:

1. **Advisories.** ``weather_alert`` exists for NWS watches, warnings and
   advisories, and the frost guard's second trigger is an advisory covering the
   site. Nobody else publishes them.
2. **A fallback for conditions and forecast**, when Open-Meteo is unreachable.

It does *not* publish ET₀. A day whose temperatures came from NWS therefore has
no ingested ET₀ at all, which is precisely the case the design was written for:
the Hargreaves fallback runs, the day is labelled, and the Almanac reports the
reduced confidence rather than a figure that looks the same as Open-Meteo's.

Shapes, from the recordings in ``mocks/recorded/nws/``:

* measurements arrive as ``{"unitCode": "wmoUnit:degC", "value": 18}``, and a
  missing reading is a present key with ``value: null``;
* gridpoint forecasts arrive as *periods* — daytime and overnight halves, named
  "Tonight" and "Thursday Night" — with the temperature as a whole number of
  °F. A night period's temperature is the night's low, which is the number the
  frost guard needs;
* wind is a human string, ``"10 mph"`` or ``"5 to 10 mph"``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .base import (
    NWS,
    Advisory,
    Fetcher,
    Forecast,
    Observation,
    SourceResult,
    SourceUnavailable,
    as_float,
    parse_time,
)

MPH_TO_KPH = 1.609344

#: NWS ``shortForecast`` prose onto the shared vocabulary. Checked in order, so
#: "Chance Rain Showers then Partly Sunny" reads as rain — the wetter half of a
#: mixed forecast is the half that waters a plant.
_CONDITION_PHRASES: tuple[tuple[str, str], ...] = (
    ("thunderstorm", "storm"),
    ("snow", "snow"),
    ("sleet", "snow"),
    ("freezing rain", "rain"),
    ("rain", "rain"),
    ("shower", "rain"),
    ("drizzle", "rain"),
    ("fog", "fog"),
    ("haze", "fog"),
    ("cloudy", "cloudy"),
    ("overcast", "cloudy"),
    ("partly sunny", "partly_cloudy"),
    ("mostly sunny", "partly_cloudy"),
    ("partly clear", "partly_cloudy"),
    ("sunny", "clear"),
    ("clear", "clear"),
)


def condition_from_phrase(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    lowered = text.lower()
    for phrase, condition in _CONDITION_PHRASES:
        if phrase in lowered:
            return condition
    return None


def measurement(block: Any) -> float | None:
    """``{"unitCode": ..., "value": 18}`` → ``18.0``; anything else → ``None``."""
    if isinstance(block, dict):
        return as_float(block.get("value"))
    return as_float(block)


def fahrenheit_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


def wind_kph(text: Any) -> float | None:
    """``"5 to 10 mph"`` → 16.1. The upper figure, because wind dries.

    A range's top is the number that matters for evaporation and for whether a
    pot blows over; averaging it away is a loss of the only useful half.
    """
    if not isinstance(text, str):
        return None
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    speed = max(numbers)
    return speed * MPH_TO_KPH if "mph" in text.lower() else speed


def parse_latest_observation(payload: Any) -> tuple[Observation, ...]:
    """One row of ``weather_obs`` from ``/stations/{id}/observations/latest``."""
    properties = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(properties, dict):
        return ()
    moment = parse_time(properties.get("timestamp"))
    if moment is None:
        return ()
    return (
        Observation(
            time=moment,
            temperature_c=measurement(properties.get("temperature")),
            humidity_pct=measurement(properties.get("relativeHumidity")),
            # Only the one-hour total. NWS also publishes
            # ``precipitationLast3Hours`` and ``…6Hours``, and reading either
            # into an hourly row would count the same rain three or six times
            # once ``weather_daily`` sums the bucket. A station that reports
            # neither leaves this None, which is "unmeasured", not "dry".
            precip_mm=measurement(properties.get("precipitationLastHour")),
            # NWS publishes no ET₀ — see the module docstring, and the design.
            et0_mm=None,
            wind_kph=measurement(properties.get("windSpeed")),
            cloud_pct=_cloud_cover_pct(properties.get("cloudLayers")),
            condition=condition_from_phrase(properties.get("textDescription")),
            source=NWS,
        ),
    )


#: METAR sky-cover abbreviations as a percentage of sky obscured, using the
#: midpoint of each band's oktas. SKC/CLR are genuinely zero.
_SKY_COVER_PCT = {
    "SKC": 0.0,
    "CLR": 0.0,
    "FEW": 18.0,
    "SCT": 44.0,
    "BKN": 75.0,
    "OVC": 100.0,
    "VV": 100.0,
}


def _cloud_cover_pct(layers: Any) -> float | None:
    """The densest reported layer. Cloud cover is cumulative, not averaged."""
    if not isinstance(layers, list):
        return None
    seen = [
        _SKY_COVER_PCT[layer["amount"]]
        for layer in layers
        if isinstance(layer, dict) and layer.get("amount") in _SKY_COVER_PCT
    ]
    return max(seen) if seen else None


def parse_period_forecast(
    payload: Any, *, issued_at: datetime, horizon: str = "daily"
) -> tuple[Forecast, ...]:
    """Gridpoint forecast periods to ``weather_forecast`` rows.

    A night period carries the night's low and a day period the day's high, so
    each row sets exactly the one it knows. Filling the other from the same
    number would hand the frost guard a low that is really a high.
    """
    properties = payload.get("properties") if isinstance(payload, dict) else None
    periods = properties.get("periods") if isinstance(properties, dict) else None
    if not isinstance(periods, list):
        return ()

    rows: list[Forecast] = []
    for period in periods:
        if not isinstance(period, dict):
            continue
        moment = parse_time(period.get("startTime"))
        if moment is None:
            continue
        temperature = as_float(period.get("temperature"))
        if temperature is not None and period.get("temperatureUnit") == "F":
            temperature = fahrenheit_to_c(temperature)
        is_daytime = bool(period.get("isDaytime"))
        rows.append(
            Forecast(
                time=moment,
                issued_at=issued_at,
                horizon=horizon,
                temperature_c=temperature,
                temp_min_c=None if is_daytime else temperature,
                temp_max_c=temperature if is_daytime else None,
                precip_prob_pct=measurement(period.get("probabilityOfPrecipitation")),
                # NWS periods carry a probability, not an amount, and never ET₀.
                precip_mm=None,
                et0_mm=None,
                wind_kph=wind_kph(period.get("windSpeed")),
                condition=condition_from_phrase(period.get("shortForecast")),
                source=NWS,
            )
        )
    return tuple(rows)


def parse_alerts(payload: Any) -> tuple[Advisory, ...]:
    """``/alerts/active`` to ``weather_alert`` rows.

    An empty ``features`` list is a real answer — no advisory is in force — and
    the caller must be able to tell it from a failed request, which is why this
    returns rows and :class:`SourceUnavailable` is raised elsewhere.
    """
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return ()

    rows: list[Advisory] = []
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict):
            continue
        external_id = properties.get("id") or properties.get("@id")
        event = properties.get("event")
        if not external_id or not event:
            continue
        rows.append(
            Advisory(
                external_id=str(external_id),
                event=str(event),
                severity=_text(properties.get("severity")),
                onset=parse_time(properties.get("onset"))
                or parse_time(properties.get("effective")),
                expires=parse_time(properties.get("expires"))
                or parse_time(properties.get("ends")),
                headline=_text(properties.get("headline")),
                description=_text(properties.get("description")),
            )
        )
    return tuple(rows)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class NwsSource:
    """NWS, bound to a fetcher."""

    source = NWS

    def __init__(
        self, fetcher: Fetcher, *, base_url: str = "https://api.weather.gov"
    ) -> None:
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    async def fetch_advisories(self, zone: str) -> SourceResult:
        """Active watches, warnings and advisories for a forecast zone."""
        try:
            result = await self.fetcher.get_json(
                "nws", f"{self.base_url}/alerts/active", {"zone": zone}
            )
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))
        return SourceResult(
            source=self.source,
            advisories=parse_alerts(result.payload),
            is_mock=result.is_mock,
        )

    async def fetch_forecast(self, grid_url: str) -> SourceResult:
        """A gridpoint forecast, for when Open-Meteo will not answer.

        ``grid_url`` comes from ``/points/{lat},{lon}``; the ingest resolves it
        once and keeps it, because a site does not move between grid cells.
        """
        try:
            result = await self.fetcher.get_json("nws", grid_url)
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))
        return SourceResult(
            source=self.source,
            forecasts=parse_period_forecast(
                result.payload, issued_at=result.retrieved_at
            ),
            is_mock=result.is_mock,
        )

    async def fetch_observation(self, station: str) -> SourceResult:
        """The latest observation from one station."""
        try:
            result = await self.fetcher.get_json(
                "nws", f"{self.base_url}/stations/{station}/observations/latest"
            )
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))
        return SourceResult(
            source=self.source,
            observations=parse_latest_observation(result.payload),
            is_mock=result.is_mock,
        )

    async def resolve_point(self, latitude: float, longitude: float) -> dict[str, Any]:
        """``/points`` — the forecast grid, zone and station list for a site.

        Worth calling once and storing: it is also the thing that would have
        caught ``fixtures/site.json`` naming a zone in the wrong county.
        """
        result = await self.fetcher.get_json(
            "nws", f"{self.base_url}/points/{latitude},{longitude}"
        )
        properties = result.payload.get("properties", {})
        return {
            "forecast_url": properties.get("forecast"),
            "forecast_hourly_url": properties.get("forecastHourly"),
            "forecast_zone": _last_segment(properties.get("forecastZone")),
            "county": _last_segment(properties.get("county")),
            "grid_id": properties.get("gridId"),
        }


def _last_segment(url: Any) -> str | None:
    return (
        str(url).rstrip("/").rsplit("/", 1)[-1]
        if isinstance(url, str) and url
        else None
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
