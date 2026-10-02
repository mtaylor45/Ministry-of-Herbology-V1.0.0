"""Open-Meteo: the column-oriented parser, and the two error bodies.

The success payloads are synthesised from the frozen fixtures in Open-Meteo's
own shape (see ``mocks/recorded/PROVENANCE.md``); the error payloads are real.
"""

from datetime import UTC, date, datetime

import pytest

from workers.weather.sources.base import CONDITIONS, SourceUnavailable
from workers.weather.sources.openmeteo import (
    OpenMeteoSource,
    condition_from_wmo,
    parse_daily_forecast,
    parse_hourly_observations,
)

ISSUED = datetime(2026, 9, 23, 20, 0, tzinfo=UTC)


@pytest.fixture
def source(fetcher):
    return OpenMeteoSource(fetcher)


def test_wmo_codes_map_onto_the_shared_vocabulary():
    assert condition_from_wmo(0) == "clear"
    assert condition_from_wmo(2) == "partly_cloudy"
    assert condition_from_wmo(3) == "cloudy"
    assert condition_from_wmo(45) == "fog"
    assert condition_from_wmo(63) == "rain"
    assert condition_from_wmo(73) == "snow"
    assert condition_from_wmo(81) == "rain"
    assert condition_from_wmo(95) == "storm"
    for code in range(100):
        mapped = condition_from_wmo(code)
        assert mapped is None or mapped in CONDITIONS


def test_freezing_rain_is_rain_not_snow():
    """It falls as liquid. Whether the ground is lethal is the frost guard's job."""
    assert condition_from_wmo(66) == "rain"
    assert condition_from_wmo(67) == "rain"


def test_an_unknown_code_says_nothing_rather_than_guessing():
    assert condition_from_wmo(None) is None
    assert condition_from_wmo("drizzle") is None
    assert condition_from_wmo(4) is None


def test_the_daily_forecast_carries_everything_the_almanac_shows(source, run):
    result = run(source.fetch_forecast(39.7684, -86.1581, days=10))
    daily = [row for row in result.forecasts if row.horizon == "daily"]
    assert len(daily) == 10, "the plan calls for a 10-day forecast"
    first = daily[0]
    assert first.temp_min_c is not None and first.temp_max_c is not None
    assert first.et0_mm is not None, "ET₀ is the whole reason this source is primary"
    assert first.sunrise is not None and first.sunset is not None
    assert first.sunset > first.sunrise
    assert first.condition in CONDITIONS
    assert first.source == "open_meteo"


def test_the_hourly_forecast_is_hourly_and_ordered(source, run):
    result = run(source.fetch_forecast(39.7684, -86.1581, days=10))
    hourly = [row for row in result.forecasts if row.horizon == "hourly"]
    assert len(hourly) >= 24
    times = [row.time for row in hourly]
    assert times == sorted(times)
    assert (times[1] - times[0]).total_seconds() == 3600


def test_observations_never_include_the_future():
    """A forecast hour stored as an observation is rain that never fell.

    One request carries both halves, so the cut is the parser's to make.
    """
    payload = {
        "hourly": {
            "time": ["2026-06-01T10:00", "2026-06-01T11:00", "2026-06-01T12:00"],
            "temperature_2m": [15.0, 16.0, 17.0],
            "precipitation": [0.0, 0.0, 40.0],
        }
    }
    cutoff = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
    rows = parse_hourly_observations(payload, before=cutoff)
    assert [row.time.hour for row in rows] == [10, 11]
    assert all(row.precip_mm == 0.0 for row in rows)


def test_a_variable_that_was_not_requested_is_none_not_zero():
    """Zero rainfall is a claim about the weather. Absence is not."""
    payload = {"hourly": {"time": ["2026-06-01T10:00"], "temperature_2m": [15.0]}}
    row = parse_hourly_observations(payload)[0]
    assert row.temperature_c == 15.0
    assert row.precip_mm is None
    assert row.et0_mm is None
    assert row.condition is None


def test_a_null_inside_an_array_is_none_not_zero():
    payload = {
        "hourly": {
            "time": ["2026-06-01T10:00", "2026-06-01T11:00"],
            "precipitation": [None, 2.0],
        }
    }
    rows = parse_hourly_observations(payload)
    assert rows[0].precip_mm is None
    assert rows[1].precip_mm == 2.0


def test_a_short_array_does_not_fall_off_the_end():
    """Open-Meteo pads its arrays; a parser that assumes it would crash if not."""
    payload = {
        "hourly": {
            "time": ["2026-06-01T10:00", "2026-06-01T11:00"],
            "temperature_2m": [15.0],
        }
    }
    rows = parse_hourly_observations(payload)
    assert [row.temperature_c for row in rows] == [15.0, None]


