"""The jobs — the hub.

The releases's exit criterion is **indoor and outdoor readings stored every 5–15
minutes**. The weather engine landed the outdoor half; these are the tests for the
indoor one. Under the design nothing else fills in behind it, so the tests here
are as much about the failure paths — a hub that is off, a mapping that is
wrong, a run that produced nothing — as about the happy one. A silent adapter
is this parts of the project's failure mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from workers.hub import tasks
from workers.hub.mapping import SensorSource
from workers.hub.mocks.fetcher import RecordedFetcher, UnavailableFetcher
from workers.hub.sources.home_assistant import HomeAssistantSource

TOKEN = "eyJhbGciOiJIUzI1NiJ9.aVeryLongLivedAccessToken.signaturegoeshere"


@pytest.fixture
def live_clock_source(settings):
    """A hub whose entities are fresh against the *real* clock.

    The jobs stamp their own ``datetime.now(UTC)`` — deliberately, because a
    job that takes its timestamp from its caller cannot be trusted to have run
    when it says it did. So the mock hub here moves with the wall clock too,
    or every entity would read as three months stale and the poll would
    correctly refuse all of them. ``test_hub_adapter.py`` freezes both ends
    together instead, which is where the freshness rules are actually tested.
    """
    return HomeAssistantSource(RecordedFetcher(settings), settings)


@pytest.fixture
def ctx(settings, live_clock_source, sensor_sources):
    return {
        "settings": settings,
        "source": live_clock_source,
        "sources": sensor_sources,
    }


# ------------------------------------------------------- the exit criterion


def test_the_poll_schedule_meets_the_sprints_five_to_fifteen_minutes():
    """Read off the cron rather than off the docstring, so a schedule that
    drifts out of the band fails here rather than in a demo."""
    jobs = tasks.WorkerSettings.cron_jobs
    assert jobs, "arq is a declared dependency; the schedule must be built"
    poll = next(job for job in jobs if job.coroutine is tasks.poll_home_assistant)
    minutes = sorted(poll.minute)
    gaps = {b - a for a, b in pairwise(minutes)} | {60 - minutes[-1] + minutes[0]}
    assert gaps == {5}
    assert poll.run_at_startup is True


def test_the_health_check_runs_as_often_as_the_poll_and_not_with_it():
    """The Office should learn the hub is down from a cheap GET /api/ rather
    than from a poll that had to time out first."""
    jobs = tasks.WorkerSettings.cron_jobs
    poll = next(job for job in jobs if job.coroutine is tasks.poll_home_assistant)
    check = next(job for job in jobs if job.coroutine is tasks.check_home_assistant)
    assert len(check.minute) == len(poll.minute)
    assert not set(check.minute) & set(poll.minute)


def test_a_poll_stores_a_reading_for_every_mapped_entity(run, ctx):
    report = run(tasks.poll_home_assistant(ctx))
    assert report["ok"] is True
    assert report["readings"] == 6
    assert sorted(report["metrics"]) == ["humidity_pct", "temperature_c"]
    assert report["skipped"] == []


def test_the_rows_reach_the_hypertable_and_the_rollup_is_refreshed(
    run, ctx, connection
):
    """The scheduled aggregate policy runs hourly, which is right for steady
    state and too slow for a screen somebody is looking at now."""
    report = run(tasks.poll_home_assistant({**ctx, "connection": connection}))
    assert report["stored"] == 6

    inserts = connection.matching("INSERT INTO reading")
    assert len(inserts) == 1
    refreshes = [sql for sql in connection.statements() if "refresh_continuous" in sql]
    assert any("reading_hourly" in sql for sql in refreshes)
    assert any("reading_daily" in sql for sql in refreshes)


def test_a_successful_run_stamps_last_ok_at_and_records_the_run(run, ctx, connection):
    run(tasks.poll_home_assistant({**ctx, "connection": connection}))
    assert connection.matching("last_ok_at = $2")
    ((_, args),) = connection.matching("INSERT INTO job_run")
    assert args[1] == "poll_home_assistant"
    assert args[4] is True


# ------------------------------------------------------------- the silence


def test_a_hub_that_is_off_lands_on_last_error_rather_than_in_a_log(
    run, settings, sensor_sources, connection
):
    """if HA is down, indoor readings stop, and the hub must record that
    so the Ministry Office shows it without anyone reading logs."""
    down = HomeAssistantSource(UnavailableFetcher(), settings)
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": down,
                "sources": sensor_sources,
                "connection": connection,
            }
        )
    )
    assert report["ok"] is False
    assert "unreachable" in report["error"]
    ((_, args),) = connection.matching("SET last_error")
    assert "unreachable" in args[1]
    # The last success is left alone: it is still true.
    assert connection.matching("last_ok_at = $2") == []


def test_a_working_hub_with_a_broken_mapping_is_not_counted_as_success(
    run, settings, connection
):
    """The case that would otherwise pass silently: the job ran, no exception
    was raised, and the hypertable stayed empty."""
    typo = SensorSource(
        id="typo",
        name="Study",
        external_ids={"temperature_c": "sensor.sutdy_temperature"},
        location_id="location-1",
    )
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": HomeAssistantSource(RecordedFetcher(settings), settings),
                "sources": [typo],
                "connection": connection,
            }
        )
    )
    assert report["ok"] is False
    assert "no mapped entity produced a reading" in report["error"]
    assert "entity_not_found" in report["error"]


def test_a_partly_working_mapping_is_named_while_the_rest_still_lands(
    run, settings, sensor_sources, connection
):
    """A partly-working mapping is the one people never get round to fixing."""
    typo = SensorSource(
        id="typo",
        name="Hall",
        external_ids={"temperature_c": "sensor.hall_temperature"},
        location_id="location-9",
    )
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": HomeAssistantSource(RecordedFetcher(settings), settings),
                "sources": [*sensor_sources, typo],
                "connection": connection,
            }
        )
    )
    assert report["readings"] == 6
    assert report["ok"] is False
    assert "some entities produced no reading" in report["error"]
    assert report["stored"] == 6  # the good ones were not held hostage


def test_a_misconfigured_row_reaches_the_office_even_when_the_poll_works(
    run, settings, sensor_sources
):
    invented = SensorSource(
        id="invented",
        name="Mandrake pot",
        external_ids={"soil_moisture_pct": "sensor.bathroom_humidity"},
        location_id="location-1",
    )
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": HomeAssistantSource(RecordedFetcher(settings), settings),
                "sources": [*sensor_sources, invented],
            }
        )
    )
    assert any("needs a specimen_id" in problem for problem in report["problems"])


def test_nothing_credential_shaped_reaches_last_error(
    run, settings, sensor_sources, connection
):
    """``integration.last_error`` is rendered in the Ministry Office."""
    from pydantic import SecretStr

    leaky = HomeAssistantSource(
        UnavailableFetcher(f"connection refused; Authorization: Bearer {TOKEN}"),
        settings,
    )
    settings = settings.model_copy(update={"ha_token": SecretStr(TOKEN)})
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": leaky,
                "sources": sensor_sources,
                "connection": connection,
            }
        )
    )
    assert TOKEN not in report["error"]
    assert TOKEN not in str(connection.executed)


def test_a_deployment_with_every_source_disabled_does_not_look_healthy(
    run, settings, sensor_sources, connection
):
    """Nothing was asked of Home Assistant, so nothing was learned about it.

    Stamping ``last_ok_at`` here would make a deployment that reads nothing
    report as working forever.
    """
    disabled = [
        SensorSource(
            **{**row.to_dict(), "enabled": False, "external_ids": row.external_ids}
        )
        for row in sensor_sources
    ]
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "sources": disabled,
                "connection": connection,
            }
        )
    )
    assert report["polled"] == 0
    assert report["note"] == "no source was due"
    assert connection.executed == []


# ------------------------------------------------------------ the cadences


def hourly_source(last_seen_at) -> SensorSource:
    return SensorSource(
        id="slow",
        name="Study",
        external_ids={"temperature_c": "sensor.study_temperature"},
        location_id="location-1",
        poll_seconds=3600,
        last_seen_at=last_seen_at,
    )


def test_a_source_that_is_not_due_yet_is_not_polled(run, settings):
    """The cron sets the finest cadence; each row decides whether it wants
    reading this time round. A thermostat is not a soil probe."""
    recent = hourly_source(datetime.now(UTC) - timedelta(minutes=5))
    report = run(tasks.poll_home_assistant({"settings": settings, "sources": [recent]}))
    assert report["polled"] == 0


def test_naming_a_source_polls_it_whether_or_not_it_is_due(
    run, settings, live_clock_source
):
    """What the Ministry Office's "test this sensor" button needs."""
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": live_clock_source,
                "sources": [hourly_source(datetime.now(UTC))],
            },
            source_id="slow",
        )
    )
    assert report["polled"] == 1
    assert report["readings"] == 1


