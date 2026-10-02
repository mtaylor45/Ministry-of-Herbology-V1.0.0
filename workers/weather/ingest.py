"""Ingest: ask the sources, fall back, and hand rows to the store.

The orchestration the Arq jobs in ``tasks.py`` call. It holds exactly one
policy, which is the contract's: **Open-Meteo is primary, NWS is secondary.**
Everything else here exists to make a failure visible instead of quiet.

Three rules this module keeps:

* **A source that is down is recorded as down.** ``IngestReport.errors`` carries
  every failure even when the fallback rescued the run, because "we have been
  running on NWS for nine days" is something a household should be able to find
  out, and NWS publishes no ET₀.
* **A fallback is labelled, not blended.** Rows carry the source that produced
  them; nothing merges two sources into one hour.
* **An empty answer is an answer.** No advisories in force is the normal state
  of the world, and it is not an error — see ``sources/base.SourceUnavailable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from .settings import WeatherSettings, get_settings
from .sources.base import NWS, OPEN_METEO, Advisory, Fetcher, Forecast, Observation
from .sources.nws import NwsSource
from .sources.openmeteo import OpenMeteoSource


@dataclass(frozen=True, slots=True)
class Site:
    """What the ingest needs to know about a place. Mirrors ``site`` in the schema."""

    id: str
    latitude: float
    longitude: float
    timezone: str = "UTC"
    nws_zone: str | None = None
    #: An NWS station id (``KIND``). Optional, and usually unset: Open-Meteo's
    #: own recent actuals are the observation path, and a station is only a
    #: fallback for when Open-Meteo cannot be reached at all.
    nws_station: str | None = None

    @classmethod
    def from_fixture(cls, row: dict[str, Any]) -> Site:
        return cls(
            id=str(row["id"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            timezone=str(row.get("timezone") or "UTC"),
            nws_zone=row.get("nws_zone"),
            nws_station=row.get("nws_station"),
        )


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What one run did, and what it could not do."""

    site_id: str
    observations: tuple[Observation, ...] = ()
    forecasts: tuple[Forecast, ...] = ()
    advisories: tuple[Advisory, ...] = ()
    #: Which source actually answered, per kind. ``{}`` where nothing did.
    sources: dict[str, str] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    is_mock: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    #: Kinds for which Open-Meteo is primary. Advisories are not among them:
    #: NWS is the only source that publishes them, so NWS answering there is
    #: the normal path, not a degradation, and reporting it as a fallback would
    #: put a caveat on every Almanac response forever.
    PRIMARY_KINDS: ClassVar[tuple[str, ...]] = ("forecast", "observations", "history")

    @property
    def used_fallback(self) -> bool:
        return any(
            source == NWS
            for kind, source in self.sources.items()
            if kind in self.PRIMARY_KINDS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "observations": len(self.observations),
            "forecasts": len(self.forecasts),
            "advisories": len(self.advisories),
            "sources": dict(self.sources),
            "used_fallback": self.used_fallback,
            "errors": list(self.errors),
            "is_mock": self.is_mock,
        }