def test_an_unparseable_timestamp_drops_its_row_and_keeps_the_rest():
    payload = {
        "hourly": {
            "time": ["not-a-time", "2026-06-01T11:00"],
            "temperature_2m": [99.0, 16.0],
        }
    }
    rows = parse_hourly_observations(payload)
    assert [row.temperature_c for row in rows] == [16.0]


def test_a_naive_timestamp_is_read_as_utc():
    """We always ask for ``timezone=UTC``; everything is stored ``timestamptz``."""
    row = parse_hourly_observations(
        {"hourly": {"time": ["2026-06-01T10:00"], "temperature_2m": [1.0]}}
    )[0]
    assert row.time.tzinfo is not None
    assert row.time == datetime(2026, 6, 1, 10, 0, tzinfo=UTC)


def test_an_empty_payload_parses_to_nothing_rather_than_raising():
    assert parse_hourly_observations({}) == ()
    assert parse_daily_forecast({"daily": None}, issued_at=ISSUED) == ()
    assert parse_hourly_observations({"hourly": {"time": "not a list"}}) == ()


def test_the_archive_returns_only_the_days_it_covers(source, run):
    """A window past the archive's reach comes back empty, not invented."""
    inside = run(
        source.fetch_history(
            39.7684, -86.1581, start=date(2026, 5, 1), end=date(2026, 5, 3)
        )
    )
    assert inside.ok
    assert {row.time.date() for row in inside.observations} == {
        date(2026, 5, 1),
        date(2026, 5, 2),
        date(2026, 5, 3),
    }

    outside = run(
        source.fetch_history(
            39.7684, -86.1581, start=date(2031, 1, 1), end=date(2031, 1, 5)
        )
    )
    assert outside.ok and outside.observations == ()


def test_hourly_et0_sums_back_to_the_daily_figure(source, run, fixture):
    """The rollups sum these hours. Hours that do not add up break weather_daily."""
    result = run(
        source.fetch_history(
            39.7684, -86.1581, start=date(2026, 5, 1), end=date(2026, 5, 5)
        )
    )
    totals: dict[date, float] = {}
    for row in result.observations:
        totals[row.time.date()] = totals.get(row.time.date(), 0.0) + (row.et0_mm or 0.0)
    expected = {
        date.fromisoformat(day["date"]): day["et0_mm"]
        for day in fixture("weather/baseline_30d.json")["days"]
    }
    for day, total in totals.items():
        assert total == pytest.approx(expected[day], abs=0.02)


def test_hourly_rainfall_sums_back_to_the_daily_figure(source, run, fixture):
    result = run(
        source.fetch_history(
            39.7684, -86.1581, start=date(2026, 5, 4), end=date(2026, 5, 6)
        )
    )
    totals: dict[date, float] = {}
    for row in result.observations:
        totals[row.time.date()] = totals.get(row.time.date(), 0.0) + (
            row.precip_mm or 0.0
        )
    expected = {
        date.fromisoformat(day["date"]): day["precip_mm"]
        for day in fixture("weather/baseline_30d.json")["days"]
    }
    assert totals[date(2026, 5, 5)] == pytest.approx(
        expected[date(2026, 5, 5)], abs=0.05
    )


def test_a_source_that_is_down_is_reported_not_raised(run, settings):
    """A failure must reach the caller as a result it can caveat."""
    from workers.weather.mocks.fetcher import UnavailableFetcher

    result = run(OpenMeteoSource(UnavailableFetcher()).fetch_forecast(39.0, -86.0))
    assert not result.ok
    assert result.forecasts == ()
    assert "unreachable" in (result.error or "")


def test_the_recorded_error_bodies_are_what_the_fetcher_rejects(payload):
    """Open-Meteo answers some failures with a body, not only a status.

    Both of these were returned by the live service; ``error__rate-limited``
    is why this branch has no recorded success payloads at all.
    """
    rate_limited = payload("open_meteo/error__rate-limited.json")
    bad_variable = payload("open_meteo/error__unknown-variable.json")
    assert rate_limited["error"] is True
    assert "limit exceeded" in rate_limited["reason"]
    assert bad_variable["error"] is True

    # The guard the HTTP fetcher applies, exercised on the real bodies.
    for body in (rate_limited, bad_variable):
        assert isinstance(body, dict) and body.get("error")


def test_the_mock_fetcher_stamps_everything_it_synthesises(fetcher, run):
    """A synthesised payload must never pass for a fetch."""
    result = run(
        fetcher.get_json(
            "open_meteo",
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": 39.7, "longitude": -86.1, "daily": "x", "forecast_days": 3},
        )
    )
    assert result.is_mock
    assert result.payload["_synthetic"]["from"].endswith("baseline_30d.json")


def test_a_kind_with_nothing_to_replay_or_synthesise_fails_loudly(fetcher, run):
    with pytest.raises(SourceUnavailable):
        run(fetcher.get_json("meteomatics", "https://example.invalid/forecast"))