def test_naming_a_source_that_does_not_exist_is_an_error_not_a_no_op(run, ctx):
    report = run(tasks.poll_home_assistant(ctx, source_id="nope"))
    assert report["ok"] is False
    assert "nope" in report["error"]


# --------------------------------------------------------------- the health


def test_the_health_check_is_answerable_before_any_source_is_configured(
    run, settings, source
):
    """The screen someone looks at *while* setting it up. A health check that
    only runs when there is something to poll is absent exactly when wanted."""
    report = run(tasks.check_home_assistant({"settings": settings, "source": source}))
    assert report["ok"] is True
    assert report["status"] == "ok"
    assert report["is_mock"] is True


def test_a_failed_check_records_the_reason(run, settings, connection):
    down = HomeAssistantSource(UnavailableFetcher(), settings)
    report = run(
        tasks.check_home_assistant(
            {"settings": settings, "source": down, "connection": connection}
        )
    )
    assert report["status"] == "down"
    assert connection.matching("SET last_error")


def test_the_office_report_separates_a_new_install_from_a_broken_one(run, ctx):
    report = run(tasks.hub_health(ctx))
    assert report["ok"] is True
    assert report["problems"] == []
    assert sorted(report["awaiting"]) == ["Greenhouse Window", "Kitchen Sill", "Study"]
    assert {row["status"] for row in report["integrations"]} == {"unconfigured"}


