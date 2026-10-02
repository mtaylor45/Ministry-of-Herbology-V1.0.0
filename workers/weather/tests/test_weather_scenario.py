"""Putting the running deployment under a recorded week — the weather engine.

``fixtures/scenarios/`` has held ``drought``, ``storm`` and ``frost``
and nothing but a unit test could read them: ``world.weather_days``
took a ``scenario=`` argument and every caller in the running app left it out.
So the app was permanently on ``weather/baseline_30d.json``, and the releases's
exit criterion — *rain visibly clears due waterings* — could not be shown to
anybody, in a test or in a browser.

``MOH_SCENARIO`` and ``MOH_SCENARIO_DAY`` are that switch. They are operator
inputs under no usable default, unset in every shipped deployment, and
documented rather than discovered. These tests hold the two properties that make
them worth having — the API and the worker read the *same* setting, and an unset
setting changes nothing at all.

**Nothing here restates what is in a fixture.** The first version of this file
hard-coded ``storm``'s rain on 2026-07-07, and L — who owns ``fixtures/`` — re-cut
the recording so the rain falls on its *last* day, which is the better fixture and
broke six of these tests. A test that copies a number out of a file it does not
own has taken a second, stale copy of somebody else's data. So the rain day is
*found* in the recording, the way the engine finds it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from workers.weather import world
from workers.weather.settings import WeatherSettings


def rain_day(settings: WeatherSettings, scenario: str) -> date:
    """The day the recording's rain falls, read from the recording itself."""
    wet = [
        row
        for row in world.weather_rows(settings, scenario=scenario)
        if row["precip_mm"]
    ]
    assert len(wet) == 1, f"{scenario} is no longer a single-downpour recording"
    return date.fromisoformat(wet[0]["date"])


@pytest.fixture
def baseline(settings: WeatherSettings) -> WeatherSettings:
    return settings


@pytest.fixture
def storm(settings: WeatherSettings) -> WeatherSettings:
    return settings.model_copy(update={"scenario": "storm"})


@pytest.fixture
def storm_on_the_rain_day(settings: WeatherSettings) -> WeatherSettings:
    """``storm``, standing on the day it rains — stated, not assumed.

    ``storm`` has been re-cut twice inside this release: the downpour on the
    closing day in one shape, mid-series with trailing dry days in another. Both
    are the test suite's call over the test suite's file, so nothing here depends on which it is.
    Setting
    the day is a no-op in the first shape and the whole point in the second.
    """
    base = settings.model_copy(update={"scenario": "storm"})
    return base.model_copy(update={"scenario_day": rain_day(base, "storm")})


# ------------------------------------------------------------------ the switch


def test_an_unset_scenario_is_the_baseline_recording(baseline):
    """The shipped default. Nothing about an earlier release changes what a deployment does."""
    assert world.active_scenario(baseline) is None
    assert world.as_of_day(baseline) is None

    days = world.weather_days(baseline)
    assert len(days) == 30
    assert days[0].day == date(2026, 5, 1)


def test_selecting_a_scenario_changes_what_the_weather_is(storm):
    assert world.active_scenario(storm) == "storm"
    days = world.weather_days(storm)
    assert days[0].day == date(2026, 7, 1)
    assert [day.precip_mm for day in days if day.precip_mm] == [38.0]
    assert rain_day(storm, "storm") in {day.day for day in days}


def test_the_as_of_day_ends_the_series_there(storm, storm_on_the_rain_day):
    """The balance is a history that ends *now*, so "now" has to be sayable.

    This is what the setting is *for*: a recording whose interesting day is not
    its last one. ``drought`` and ``frost`` are both about a day in the middle,
    and ``storm`` has been cut both ways inside this release.
    """
    wet = rain_day(storm, "storm")
    assert world.weather_days(storm_on_the_rain_day)[-1].day == wet
    assert world.weather_days(storm_on_the_rain_day)[-1].precip_mm == 38.0

    stopped_early = storm.model_copy(update={"scenario_day": wet - timedelta(days=2)})
    days = world.weather_days(stopped_early)
    assert days[-1].day == wet - timedelta(days=2)
    assert all(day.precip_mm == 0.0 for day in days), "stopped before the rain"

    # An explicit argument still wins, which is what the worker's
    # ``evaluate_water_balance(day=...)`` has always done.
    through = days[0].day
    assert world.weather_days(storm, through=through)[-1].day == through


