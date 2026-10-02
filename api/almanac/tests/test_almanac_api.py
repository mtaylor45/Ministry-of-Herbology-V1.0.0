"""The four Almanac endpoints on the wire — the weather engine.

``tests/contract/`` owns the shapes the frozen contract declares. This file
owns the thing the contract does not yet carry and which the design makes
essential: **the response says how much it is worth.**

The app's screens' Almanac screen reads these next, so the field names here are a promise.

Run them the way CI does, from the repository root::

    .venv/bin/pytest tests api workers -q

``pytest api/almanac`` on its own works too, as of the root ``pytest.ini``.
It did not before: ``api/pyproject.toml`` carried the only pytest config, so
pytest made ``api/`` the rootdir, ``confcutdir`` followed it, and the
repository-root ``conftest.py`` that puts both source roots on ``sys.path`` was
never loaded — ``app.main`` could not import ``workers``. There is still only
one copy of that path mechanism, which is the point; it is now reachable from
every invocation rather than only some.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

SITE = "01890000-0000-7000-8000-000000000001"
LEMON_ON_TERRACE = "01890040-0000-7000-8000-000000000004"  # 45 L, open sky
LEMON_ON_PORCH = "01890040-0000-7000-8000-000000000005"  # 25 L, covered
MONSTERA_INDOORS = "01890040-0000-7000-8000-000000000001"
LAVENDER_HEDGE = "01890040-0000-7000-8000-000000000006"

CONFIDENCES = {"high", "medium", "low", "unknown"}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def under_storm(monkeypatch):
    """The same app, stood inside the storm recording.

    Function-scoped and cache-clearing on both sides: `get_settings` is cached,
    so a scenario left set would leak into the module-scoped `client` and the
    baseline tests would quietly start reading July.
    """
    from workers.weather.settings import get_settings

    monkeypatch.setenv("MOH_SCENARIO", "storm")
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def balance(client, specimen_id):
    response = client.get(f"/api/v1/almanac/water-balance/{specimen_id}")
    assert response.status_code == 200
    return response.json()


# ------------------------------------------------------------------ forecast


def test_the_daily_forecast_carries_et0_and_the_sun(client):
    """ET₀ is the number the water balance runs on; sunset is when frost tasks are due."""
    rows = client.get(
        "/api/v1/almanac/forecast", params={"site_id": SITE, "horizon": "daily"}
    ).json()
    assert len(rows) == 10
    first = rows[0]
    assert first["et0_mm"] is not None
    assert first["temp_min_c"] is not None and first["temp_max_c"] is not None
    assert first["sunrise"] < first["sunset"]
    assert first["time"].endswith("Z")


def test_the_hourly_forecast_is_a_day_of_hours(client):
    rows = client.get(
        "/api/v1/almanac/forecast", params={"site_id": SITE, "horizon": "hourly"}
    ).json()
    assert len(rows) == 24
    assert [row["time"][11:13] for row in rows] == [f"{h:02d}" for h in range(24)]


def test_an_unknown_horizon_is_refused_by_the_contract_s_own_pattern(client):
    response = client.get(
        "/api/v1/almanac/forecast", params={"site_id": SITE, "horizon": "yearly"}
    )
    assert response.status_code == 422


# ------------------------------------------------------------------- history


@pytest.mark.parametrize(("window", "points"), [("1d", 1), ("7d", 7), ("30d", 30)])
def test_every_window_returns_parallel_columns(client, window, points):
    """uPlot reads these as columns; a short one silently misaligns the chart."""
    series = client.get(
        "/api/v1/almanac/history", params={"window": window, "site_id": SITE}
    ).json()
    assert len(series["times"]) == points
    assert len(series["values"]) == points
    assert len(series["min"]) == len(series["max"]) == points
    assert series["times"] == sorted(series["times"])


def test_history_names_the_rollup_it_came_from(client):
    """So a reviewer can see it is not scanning the raw hypertable."""
    series = client.get(
        "/api/v1/almanac/history", params={"window": "30d", "metric": "et0_mm"}
    ).json()
    assert series["source"] == "weather_daily"
    assert series["unit"] == "mm"


def test_a_metric_no_deployment_can_supply_yet_comes_back_empty_not_invented(client):
    """Soil moisture has no hardware behind it and no readings.

    An empty series with the right shape is the honest answer. A plausible
    curve would be a fabricated measurement of a pot nobody has instrumented.
    """
    series = client.get(
        "/api/v1/almanac/history",
        params={"window": "7d", "metric": "soil_moisture_pct"},
    ).json()
    assert len(series["times"]) == 7
    assert all(value is None for value in series["values"])
    assert series["source"] == "reading_daily"


# ------------------------------------------------------------- water balance


def test_the_balance_publishes_its_confidence_and_the_reasons_for_it(client):
    """the design makes this endpoint the only thing deciding an outdoor watering.

    A bare number would be a degraded answer wearing a clean one's clothes.
    """
    body = balance(client, LEMON_ON_TERRACE)
    assert body["confidence"] in CONFIDENCES
    assert isinstance(body["degraded"], bool)
    assert isinstance(body["degradations"], list)
    for reason in body["degradations"]:
        assert set(reason) == {"code", "detail", "caps_at"}


def test_a_modelled_deficit_never_claims_high_confidence(client):
    """Nothing measures the soil, so nothing here is an observation."""
    for specimen_id in (LEMON_ON_TERRACE, LEMON_ON_PORCH, LAVENDER_HEDGE):
        assert balance(client, specimen_id)["confidence"] != "high"


def test_the_coefficient_arrives_with_its_provenance(client):
    """a category default must not read like a measurement."""
    body = balance(client, LEMON_ON_TERRACE)
    assert body["k_c"] == 0.9
    assert body["k_c_confidence"] in CONFIDENCES
    assert body[
        "k_c_source"
    ], "The no-invented-plant-facts rule — no care value travels uncited"
    assert body["k_c_is_category_default"] is False


def test_every_day_says_how_its_et0_was_arrived_at(client):
    """a fallback day is a different quality of input, and is labelled."""
    body = balance(client, LEMON_ON_TERRACE)
    assert body["days"]
    for day in body["days"]:
        assert day["et0_method"] in {"ingested", "hargreaves", "unavailable"}
        assert "reference_et0_mm" in day
        assert day["status"] in {"due", "satisfied", "ok"}


def test_rain_never_reaches_a_covered_porch(client):
    """``f_cover = 0``. The most commonly got-wrong term in the model."""
    covered = balance(client, LEMON_ON_PORCH)
    assert covered["cover_factor"] == 0.0
    assert all(day["precip_mm"] == 0 for day in covered["days"])
    assert any(
        day["gross_precip_mm"] > 0 for day in covered["days"]
    ), "what fell is still reported — it simply did not land in the pot"


def test_an_open_air_plant_does_collect_rain(client):
    open_air = balance(client, LEMON_ON_TERRACE)
    assert open_air["cover_factor"] == 1.0
    assert any(day["precip_mm"] > 0 for day in open_air["days"])


def test_rain_that_settles_a_watering_shows_as_satisfied_somewhere(under_storm):
    """The plan is explicit: the task must not simply vanish.

    Asserted under the storm rather than the baseline, for two reasons that
    both landed.

    The baseline is the *control* recording — thirty days of ordinary weather,
    so that a deployment which selects nothing sees nothing dramatic. It closes
    on a 6 mm shower, and 6 mm no longer settles a 45 L pot, because the other
    change was the weather engine fixing `BALANCE_DAYS`: the endpoint used to replay
    only the last fortnight from a zero deficit, so the lemon arrived at that
    shower artificially dry-but-shallow and the shower crossed it back. The
    deficit is now what the whole recording did, and a light shower on a real
    deficit is honestly not a settled watering.

    So the property moves to the weather that actually demonstrates it. The
    storm's downpour is 38 mm.
    """
    days = balance(under_storm, LEMON_ON_TERRACE)["days"]
    assert any(day["status"] == "satisfied" for day in days)


def test_a_shower_too_small_to_settle_a_watering_does_not_claim_to(client):
    """The other half of the test above, on the control recording.

    The storm proves ``satisfied`` is reachable. This proves it is not reachable
    on weather that does not deserve it: the baseline closes on a 6 mm shower,
    which leaves the 45 L lemon at 29.76 mm against a 19.65 mm threshold — still
    owed.

    It is here because the assertion above used to hold on the baseline, for the
    wrong reason. The endpoint replayed only ``BALANCE_DAYS`` from a zero
    deficit, so the lemon arrived at that shower artificially shallow and 6 mm
    crossed it back. Moving the positive case to the storm records that the
    baseline no longer settles anything; nothing yet records *why that is
    right*, so a regression of the replay window would put the old behaviour
    back and only this test would notice.

    And it is the direction that costs a plant. A downpour mistaken for a
    drizzle produces one unnecessary watering; a drizzle credited as a downpour
    leaves the pot dry with the app reporting it settled, which
    nothing else would catch — the same failure ``store.py`` replaces whole
    windows of ``weather_obs`` to avoid.
    """
    payload = balance(client, LEMON_ON_TERRACE)
    closing = payload["days"][-1]

    assert closing["precip_mm"] > 0, "the control recording does close on rain"
    assert closing["deficit_mm"] > payload["threshold_mm"], "6 mm is not enough"
    assert payload["status"] == "due" and payload["satisfied_by"] is None
    assert not any(day["status"] == "satisfied" for day in payload["days"])


def test_an_indoor_specimen_is_told_this_engine_does_not_apply(client):
    """Indoor plants use interval rules adjusted by season and humidity.

    Serving a deficit for a pot in a study, with no warning, would be inventing
    a fact about a place where no rain falls.
    """
    body = balance(client, MONSTERA_INDOORS)
    assert body["applies"] is False
    assert "interval rule" in body["note"]


def test_an_outdoor_specimen_is_told_that_it_does(client):
    assert balance(client, LEMON_ON_TERRACE)["applies"] is True


def test_the_container_dries_before_the_open_ground(client):
    """A 45 L pot has a fraction of a border's buffer."""
    pot = balance(client, LEMON_ON_TERRACE)
    ground = balance(client, LAVENDER_HEDGE)
    assert pot["capacity_mm"] < ground["capacity_mm"]
    assert pot["threshold_mm"] < ground["threshold_mm"]


