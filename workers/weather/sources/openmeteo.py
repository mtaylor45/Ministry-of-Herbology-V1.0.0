"""Open-Meteo — the primary source for forecast, recent actuals and history.

Free, no key, CC-BY, and the only one of the two sources that publishes ET₀
(``et0_fao_evapotranspiration``, FAO-56 Penman-Monteith). That last point is
why it is primary and why the design exists: when it is missing, nothing else
upstream supplies the number the water balance runs on.

Three endpoints, one parser:

* ``/v1/forecast`` — 10 days daily plus hourly, for ``weather_forecast``;
* ``/v1/forecast?past_days=`` — the same hours once they have happened, for
  ``weather_obs``. Open-Meteo re-serves a past hour with the measured value, so
  a forecast hour becomes an observation without a second API to reconcile;
* ``/v1/archive`` — history for a backfill, for ``weather_obs``.

Responses are column-oriented: ``{"hourly": {"time": [...], "temperature_2m":
[...]}}``. Every array is parallel to ``time``, and a variable the caller did
not request is simply absent — so the parser indexes defensively and yields
``None`` rather than assuming a shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from .base import (
    OPEN_METEO,
    Fetcher,
    Forecast,
    Observation,
    SourceResult,
    SourceUnavailable,
    as_float,
    parse_time,
)

#: Hourly variables we ask for. ``et0_fao_evapotranspiration`` is hourly as
#: well as daily; summing the hours is how an observation day gets an ET₀ that
#: matches the hours actually stored.
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "precipitation_probability",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "shortwave_radiation",
    "et0_fao_evapotranspiration",
)

DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "et0_fao_evapotranspiration",
    "wind_speed_10m_max",
    "sunrise",
    "sunset",
)

#: WMO 4677 present-weather codes onto the vocabulary the fixtures and the UI
#: already speak. Freezing drizzle and freezing rain map to ``rain``, not
#: ``snow``: it falls as liquid, and it is the frost guard's job — not the icon's
#: — to say the ground is about to be lethal.
#: Inclusive ``(lowest, highest, condition)`` bands.
_WMO_CONDITIONS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "clear"),
    (1, 2, "partly_cloudy"),
    (3, 3, "cloudy"),
    (45, 48, "fog"),
    (51, 67, "rain"),
    (71, 77, "snow"),
    (80, 82, "rain"),
    (85, 86, "snow"),
    (95, 99, "storm"),
)


def condition_from_wmo(code: Any) -> str | None:
    """A WMO code to one of ``base.CONDITIONS``; ``None`` when it says nothing."""
    number = as_float(code)
    if number is None:
        return None
    whole = int(number)
    for lowest, highest, condition in _WMO_CONDITIONS:
        if lowest <= whole <= highest:
            return condition
    return None


def _column(block: Any, name: str) -> Sequence[Any]:
    """One variable's array, or an empty one when it was not requested."""
    if not isinstance(block, dict):
        return ()
    values = block.get(name)
    return values if isinstance(values, list) else ()


def _at(column: Sequence[Any], index: int) -> Any:
    return column[index] if index < len(column) else None


def _times(block: Any) -> list[datetime | None]:
    return [parse_time(value) for value in _column(block, "time")]


def parse_hourly_observations(
    payload: Any, *, source: str = OPEN_METEO, before: datetime | None = None
) -> tuple[Observation, ...]:
    """Hourly rows for ``weather_obs``.

    ``before`` keeps the future out of the observation table. One request
    carries both past and forecast hours, and storing a forecast hour as an
    observation is how a rain that never fell ends up clearing a deficit.
    """
    block = payload.get("hourly") if isinstance(payload, dict) else None
    times = _times(block)
    columns = {name: _column(block, name) for name in HOURLY_VARIABLES}

    rows: list[Observation] = []
    for index, moment in enumerate(times):
        if moment is None or (before is not None and moment > before):
            continue
        rows.append(
            Observation(
                time=moment,
                temperature_c=as_float(_at(columns["temperature_2m"], index)),
                humidity_pct=as_float(_at(columns["relative_humidity_2m"], index)),
                precip_mm=as_float(_at(columns["precipitation"], index)),
                et0_mm=as_float(_at(columns["et0_fao_evapotranspiration"], index)),
                wind_kph=as_float(_at(columns["wind_speed_10m"], index)),
                solar_wm2=as_float(_at(columns["shortwave_radiation"], index)),
                cloud_pct=as_float(_at(columns["cloud_cover"], index)),
                condition=condition_from_wmo(_at(columns["weather_code"], index)),
                source=source,
            )
        )
    return tuple(rows)