def test_the_forecast_rows_and_the_balance_days_come_from_one_loader(storm):
    """Two loaders is how the Almanac shows rain the balance never saw."""
    rows = world.weather_rows(storm)
    days = world.weather_days(storm)
    assert [row["date"] for row in rows] == [day.day.isoformat() for day in days]
    assert "condition" in rows[0], "the screens need it; the equation does not"


def test_the_frost_guard_follows_the_operator_s_scenario_too(baseline, storm):
    """One deployment, one week of weather — both halves of the Almanac.

    With nothing selected this stays on ``frost``, where it has been:
    the baseline is a mild fortnight in May, and a frost endpoint that answers
    "nothing, ever" is not a mock of anything.
    """
    frost_lows = [night.low_c for night in world.frost_nights(baseline)]
    storm_lows = [night.low_c for night in world.frost_nights(storm)]
    assert min(frost_lows) < 0.0, "the baseline falls through to the frost recording"
    assert min(storm_lows) > 10.0, "a July storm has no frost in it"
    assert world.frost_nights(storm, scenario="frost")[0].low_c == frost_lows[0]


def test_a_scenario_that_does_not_exist_says_so(settings):
    """A typo must not read as "fine, no weather"."""
    bad = settings.model_copy(update={"scenario": "sotrm"})
    with pytest.raises(ValueError, match="names no recording"):
        world.weather_rows(bad)


def test_a_scenario_name_may_not_be_a_path():
    """It is interpolated into a filename, so it is checked on the way in."""
    for attempt in ("../../etc/passwd", "storm/../../secrets", "a b"):
        with pytest.raises(ValueError, match="plain fixture name"):
            WeatherSettings(scenario=attempt)
    assert WeatherSettings(scenario="  storm  ").scenario == "storm"
    assert WeatherSettings(scenario="").scenario is None


# -------------------------------------------------- the API and the worker agree


def test_the_endpoint_and_the_job_read_the_same_setting(storm_on_the_rain_day, run):
    """The one property worth a test all of its own.

    If the Almanac resolved the scenario and the worker did not, a deployment
    would serve a balance cleared by rain out of one process while the other
    wrote rows that never saw it, and the disagreement would surface as a task
    that reappears overnight.
    """
    from almanac import service as almanac

    from workers.weather import tasks

    settings = storm_on_the_rain_day
    lemon = "01890040-0000-7000-8000-000000000004"  # 45 L, open sky

    report = run(tasks.evaluate_water_balance({"settings": settings}))
    from_job = next(row for row in report["specimens"] if row["specimen_id"] == lemon)

    payload = almanac.water_balance(lemon, settings=settings)
    assert payload is not None
    assert payload["status"] == from_job["status"] == "satisfied"
    assert payload["deficit_mm"] == from_job["deficit_mm"]
    assert payload["satisfied_by"] == "rain"


def test_the_frost_lookahead_is_not_cut_off_at_today(settings):
    """The balance ends at today; the guard is about the nights after it.

    Truncating the frost series at ``MOH_WEATHER_SCENARIO_DAY`` would leave a
    deployment standing two nights before a freeze reporting no freeze — the
    quiet-app failure the design is about, with a dead lemon at the end of it
    rather than a stale number.
    """
    all_nights = world.frost_nights(settings.model_copy(update={"scenario": "frost"}))
    coldest = min(all_nights, key=lambda night: night.low_c)
    two_nights_before = coldest.day - timedelta(days=2)

    under_frost = settings.model_copy(
        update={"scenario": "frost", "scenario_day": two_nights_before}
    )
    assert world.weather_days(under_frost)[-1].day == two_nights_before

    nights = world.frost_nights(under_frost)
    assert max(night.day for night in nights) == max(n.day for n in all_nights)
    assert min(night.low_c for night in nights) == coldest.low_c, "the freeze is seen"

    from almanac import service as almanac

    alerts = almanac.frost(settings=under_frost)
    assert alerts, "a freeze two nights out must still raise"
    assert {alert["action"] for alert in alerts} <= {"bring_indoors", "cover"}


def test_a_day_outside_the_recording_is_refused(settings):
    """No weather is not "nothing to do"; it is a misconfiguration.

    An empty series advances no deficit, so every plant would read as
    comfortable and the app would go quiet — indistinguishable from a garden
    that needs nothing, which is the one failure this engine may never produce.
    """
    out_of_range = settings.model_copy(
        update={"scenario": "storm", "scenario_day": date(2026, 1, 1)}
    )
    with pytest.raises(ValueError, match="outside scenarios/storm.json"):
        world.weather_days(out_of_range)

    # The frost guard asking for its own recording by name is not affected by a
    # day that belongs to a different one.
    assert world.frost_nights(out_of_range, scenario="frost")