def test_an_unknown_specimen_is_a_404_not_an_empty_balance(client):
    response = client.get(
        "/api/v1/almanac/water-balance/01890040-0000-7000-8000-00000000ffff"
    )
    assert response.status_code == 404


# --------------------------------------------------------------------- frost


def test_frost_alerts_are_computed_not_replayed(client):
    """The earlier mock read the scenario's own ``expect`` block, which proves nothing.

    These come out of the engine, so a broken threshold breaks this test.
    """
    alerts = client.get("/api/v1/almanac/frost").json()["alerts"]
    assert alerts
    for alert in alerts:
        assert alert["specimen"]["is_outdoor"]
        assert alert["forecast_low_c"] <= alert["threshold_c"]
        assert alert["action"] in {"bring_indoors", "cover", "monitor"}
        assert alert["state"] == "open"
        assert alert["confidence"] in CONFIDENCES


def test_an_alert_id_is_stable_across_calls(client):
    """A dismissed alert must not come back as a new one after a restart."""
    first = {a["id"] for a in client.get("/api/v1/almanac/frost").json()["alerts"]}
    second = {a["id"] for a in client.get("/api/v1/almanac/frost").json()["alerts"]}
    assert first == second
    assert all(len(alert_id) == 36 for alert_id in first)


def test_a_hardy_plant_is_never_in_the_list(client):
    """A false alert on a lavender teaches people to ignore the real one."""
    alerts = client.get("/api/v1/almanac/frost").json()["alerts"]
    assert LAVENDER_HEDGE not in {alert["specimen"]["id"] for alert in alerts}


def test_the_nws_advisory_reaches_the_alert(client):
    alerts = client.get("/api/v1/almanac/frost").json()["alerts"]
    assert any(alert["advisory"] for alert in alerts)


def test_no_plant_is_dropped_from_the_frost_guard_in_silence(client):
    """A plant that cannot be judged is named, on the endpoint itself.

    the design gave the response an envelope for exactly this. An unanswerable
    question must not reach the reader looking like a reassuring answer.
    """
    report = client.get("/api/v1/almanac/frost").json()
    assert set(report) == {"alerts", "unassessable"}
    for row in report["unassessable"]:
        assert row["specimen_id"] and row["reason"]

    from almanac import service

    assert report["unassessable"] == service.unassessable_for_frost()
