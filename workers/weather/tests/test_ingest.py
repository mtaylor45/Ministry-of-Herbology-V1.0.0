"""Ingest: the fallback, and what it is honest about.

The contract makes Open-Meteo primary and NWS secondary. The thing worth
testing is not that the happy path works — it is that a rescued run still says
it was rescued, because NWS publishes no ET₀ and a household running on it for
a week should be able to find that out.
"""

from datetime import date

import pytest

from workers.weather.ingest import IngestReport, Site, WeatherIngest, backfill_window
from workers.weather.mocks.fetcher import RecordedFetcher, UnavailableFetcher
from workers.weather.sources.base import FetchResult, SourceUnavailable

SITE_WITH_STATION = "KIND"


@pytest.fixture
def ingest(fetcher, settings):
    return WeatherIngest(fetcher, settings)


class HalfDownFetcher:
    """Open-Meteo refuses; NWS answers from the recordings."""

    def __init__(self, delegate: RecordedFetcher) -> None:
        self.delegate = delegate
        self.calls: list[str] = []

    async def get_json(self, kind, url, params=None) -> FetchResult:
        self.calls.append(kind)
        if kind == "open_meteo":
            raise SourceUnavailable("open_meteo: Daily API request limit exceeded")
        return await self.delegate.get_json(kind, url, params)


def test_the_primary_source_answers_and_is_named(ingest, site, run):
    report = run(ingest.forecast(site))
    assert report.ok
    assert report.sources == {"forecast": "open_meteo"}
    assert not report.used_fallback
    assert len(report.forecasts) > 10


def test_a_failed_primary_falls_back_to_nws_and_says_so(settings, site, run, fetcher):
    report = run(WeatherIngest(HalfDownFetcher(fetcher), settings).forecast(site))

    assert report.forecasts, "the fallback has to actually produce a forecast"
    assert report.sources == {"forecast": "nws"}
    assert report.used_fallback
    # Rescued, but not silent: the failure is still on the report.
    assert report.errors and "limit exceeded" in report.errors[0]
    assert not report.ok


def test_the_fallback_forecast_carries_no_et0(settings, site, run, fetcher):
    """Which is exactly the case the design Hargreaves fallback exists for."""
    report = run(WeatherIngest(HalfDownFetcher(fetcher), settings).forecast(site))
    assert all(row.et0_mm is None for row in report.forecasts)
    assert all(row.source == "nws" for row in report.forecasts)


def test_both_sources_down_reports_rather_than_raises(settings, site, run):
    report = run(WeatherIngest(UnavailableFetcher(), settings).forecast(site))
    assert report.forecasts == ()
    assert report.errors
    assert not report.ok
    assert report.sources == {}


def test_observations_have_no_fallback_unless_a_station_is_configured(
    settings, site, run, fetcher
):
    """Not a misconfiguration — the gap surfaces as staleness, not as silence."""
    assert site.nws_station is None
    report = run(WeatherIngest(HalfDownFetcher(fetcher), settings).observations(site))
    assert report.observations == ()
    assert report.errors


def test_a_configured_station_rescues_the_observation_path(
    settings, site, run, fetcher
):
    from dataclasses import replace

    with_station = replace(site, nws_station=SITE_WITH_STATION)
    report = run(
        WeatherIngest(HalfDownFetcher(fetcher), settings).observations(with_station)
    )
    assert len(report.observations) == 1
    assert report.sources == {"observations": "nws"}
    assert report.used_fallback


def test_nws_answering_for_advisories_is_not_a_fallback(ingest, site, run):
    """NWS is the only source that publishes them.

    Counting it as a fallback would put a caveat on every Almanac response
    forever, which is how a caveat stops meaning anything.
    """
    report = run(ingest.advisories(site))
    assert report.ok
    assert report.sources == {"advisories": "nws"}
    assert not report.used_fallback


def test_no_advisories_in_force_is_a_clean_run(ingest, site, run):
    report = run(ingest.advisories(site))
    assert report.advisories == ()
    assert report.ok, "the normal state of the world is not an error"


def test_a_site_with_no_zone_cannot_be_asked_about_advisories(settings, run, fetcher):
    from dataclasses import replace

    from workers.weather import world

    site = replace(world.site(settings), nws_zone=None)
    report = run(WeatherIngest(fetcher, settings).advisories(site))
    assert not report.ok
    assert "names no zone" in report.errors[0]


def test_the_archive_is_open_meteo_only(ingest, site, run):
    """NWS has no archive to offer, so there is nothing to fall back to."""
    report = run(ingest.history(site, start=date(2026, 5, 1), end=date(2026, 5, 5)))
    assert report.ok
    assert report.sources == {"history": "open_meteo"}
    assert report.observations


def test_the_backfill_window_stops_short_of_the_archive_s_lag():
    """Open-Meteo's archive lags about five days; asking for yesterday is a gap."""
    start, end = backfill_window(30, today=date(2026, 6, 20))
    assert end == date(2026, 6, 15)
    assert start == date(2026, 5, 16)
    assert (end - start).days == 30


def test_the_grid_url_is_resolved_once_per_site(settings, site, run, fetcher):
    down = HalfDownFetcher(fetcher)
    ingest = WeatherIngest(down, settings)
    run(ingest.forecast(site))
    run(ingest.forecast(site))
    assert down.calls.count("nws") == 3, "one /points lookup, then two forecasts"


def test_a_report_serialises_to_something_worth_reading():
    report = IngestReport(site_id="s", errors=("nws: 503",))
    payload = report.to_dict()
    assert payload["errors"] == ["nws: 503"]
    assert payload["used_fallback"] is False
    assert payload["observations"] == 0


def test_a_site_reads_out_of_the_frozen_fixture(fixture):
    site = Site.from_fixture(fixture("site.json"))
    assert site.latitude == pytest.approx(39.7684)
    assert site.timezone == "America/Indiana/Indianapolis"
    assert site.nws_station is None
