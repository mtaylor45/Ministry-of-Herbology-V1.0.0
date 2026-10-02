"""The shape every weather source has — the weather engine.

Three parts, the same split the botany worker used for the botanical sources and for
the same reason: exactly one of them touches the network, so the other two are
testable against a recording forever.

1. a **fetcher**, the only thing that opens a socket;
2. **pure parse functions** over a payload, returning rows;
3. a **source** binding the two, returning the rows *and* which source produced
   them, because ``weather_obs.source`` and ``weather_forecast.source`` are
   columns in the frozen schema and a row that cannot say where it came from is
   a row the Almanac cannot caveat.

The row dataclasses below mirror ``contracts/schema/001_init.sql`` column for
column. That is deliberate: a parser that invents a field it cannot store, or
stores one the contract does not have, should not typecheck.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

#: The condition vocabulary the fixtures and the UI already use. Every source
#: maps its own codes onto exactly these; a source-specific string reaching the
#: API would make the app's screens' icon table a per-source problem.
CONDITIONS = ("clear", "partly_cloudy", "cloudy", "rain", "snow", "storm", "fog")

OPEN_METEO = "open_meteo"
NWS = "nws"


class SourceUnavailable(RuntimeError):
    """The source could not be reached, or would not answer.

    Distinct from a source that answered with nothing. "No advisory is in
    force" is a fact about the weather; "NWS timed out" is a fact about us, and
    the frost guard must never read the second as the first.
    """


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One payload, and the request that produced it."""

    url: str
    payload: Any
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_mock: bool = False


@runtime_checkable
class Fetcher(Protocol):
    """The only thing in this worker allowed to touch the network."""

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class Observation:
    """One row of ``weather_obs``: what the weather actually did."""

    time: datetime
    temperature_c: float | None = None
    humidity_pct: float | None = None
    precip_mm: float | None = None
    et0_mm: float | None = None
    wind_kph: float | None = None
    solar_wm2: float | None = None
    cloud_pct: float | None = None
    condition: str | None = None
    source: str = OPEN_METEO

    def to_row(self, site_id: str) -> dict[str, Any]:
        return {
            "time": self.time,
            "site_id": site_id,
            "temperature_c": self.temperature_c,
            "humidity_pct": self.humidity_pct,
            "precip_mm": self.precip_mm,
            "et0_mm": self.et0_mm,
            "wind_kph": self.wind_kph,
            "solar_wm2": self.solar_wm2,
            "cloud_pct": self.cloud_pct,
            "condition": self.condition,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Forecast:
    """One row of ``weather_forecast``: what the weather is expected to do.

    ``horizon`` is ``hourly`` or ``daily``; ``issued_at`` is when the source
    said it, and it is part of the table's unique key. Keeping it means a
    forecast can be compared with what happened, which is the only way anyone
    ever finds out that a source has drifted.
    """

    time: datetime
    issued_at: datetime
    horizon: str
    temperature_c: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precip_mm: float | None = None
    precip_prob_pct: float | None = None
    et0_mm: float | None = None
    wind_kph: float | None = None
    condition: str | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    source: str = OPEN_METEO

    def to_row(self, site_id: str) -> dict[str, Any]:
        return {
            "time": self.time,
            "site_id": site_id,
            "issued_at": self.issued_at,
            "horizon": self.horizon,
            "temperature_c": self.temperature_c,
            "temp_min_c": self.temp_min_c,
            "temp_max_c": self.temp_max_c,
            "precip_mm": self.precip_mm,
            "precip_prob_pct": self.precip_prob_pct,
            "et0_mm": self.et0_mm,
            "wind_kph": self.wind_kph,
            "condition": self.condition,
            "sunrise": self.sunrise,
            "sunset": self.sunset,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Advisory:
    """One row of ``weather_alert``: an NWS watch, warning or advisory."""

    external_id: str
    event: str
    severity: str | None = None
    onset: datetime | None = None
    expires: datetime | None = None
    headline: str | None = None
    description: str | None = None

    #: Events the frost guard cares about. An Excessive Heat Warning is a real
    #: advisory and not this engine's business.
    FROST_EVENTS = ("Frost Advisory", "Freeze Warning", "Freeze Watch", "Hard Freeze")

    @property
    def is_frost(self) -> bool:
        return any(self.event.startswith(prefix) for prefix in self.FROST_EVENTS)

    def covers(self, moment: datetime) -> bool:
        """Is this advisory in force at ``moment``?

        An advisory with no stated window is treated as in force: NWS omits
        ``onset`` on messages that take effect immediately, and reading that
        omission as "not yet" would drop exactly the urgent ones.
        """
        if self.onset is not None and moment < self.onset:
            return False
        return not (self.expires is not None and moment > self.expires)

    def to_row(self, site_id: str) -> dict[str, Any]:
        return {
            "site_id": site_id,
            "external_id": self.external_id,
            "event": self.event,
            "severity": self.severity,
            "onset": self.onset,
            "expires": self.expires,
            "headline": self.headline,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SourceResult:
    """What one source came back with, and what went wrong if anything did."""

    source: str
    observations: tuple[Observation, ...] = ()
    forecasts: tuple[Forecast, ...] = ()
    advisories: tuple[Advisory, ...] = ()
    #: Set when the source could not be reached. A source that is down must not
    #: look like a source that said "nothing to report".
    error: str | None = None
    is_mock: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def is_empty(self) -> bool:
        return not (self.observations or self.forecasts or self.advisories)


def as_float(value: Any) -> float | None:
    """A number, or ``None`` — never a zero standing in for a missing reading."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # NaN is not a measurement; a source that sends one has said nothing.
    return None if math.isnan(number) else number


def parse_time(value: Any, *, assume_utc: bool = True) -> datetime | None:
    """ISO-8601 in, aware UTC out.

    Open-Meteo returns naive stamps and a ``timezone`` field; we always ask for
    UTC. NWS returns offsets. Everything is stored UTC (``timestamptz``), so
    this is the one place the two conventions meet.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC) if assume_utc else None
    return moment.astimezone(UTC)