def test_the_office_report_reads_the_database_when_there_is_one(run, ctx, connection):
    connection.rows["FROM integration"] = [
        {
            "id": "i-1",
            "kind": "home_assistant",
            "name": "Home Assistant",
            "enabled": True,
            "last_ok_at": None,
            "last_error": "refused",
        }
    ]
    report = run(tasks.hub_health({**ctx, "connection": connection}))
    assert report["ok"] is False
    assert report["problems"] == ["Home Assistant"]
    assert report["integrations"][0]["status"] == "down"


def test_the_jobs_read_sources_from_the_database_when_one_is_attached(
    run, settings, connection
):
    connection.rows["FROM sensor_source"] = [
        {
            "id": "s-1",
            "name": "Study",
            "adapter": "home_assistant",
            "external_ids": {"temperature_c": "sensor.study_temperature"},
            "location_id": "location-1",
            "specimen_id": None,
            "poll_seconds": 300,
            "enabled": True,
            "last_seen_at": None,
        }
    ]
    report = run(
        tasks.poll_home_assistant(
            {
                "settings": settings,
                "source": HomeAssistantSource(RecordedFetcher(settings), settings),
                "connection": connection,
            }
        )
    )
    assert report["sources"] == 1
    assert report["readings"] == 1


# ------------------------------------------------------------- publish-back


def test_the_publish_job_builds_every_contracted_message(run, settings):
    from workers.hub.mqtt import MemoryPublisher

    publisher = MemoryPublisher()
    report = run(
        tasks.publish_to_mqtt(
            {
                "settings": settings,
                "publisher": publisher,
                "rounds": {"due": 3, "overdue": 1, "tasks": [{"id": "t-1"}]},
                "frost": {"active": True, "low_c": -2.0, "next": "2026-10-03"},
                "specimens": [
                    {
                        "specimen_id": "01890040-0000-7000-8000-000000000001",
                        "water_due": True,
                        "deficit_mm": 14.2,
                    }
                ],
            }
        )
    )
    assert report["ok"] is True
    assert report["published"] == report["retained"]
    assert "herbology/status" in report["topics"]
    assert "herbology/rounds/due" in report["topics"]
    assert publisher.payload_for("herbology/frost/state") == "ON"
    assert (
        publisher.payload_for(
            "herbology/specimen/01890040-0000-7000-8000-000000000001/deficit_mm"
        )
        == "14.2"
    )


def test_the_publish_job_reports_what_it_would_send_with_no_transport(run, settings):
    """The live client is a dependency the hub does not own, so with no
    publisher the job still builds and guards every message and says so."""
    report = run(tasks.publish_to_mqtt({"settings": settings}))
    assert report["transport"] == "MemoryPublisher"
    assert report["published"] > 0


# -------------------------------------------------------------- the exports


def test_supported_metrics_is_still_importable_from_tasks():
    """the design names ``SUPPORTED_METRICS`` in ``workers/hub/tasks.py`` by
    path. Moving it is fine; making that sentence false is not."""
    assert "soil_moisture_pct" in tasks.SUPPORTED_METRICS
    assert tasks.MQTT_PREFIX == "herbology"
    assert tasks.DISCOVERY_PREFIX == "homeassistant"
    assert tasks.state_topic("frost", "state") == "herbology/frost/state"
    assert (
        tasks.discovery_topic("sensor", "x")
        == "homeassistant/sensor/herbology/x/config"
    )


def test_every_job_is_registered_with_arq():
    """A job Arq does not know about is a job that never runs.

    Written as an exact set rather than a subset on purpose: adding a job and
    forgetting to register it is silent, and so is registering one twice.
    """
    registered = set(tasks.WorkerSettings.functions)
    assert registered == {
        tasks.poll_home_assistant,
        tasks.check_home_assistant,
        tasks.hub_health,
        tasks.publish_to_mqtt,
        tasks.notify_rounds,
        tasks.notify_frost,
        tasks.notify_integration_health,
    }