def parse_daily_forecast(
    payload: Any, *, issued_at: datetime, source: str = OPEN_METEO
) -> tuple[Forecast, ...]:
    """Daily rows for ``weather_forecast``. This is what the Almanac shows."""
    block = payload.get("daily") if isinstance(payload, dict) else None
    times = _times(block)
    columns = {name: _column(block, name) for name in DAILY_VARIABLES}

    rows: list[Forecast] = []
    for index, moment in enumerate(times):
        if moment is None:
            continue
        rows.append(
            Forecast(
                time=moment,
                issued_at=issued_at,
                horizon="daily",
                temp_min_c=as_float(_at(columns["temperature_2m_min"], index)),
                temp_max_c=as_float(_at(columns["temperature_2m_max"], index)),
                precip_mm=as_float(_at(columns["precipitation_sum"], index)),
                precip_prob_pct=as_float(
                    _at(columns["precipitation_probability_max"], index)
                ),
                et0_mm=as_float(_at(columns["et0_fao_evapotranspiration"], index)),
                wind_kph=as_float(_at(columns["wind_speed_10m_max"], index)),
                condition=condition_from_wmo(_at(columns["weather_code"], index)),
                sunrise=parse_time(_at(columns["sunrise"], index)),
                sunset=parse_time(_at(columns["sunset"], index)),
                source=source,
            )
        )
    return tuple(rows)


def parse_hourly_forecast(
    payload: Any,
    *,
    issued_at: datetime,
    source: str = OPEN_METEO,
    after: datetime | None = None,
) -> tuple[Forecast, ...]:
    """Hourly rows for ``weather_forecast`` — the Almanac's 1-day view."""
    block = payload.get("hourly") if isinstance(payload, dict) else None
    times = _times(block)
    columns = {name: _column(block, name) for name in HOURLY_VARIABLES}

    rows: list[Forecast] = []
    for index, moment in enumerate(times):
        if moment is None or (after is not None and moment < after):
            continue
        rows.append(
            Forecast(
                time=moment,
                issued_at=issued_at,
                horizon="hourly",
                temperature_c=as_float(_at(columns["temperature_2m"], index)),
                precip_mm=as_float(_at(columns["precipitation"], index)),
                precip_prob_pct=as_float(
                    _at(columns["precipitation_probability"], index)
                ),
                et0_mm=as_float(_at(columns["et0_fao_evapotranspiration"], index)),
                wind_kph=as_float(_at(columns["wind_speed_10m"], index)),
                condition=condition_from_wmo(_at(columns["weather_code"], index)),
                source=source,
            )
        )
    return tuple(rows)


class OpenMeteoSource:
    """Open-Meteo, bound to a fetcher. Nothing here decides what to store."""

    source = OPEN_METEO

    def __init__(
        self,
        fetcher: Fetcher,
        *,
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
        archive_url: str = "https://archive-api.open-meteo.com/v1/archive",
    ) -> None:
        self.fetcher = fetcher
        self.forecast_url = forecast_url
        self.archive_url = archive_url

    def _base_params(self, latitude: float, longitude: float) -> dict[str, Any]:
        return {
            "latitude": latitude,
            "longitude": longitude,
            # Everything is stored UTC (`timestamptz`), so it is asked for in
            # UTC. Local time is resolved per-site, much later, for display.
            "timezone": "UTC",
            "wind_speed_unit": "kmh",
        }

    async def fetch_forecast(
        self, latitude: float, longitude: float, *, days: int = 10
    ) -> SourceResult:
        """The 10-day daily and 1-day hourly forecast the plan asks for."""
        params = self._base_params(latitude, longitude) | {
            "forecast_days": days,
            "hourly": ",".join(HOURLY_VARIABLES),
            "daily": ",".join(DAILY_VARIABLES),
        }
        try:
            result = await self.fetcher.get_json(
                "open_meteo", self.forecast_url, params
            )
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))

        issued_at = result.retrieved_at
        return SourceResult(
            source=self.source,
            forecasts=parse_daily_forecast(result.payload, issued_at=issued_at)
            + parse_hourly_forecast(result.payload, issued_at=issued_at),
            is_mock=result.is_mock,
        )

    async def fetch_observations(
        self, latitude: float, longitude: float, *, past_days: int = 2
    ) -> SourceResult:
        """Recent actuals, for ``weather_obs``."""
        params = self._base_params(latitude, longitude) | {
            "past_days": past_days,
            "forecast_days": 1,
            "hourly": ",".join(HOURLY_VARIABLES),
        }
        try:
            result = await self.fetcher.get_json(
                "open_meteo", self.forecast_url, params
            )
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))

        return SourceResult(
            source=self.source,
            observations=parse_hourly_observations(
                result.payload, before=result.retrieved_at
            ),
            is_mock=result.is_mock,
        )

    async def fetch_history(
        self, latitude: float, longitude: float, *, start: date, end: date
    ) -> SourceResult:
        """Archive backfill, for ``weather_obs``.

        The archive lags real time by about five days. A caller asking for
        yesterday gets an empty answer, not an error, so the ingest asks the
        forecast endpoint for anything recent and this one for the rest.
        """
        params = self._base_params(latitude, longitude) | {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(HOURLY_VARIABLES),
            "daily": ",".join(DAILY_VARIABLES),
        }
        try:
            result = await self.fetcher.get_json("open_meteo", self.archive_url, params)
        except SourceUnavailable as exc:
            return SourceResult(source=self.source, error=str(exc))

        return SourceResult(
            source=self.source,
            observations=parse_hourly_observations(result.payload),
            is_mock=result.is_mock,
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