class WeatherIngest:
    """Open-Meteo first, NWS second, and a report either way."""

    def __init__(
        self, fetcher: Fetcher, settings: WeatherSettings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.fetcher = fetcher
        self.open_meteo = OpenMeteoSource(
            fetcher,
            forecast_url=self.settings.open_meteo_forecast_url,
            archive_url=self.settings.open_meteo_archive_url,
        )
        self.nws = NwsSource(fetcher, base_url=self.settings.nws_base_url)
        self._grid_urls: dict[str, str | None] = {}

    # ------------------------------------------------------------- forecast

    async def forecast(self, site: Site) -> IngestReport:
        primary = await self.open_meteo.fetch_forecast(
            site.latitude, site.longitude, days=self.settings.forecast_days
        )
        if primary.ok and primary.forecasts:
            return IngestReport(
                site_id=site.id,
                forecasts=primary.forecasts,
                sources={"forecast": OPEN_METEO},
                is_mock=primary.is_mock,
            )

        errors = [primary.error] if primary.error else ["open_meteo: empty forecast"]
        grid_url = await self._grid_url(site)
        if grid_url is None:
            return IngestReport(site_id=site.id, errors=tuple(errors))

        secondary = await self.nws.fetch_forecast(grid_url)
        if not secondary.ok:
            errors.append(secondary.error or "nws: empty forecast")
            return IngestReport(site_id=site.id, errors=tuple(errors))
        return IngestReport(
            site_id=site.id,
            forecasts=secondary.forecasts,
            sources={"forecast": NWS},
            errors=tuple(errors),
            is_mock=secondary.is_mock,
        )

    # --------------------------------------------------------- observations

    async def observations(self, site: Site) -> IngestReport:
        primary = await self.open_meteo.fetch_observations(
            site.latitude, site.longitude, past_days=self.settings.observation_past_days
        )
        if primary.ok and primary.observations:
            return IngestReport(
                site_id=site.id,
                observations=primary.observations,
                sources={"observations": OPEN_METEO},
                is_mock=primary.is_mock,
            )

        errors = [primary.error] if primary.error else ["open_meteo: no observations"]
        if not site.nws_station:
            # No station configured is not a misconfiguration: Open-Meteo is the
            # observation path, and the gap this leaves surfaces as staleness on
            # the water balance rather than as silence.
            return IngestReport(site_id=site.id, errors=tuple(errors))

        secondary = await self.nws.fetch_observation(site.nws_station)
        if not secondary.ok or not secondary.observations:
            errors.append(secondary.error or "nws: no observation")
            return IngestReport(site_id=site.id, errors=tuple(errors))
        return IngestReport(
            site_id=site.id,
            observations=secondary.observations,
            sources={"observations": NWS},
            errors=tuple(errors),
            is_mock=secondary.is_mock,
        )

    async def history(self, site: Site, *, start: date, end: date) -> IngestReport:
        """Archive backfill. Open-Meteo only — NWS has no archive to offer."""
        result = await self.open_meteo.fetch_history(
            site.latitude, site.longitude, start=start, end=end
        )
        if not result.ok:
            return IngestReport(
                site_id=site.id, errors=(result.error or "open_meteo: archive refused",)
            )
        return IngestReport(
            site_id=site.id,
            observations=result.observations,
            sources={"history": OPEN_METEO} if result.observations else {},
            is_mock=result.is_mock,
        )

    # ------------------------------------------------------------ advisories

    async def advisories(self, site: Site) -> IngestReport:
        """NWS only. Nobody else publishes them, so there is no fallback."""
        if not site.nws_zone:
            return IngestReport(
                site_id=site.id, errors=("nws: the site names no zone",)
            )
        result = await self.nws.fetch_advisories(site.nws_zone)
        if not result.ok:
            return IngestReport(
                site_id=site.id, errors=(result.error or "nws: refused",)
            )
        return IngestReport(
            site_id=site.id,
            advisories=result.advisories,
            sources={"advisories": NWS},
            is_mock=result.is_mock,
        )

    # ----------------------------------------------------------------- misc

    async def _grid_url(self, site: Site) -> str | None:
        """Resolve and remember the NWS gridpoint forecast URL for a site.

        A site does not move between grid cells, so this is asked once per
        process. A failure here is not fatal — it only means the fallback has
        no fallback, which the caller reports.
        """
        if site.id in self._grid_urls:
            return self._grid_urls[site.id]
        try:
            point = await self.nws.resolve_point(site.latitude, site.longitude)
            url = point.get("forecast_url")
        except Exception:  # noqa: BLE001 — any failure here is just "no fallback"
            url = None
        self._grid_urls[site.id] = url
        return url


def backfill_window(days: int, *, today: date | None = None) -> tuple[date, date]:
    """The archive window for a backfill of ``days``.

    Open-Meteo's archive lags real time by about five days, so a window that
    runs to yesterday comes back short. Ending five days back means the caller
    gets what exists rather than a gap it has to notice.
    """
    end = (today or datetime.now(UTC).date()) - timedelta(days=5)
    return end - timedelta(days=days), end
