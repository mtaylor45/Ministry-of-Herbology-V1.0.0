"""Which entity is which plant — the hub."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from workers.hub.mapping import SensorSource, pollable, validation_errors

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def source(**kwargs) -> SensorSource:
    defaults = {
        "id": "source-1",
        "name": "Study",
        "external_ids": {
            "temperature_c": "sensor.study_temperature",
            "humidity_pct": "sensor.study_humidity",
        },
        "location_id": "location-1",
    }
    return SensorSource(**{**defaults, **kwargs})


def test_one_row_carries_a_thermostats_two_entities():
    """Which is what makes "the Study" a series rather than two loose ones."""
    assert source().bindings() == (
        ("humidity_pct", "sensor.study_humidity"),
        ("temperature_c", "sensor.study_temperature"),
    )


def test_bindings_are_sorted_so_a_report_does_not_depend_on_json_key_order():
    one = source(external_ids={"temperature_c": "a", "humidity_pct": "b"})
    other = source(external_ids={"humidity_pct": "b", "temperature_c": "a"})
    assert one.bindings() == other.bindings()


def test_a_metric_the_contract_does_not_store_is_not_polled():
    row = source(external_ids={"co2_ppm": "sensor.study_co2"})
    assert row.bindings() == ()


def test_from_row_reads_a_database_row_and_a_fixture_alike():
    """asyncpg hands back a Record, the fixture loader a dict of JSON."""
    from_json = SensorSource.from_row(
        {
            "id": "source-1",
            "name": "Study",
            "adapter": "home_assistant",
            "external_ids": '{"temperature_c": "sensor.study_temperature"}',
            "location_id": "location-1",
            "specimen_id": None,
            "poll_seconds": 600,
            "enabled": True,
            "last_seen_at": "2026-06-15T11:50:00+00:00",
        }
    )
    assert from_json.external_ids == {"temperature_c": "sensor.study_temperature"}
    assert from_json.poll_seconds == 600
    assert from_json.last_seen_at == datetime(2026, 6, 15, 11, 50, tzinfo=UTC)


def test_a_thermostat_is_not_a_soil_probe():
    """The brief's rule, and the whole of why poll_seconds is per row.

    The cron sets the finest cadence available; each row decides whether it
    wants to be read this time round.
    """
    fast = source(poll_seconds=300, last_seen_at=NOW - timedelta(minutes=6))
    slow = source(poll_seconds=3600, last_seen_at=NOW - timedelta(minutes=6))
    assert fast.is_due(NOW)
    assert not slow.is_due(NOW)


def test_a_source_that_has_never_been_polled_is_due_immediately():
    """A thermostat added at 10:02 should appear at 10:05, not at 11:00."""
    assert source(last_seen_at=None).is_due(NOW)


def test_a_disabled_source_is_never_due():
    assert not source(enabled=False, last_seen_at=None).is_due(NOW)


def test_the_job_may_override_the_marker_with_its_own_attempt():
    """A failed attempt is still an attempt, or a dead hub is hammered every
    five minutes for as long as it stays dead."""
    row = source(poll_seconds=900, last_seen_at=None)
    assert not row.is_due(NOW, last_polled_at=NOW - timedelta(minutes=2))


def test_a_soil_metric_with_no_specimen_behind_it_is_refused():
    """nothing may ship that pretends a sensor exists.

    A soil_moisture_pct series bound to a room rather than to a pot is not a
    mislabelled row — it is a probe the household does not have, feeding an
    override the weather engine's water balance obeys.
    """
    problems = validation_errors(
        source(external_ids={"soil_moisture_pct": "sensor.pot"}, specimen_id=None)
    )
    assert any("needs a specimen_id" in problem for problem in problems)


def test_a_soil_metric_bound_to_a_specimen_is_accepted():
    assert (
        validation_errors(
            source(
                external_ids={"soil_moisture_pct": "sensor.pot"},
                specimen_id="specimen-1",
            )
        )
        == []
    )


def test_an_entity_that_carries_no_reading_is_named_rather_than_polled_quietly():
    problems = validation_errors(source(external_ids={"temperature_c": "light.lamp"}))
    assert any("light entity" in problem for problem in problems)


def test_a_row_with_nothing_mapped_is_a_problem_not_a_no_op():
    problems = validation_errors(source(external_ids={}))
    assert any("nothing to read" in problem for problem in problems)


def test_validation_returns_problems_rather_than_raising():
    """One bad row must not stop the other eleven from being polled."""
    problems = validation_errors(
        source(external_ids={"temperature_c": "not-an-entity"}, poll_seconds=0)
    )
    assert len(problems) == 2


def test_only_home_assistant_rows_are_polled_and_the_rest_are_not_errors():
    """the design keeps the full adapter enum as a label for provenance.

    A row marked ``nest`` says where a reading ultimately came from. It is not
    a request for a Nest integration, and there is not going to be one.
    """
    rows = [
        source(id="a", adapter="home_assistant"),
        source(id="b", adapter="manual"),
        source(id="c", adapter="nest"),
        source(id="d", adapter="home_assistant", enabled=False),
    ]
    assert [row.id for row in pollable(rows)] == ["a"]
