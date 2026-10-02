"""The whole chain, through the running app — the weather engine, an earlier release.

The releases's exit criterion is *rain visibly clears due waterings*, and on
``main`` ``GET /api/v1/tending/rounds`` returned ``satisfied: []`` against every
fixture. The engine was not the reason: replayed directly, it marked the storm's
rain day ``satisfied`` exactly as ``fixtures/scenarios/storm.json`` expects. The
reason was that the *running app* could not be put under a scenario at all, so
the only weather it ever saw was ``weather/baseline_30d.json``, whose closing
fortnight has no downpour big enough to clear anybody's deficit.

This file drives the same path an operator does — environment variables, then
HTTP — across all four links:

    rainfall → water balance → ``status: satisfied`` / ``satisfied_by: rain``
              → ``api/tending/domain.py`` → the ``satisfied`` section of the round

It is deliberately an end-to-end test rather than four unit tests. Each link
was individually sound on ``main`` and the chain still produced nothing, which
is precisely the class of defect a unit test cannot see.

``tests/`` and ``fixtures/`` are the test suite's and are not touched here; this
is the weather engine's own suite, reading the frozen scenario L already owns.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from workers.weather import world
from workers.weather.settings import WeatherSettings
from workers.weather.settings import get_settings as weather_settings


def storm_rain_day() -> str:
    """The day ``storm``'s 38 mm falls, read from the recording, not restated.

    ``fixtures/`` is the test suite's and ``storm`` has been re-cut twice inside this release —
    the rain on the closing day in one shape, mid-series with trailing days in
    another. Both are defensible and neither is the weather engine's call. So the day is *found*,
    the way the engine finds it, and the test below stands on it explicitly via
    ``MOH_SCENARIO_DAY`` rather than relying on where it happens to sit. A test
    that copies a number out of a file it does not own holds a stale second copy
    of somebody else's data.

    The one property this does assert is the one the storm story needs: a single
    downpour. A recording with two would make "the rain day" ambiguous, and the
    failure should say so in a sentence rather than as ``0.0 == 38.0``.
    """
    rows = world.weather_rows(WeatherSettings(), scenario="storm")
    wet = [row for row in rows if row["precip_mm"]]
    assert len(wet) == 1, (
        f"storm is no longer a single-downpour recording ({len(wet)} wet days), "
        "so which day the storm story stands on is no longer obvious"
    )
    return str(wet[0]["date"])


LEMON_ON_TERRACE = "01890040-0000-7000-8000-000000000004"  # 45 L, open sky
LEMON_ON_PORCH = "01890040-0000-7000-8000-000000000005"  # 25 L, under a roof


@pytest.fixture
def under_storm(monkeypatch: pytest.MonkeyPatch):
    """The app as an operator running the storm demo would have it.

    Set through the environment rather than by handing a settings object
    around, because the environment is the only route a deployment has and a demo that works only
    from Python has not been demonstrated.
    """
    from app.main import app

    # Standing *on* the rain day, stated rather than assumed. When the recording
    # ends there this is a no-op; when it carries trailing dry days it is the
    # whole point — a balance replayed past the rain honestly reports the deficit
    # that has rebuilt since, which is the right answer to a different question.
    monkeypatch.setenv("MOH_SCENARIO", "storm")
    monkeypatch.setenv("MOH_SCENARIO_DAY", storm_rain_day())
    weather_settings.cache_clear()
    yield TestClient(app)
    weather_settings.cache_clear()


@pytest.fixture
def unset(monkeypatch: pytest.MonkeyPatch):
    """The shipped default: no scenario, the baseline recording."""
    from app.main import app

    monkeypatch.delenv("MOH_SCENARIO", raising=False)
    monkeypatch.delenv("MOH_SCENARIO_DAY", raising=False)
    weather_settings.cache_clear()
    yield TestClient(app)
    weather_settings.cache_clear()


def rounds(client: TestClient) -> dict:
    response = client.get("/api/v1/tending/rounds")
    assert response.status_code == 200
    return response.json()


def balance(client: TestClient, specimen_id: str) -> dict:
    response = client.get(f"/api/v1/almanac/water-balance/{specimen_id}")
    assert response.status_code == 200
    return response.json()


def test_rain_clears_a_due_watering_all_the_way_to_morning_rounds(under_storm):
    """The exit criterion, end to end and on the wire."""
    settled = rounds(under_storm)["satisfied"]

    assert settled, "38 mm of rain settled nothing that the round shows"
    assert all(task["status"] == "satisfied" for task in settled)
    assert {task["satisfied_by"] for task in settled} == {"rain"}
    assert LEMON_ON_TERRACE in {task["specimen"]["id"] for task in settled}


def test_the_settled_watering_keeps_its_place_rather_than_vanishing(under_storm):
    """The plan is explicit: the task must not simply disappear overnight.

    Somebody who saw "water the lemon" yesterday needs to be told the sky did
    it, not left wondering whether they imagined the task.
    """
    settled = next(
        task
        for task in rounds(under_storm)["satisfied"]
        if task["specimen"]["id"] == LEMON_ON_TERRACE
    )
    assert settled["task_type"] == "water"
    assert settled["plain_title"], "the plain-language equivalent, always"
    assert settled["id"] and settled["due_at"]


def test_the_balance_underneath_it_attributes_the_rain(under_storm):
    """The link the scheduler reads. ``status`` and ``satisfied_by`` are the weather engine's words
    for it."""
    payload = balance(under_storm, LEMON_ON_TERRACE)
    assert payload["status"] == "satisfied"
    assert payload["satisfied_by"] == "rain"
    assert payload["is_due"] is False
    assert payload["deficit_mm"] == 0.0

    rain_day = payload["days"][-1]
    assert rain_day["day"] == storm_rain_day()
    assert rain_day["status"] == "satisfied"
    assert rain_day["precip_mm"] == 38.0


def test_a_plant_under_a_roof_is_not_watered_by_rain_it_never_saw(under_storm):
    """``f_cover`` is the most commonly got-wrong term in the equation.

    The same downpour, the same site, the same day: a lemon on the covered
    porch still owes a watering, and the scenario says so in its own words.
    """
    payload = balance(under_storm, LEMON_ON_PORCH)
    assert payload["cover_factor"] == 0.0
    assert payload["status"] == "due"
    assert payload["satisfied_by"] is None

    due = {task["specimen"]["id"] for task in rounds(under_storm)["due"]}
    assert LEMON_ON_PORCH in due


def test_the_almanac_shows_the_same_week_the_balance_ran_on(under_storm):
    """One deployment, one weather. Two loaders is how those come apart.

    The history ends where the balance ends — on the wet day — and the forecast
    is drawn from the same recording rather than from the baseline. Every date on
    both screens belongs to ``storm``.

    What is deliberately *not* asserted is that the forecast begins on the day
    the balance calls today. A recording has no future: with no
    ``MOH_SCENARIO_DAY`` set the balance's newest day is the recording's last,
    and a forecast anchored there would hold exactly one day. Mock mode has
    presented a historical recording read forwards as "the forecast" —
    ``days[:10]`` — so on an eleven-day recording like ``storm`` the ten-day
    forecast stops one day short of the day the balance is standing on. That is
    the earlier shape rather than this switch's, it is raised with the maintainers rather than
    quietly changed here, and setting the day *does* anchor both together, which
    the test below shows.
    """
    storm_dates = {
        row["date"] for row in world.weather_rows(WeatherSettings(), scenario="storm")
    }

    forecast = under_storm.get(
        "/api/v1/almanac/forecast", params={"site_id": "x", "horizon": "daily"}
    ).json()
    assert forecast, "a deployment under a scenario still has an Almanac"
    assert {
        row["time"][:10] for row in forecast
    } <= storm_dates, (
        "the forecast is drawn from the selected recording, not the baseline"
    )

    history = under_storm.get(
        "/api/v1/almanac/history", params={"window": "7d", "metric": "precip_mm"}
    ).json()
    assert history["values"][-1] == 38.0, "the history ends on the wet day too"

    balance_days = {
        day["day"] for day in balance(under_storm, LEMON_ON_TERRACE)["days"]
    }
    assert balance_days <= storm_dates


def test_standing_on_a_day_anchors_the_forecast_to_it(monkeypatch):
    """``MOH_SCENARIO_DAY`` is where the operator is, so the forecast starts there."""
    from app.main import app

    rows = world.weather_rows(WeatherSettings(), scenario="storm")
    mid = rows[len(rows) // 2]["date"]

    monkeypatch.setenv("MOH_SCENARIO", "storm")
    monkeypatch.setenv("MOH_SCENARIO_DAY", mid)
    weather_settings.cache_clear()
    try:
        client = TestClient(app)
        forecast = client.get(
            "/api/v1/almanac/forecast", params={"site_id": "x", "horizon": "daily"}
        ).json()
        assert forecast[0]["time"].startswith(mid), "the forecast starts where you are"

        payload = balance(client, LEMON_ON_TERRACE)
        assert payload["days"][-1]["day"] == mid, "and the history ends there"
    finally:
        weather_settings.cache_clear()


def test_the_certainty_survives_the_trip_to_the_instruction(under_storm):
    """the task a person acts on carries the doubt, not just the API.

    A watering settled by a modelled deficit is still a modelled deficit, and
    nothing measures the soil.
    """
    settled = next(
        task
        for task in rounds(under_storm)["satisfied"]
        if task["specimen"]["id"] == LEMON_ON_TERRACE
    )
    assert settled["confidence"] in {"high", "medium", "low", "unknown"}
    assert settled["confidence"] != "high", "nothing measured this soil"
    assert "degraded" in settled and "degradations" in settled


def test_an_unset_scenario_leaves_the_deployment_exactly_as_it_was(unset):
    """The switch is opt-in: a deployment that sets nothing reads the baseline.

    What is asserted is that it is the *baseline* recording, not a scenario —
    deliberately not the baseline's own numbers. L re-cut its closing day from
    6 mm to 32 mm, which is the test suite's call over the test suite's file, and a test of the
    weather engine's switch that
    fails because of it was testing the wrong thing.
    """
    from workers.weather import world

    baseline_last = world.weather_rows(WeatherSettings())[-1]["date"]
    storm_days = {
        row["date"] for row in world.weather_rows(WeatherSettings(), scenario="storm")
    }

    payload = balance(unset, LEMON_ON_TERRACE)
    assert payload["days"][-1]["day"] == baseline_last
    assert payload["days"][-1]["day"] not in storm_days

    day = rounds(unset)
    assert day["due"] or day["satisfied"], "the round still speaks for the garden"
