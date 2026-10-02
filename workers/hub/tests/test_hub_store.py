"""The statements the hub issues — the hub.

Every statement is built by a pure function, so what is worth asserting is
*which* ones a write issues and with what arguments. A real Postgres would
make that harder to see, not easier.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from workers.hub import store
from workers.hub.sources.base import Reading

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def reading(metric: str = "temperature_c", value: float = 21.0, **kwargs) -> Reading:
    return Reading(
        time=kwargs.pop("time", NOW),
        source_id=kwargs.pop("source_id", "source-1"),
        metric=metric,
        value=value,
        location_id=kwargs.pop("location_id", "location-1"),
        specimen_id=kwargs.pop("specimen_id", None),
    )


def test_readings_are_written_in_one_statement_with_the_contracts_columns():
    sql, params = store.insert_readings_sql([reading(), reading("humidity_pct", 44.0)])
    assert sql.startswith(
        "INSERT INTO reading (time, source_id, metric, value, location_id, "
        "specimen_id)"
    )
    assert sql.count("(") == 3  # the column list and two value tuples
    assert len(params) == 12
    assert params[2] == "temperature_c"
    assert params[9] == 44.0


def test_a_reading_row_matches_the_hypertables_columns():
    """``reading`` has no id and no created_at; a parser that invents one
    should not typecheck, and a writer that sends one should not pass."""
    assert set(reading().to_row()) == {
        "time",
        "source_id",
        "metric",
        "value",
        "location_id",
        "specimen_id",
    }


def test_writing_readings_stamps_every_source_that_produced_one(run, connection):
    run(
        store.write_readings(
            connection,
            [
                reading(source_id="a"),
                reading("humidity_pct", 44.0, source_id="a"),
                reading(source_id="b"),
            ],
        )
    )
    touches = connection.matching("UPDATE sensor_source")
    assert {args[0] for _, args in touches} == {"a", "b"}


def test_a_poll_that_produced_nothing_stamps_nothing(run, connection):
    """``last_seen_at`` is what "no recent reading" is measured against.

    Stamping it on a poll that returned nothing would make a dead sensor look
    alive, which is the exact failure the design asks this parts of the project to
    prevent.
    """
    assert run(store.write_readings(connection, [])) == 0
    assert connection.executed == []


def test_a_source_is_stamped_with_its_newest_reading_not_its_last(run, connection):
    early, late = NOW.replace(minute=0), NOW.replace(minute=5)
    run(
        store.write_readings(
            connection,
            [reading(time=late), reading("humidity_pct", 44.0, time=early)],
        )
    )
    ((_, args),) = connection.matching("UPDATE sensor_source")
    assert args[1] == late


def test_an_integrations_id_is_derived_so_two_workers_cannot_race_two_rows():
    """``integration`` is keyed only on id and has no unique (kind, name).

    Without this, "record that Home Assistant answered" is a select-then-insert
    that two workers starting together turn into two rows for one hub. The
    derivation is a workaround for a missing index, and it is on the list for the maintainers.
    """
    first = store.integration_id_for("home_assistant", "Home Assistant")
    assert first == store.integration_id_for("home_assistant", "Home Assistant")
    assert first != store.integration_id_for("mqtt", "Home Assistant")


def test_success_clears_the_error_and_failure_leaves_the_last_success_alone():
    """A stale error beside a fresh success is a screen that cries wolf; the
    history of failures belongs in ``job_run``, which keeps one row per run."""
    ok_sql, _ = store.record_integration_ok_sql("home_assistant", "HA", NOW)
    assert "last_error = NULL" in ok_sql

    error_sql, _ = store.record_integration_error_sql("home_assistant", "HA", "boom")
    assert "last_ok_at" not in error_sql


def test_recording_health_creates_the_row_if_this_deployment_has_none(run, connection):
    run(store.record_ok(connection, "home_assistant", "Home Assistant", NOW))
    statements = connection.statements()
    assert statements[0].startswith("INSERT INTO integration")
    assert "ON CONFLICT (id) DO NOTHING" in statements[0]
    assert statements[1].startswith("UPDATE integration")


def test_the_job_run_row_carries_the_report_as_json(run, connection):
    run(
        store.record_job_run(
            connection,
            "poll_home_assistant",
            started_at=NOW,
            finished_at=NOW,
            ok=False,
            detail={"skipped": [{"entity_id": "sensor.x", "reason": "stale_entity"}]},
        )
    )
    ((_, args),) = connection.matching("INSERT INTO job_run")
    assert args[1] == "poll_home_assistant"
    assert args[4] is False
    assert "stale_entity" in args[5]


def test_only_the_contracts_own_aggregates_can_be_refreshed():
    """The view name is interpolated because it is an identifier, not a value."""
    start, end = date(2026, 6, 15), date(2026, 6, 16)
    sql, params = store.refresh_aggregate_sql("reading_hourly", start, end)
    assert sql.startswith("CALL refresh_continuous_aggregate('reading_hourly'")
    assert params == [start, end]

    with pytest.raises(ValueError, match="not a continuous aggregate"):
        store.refresh_aggregate_sql("reading; DROP TABLE reading", start, end)

    with pytest.raises(ValueError):
        # The weather engine's view, over a table this worker does not write.
        store.refresh_aggregate_sql("weather_daily", start, end)


def test_the_office_never_reads_integration_config():
    """The schema's comment says secrets live in the secret store, which is a
    convention rather than a constraint. Not selecting the column means a
    deployment that ignored the convention cannot leak through a health
    screen."""
    sql, _ = store.integrations_sql()
    assert "config" not in sql


def test_disabled_sources_are_not_filtered_out_in_sql():
    """The Office has to show a source somebody turned off as disabled rather
    than as missing."""
    sql, params = store.sensor_sources_sql()
    assert "enabled" in sql.split("FROM")[0]
    assert "WHERE" not in sql
    assert params == []

    sql, params = store.sensor_sources_sql(adapter="home_assistant")
    assert "WHERE adapter = $1" in sql
    assert params == ["home_assistant"]
