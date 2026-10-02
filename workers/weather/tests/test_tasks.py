"""The Arq jobs, run offline, reporting what they did.

Every job returns a dict rather than writing and staying quiet. That is what
makes this file possible with no database, and it is also the point: a job
whose only evidence is a row in Postgres is a job nobody checks.
"""

from datetime import date

import pytest

from workers.weather import tasks
from workers.weather.ingest import WeatherIngest
from workers.weather.mocks.fetcher import UnavailableFetcher


@pytest.fixture
def ctx(fetcher, settings, site):
    return {
        "ingest": WeatherIngest(fetcher, settings),
        "settings": settings,
        "site": site,
    }


def test_the_forecast_job_reports_what_it_pulled(ctx, run):
    report = run(tasks.ingest_forecast(ctx))
    assert report["forecasts"] >= 10
    assert report["sources"] == {"forecast": "open_meteo"}
    assert report["errors"] == []


def test_the_observation_job_reports_what_it_stored(ctx, run):
    report = run(tasks.ingest_observations(ctx))
    assert report["observations"] > 0
    assert report["sources"] == {"observations": "open_meteo"}


def test_a_job_persists_through_the_store_when_a_connection_is_present(ctx, run):
    """And refreshes the rollup window it just touched, rather than waiting an hour."""

    class FakeConnection:
        def __init__(self):
            self.statements = []

        async def execute(self, sql, *args):
            self.statements.append(sql)

        async def fetch(self, sql, *args):
            return []

    connection = FakeConnection()
    run(tasks.ingest_observations(ctx | {"connection": connection}))
    assert any(s.startswith("DELETE FROM weather_obs") for s in connection.statements)
    assert any(s.startswith("INSERT INTO weather_obs") for s in connection.statements)
    assert any("refresh_continuous_aggregate" in s for s in connection.statements)


def test_a_job_with_no_connection_still_does_the_work(ctx, run):
    """Mock mode is a shipping path, not a stub."""
    report = run(tasks.ingest_forecast(ctx))
    assert report["forecasts"] > 0
    assert report["is_mock"] is True


def test_the_advisory_job_separates_frost_events_from_the_rest(ctx, run):
    report = run(tasks.ingest_advisories(ctx))
    assert report["sources"] == {"advisories": "nws"}
    assert report["frost_advisories"] == []


def test_the_history_job_names_the_window_it_asked_for(ctx, run):
    report = run(tasks.ingest_history(ctx, days=10))
    start, end = report["window"]
    assert date.fromisoformat(end) > date.fromisoformat(start)


def test_every_ingest_job_survives_both_sources_being_down(settings, site, run):
    """A dead afternoon must not take the worker down with it."""
    ctx = {
        "ingest": WeatherIngest(UnavailableFetcher(), settings),
        "settings": settings,
        "site": site,
    }
    for job in (
        tasks.ingest_forecast,
        tasks.ingest_observations,
        tasks.ingest_advisories,
    ):
        report = run(job(ctx))
        assert report["errors"], f"{job.__name__} swallowed a failure"


def test_the_water_balance_job_skips_indoor_specimens(ctx, run):
    """Indoor plants use interval rules, not this engine."""
    from workers.weather import world

    report = run(tasks.evaluate_water_balance(ctx))
    outdoor = [
        c for c in world.specimen_contexts(ctx["settings"]).values() if c.is_outdoor
    ]
    assert report["evaluated"] == len(outdoor)


def test_the_water_balance_job_counts_the_answers_resting_on_degraded_inputs(ctx, run):
    """The number that says whether this engine is still worth trusting."""
    report = run(tasks.evaluate_water_balance(ctx))
    assert "degraded" in report
    assert report["degraded"] == sum(
        1 for row in report["specimens"] if row["degradations"]
    )
    for row in report["specimens"]:
        assert row["confidence"] in {"high", "medium", "low", "unknown"}


def test_every_water_balance_row_reaches_a_definite_answer(ctx, run):
    """with zero sensors configured, every outdoor plant still decides."""
    report = run(tasks.evaluate_water_balance(ctx))
    assert report["evaluated"] >= 5
    for row in report["specimens"]:
        assert isinstance(row["is_due"], bool)
        assert row["status"] in {"due", "satisfied", "ok"}


def test_the_balance_job_can_be_replayed_to_a_past_day(ctx, run):
    early = run(tasks.evaluate_water_balance(ctx, "2026-05-03"))
    late = run(tasks.evaluate_water_balance(ctx))
    assert early["due"] <= late["due"], "a shorter dry run cannot owe more water"


def test_the_frost_job_reports_alerts_and_the_plants_it_could_not_judge(ctx, run):
    report = run(tasks.evaluate_frost_guard(ctx))
    assert report["alerts"], "the frost scenario must produce alerts"
    assert isinstance(report["unassessable"], list)
    for alert in report["alerts"]:
        assert alert["forecast_low_c"] <= alert["threshold_c"]
        assert alert["action"] in {"bring_indoors", "cover", "monitor"}


def test_the_schedule_covers_the_sprint_s_exit_criterion():
    """an earlier release: readings stored every 5–15 minutes, forecast visible."""
    jobs = tasks.WorkerSettings.cron_jobs
    assert jobs, "arq is a declared dependency; the schedule should be built"
    by_name = {job.coroutine.__name__: job for job in jobs}
    observations = by_name["ingest_observations"]
    assert observations.minute == set(range(0, 60, 10))
    assert observations.run_at_startup, "an empty Almanac after a restart looks broken"
    assert "ingest_forecast" in by_name
    assert "evaluate_frost_guard" in by_name


def test_every_scheduled_job_is_also_a_registered_function():
    """A cron entry naming a function the worker cannot run fails at 4 a.m."""
    registered = {function.__name__ for function in tasks.WorkerSettings.functions}
    for job in tasks.WorkerSettings.cron_jobs:
        assert job.coroutine.__name__ in registered
