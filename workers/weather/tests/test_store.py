"""The statements, and the rollups they have to feed correctly.

Every builder is a pure function returning ``(sql, params)``, so which view a
window reads and whether a write can double-count are both checkable without
Postgres — which is the point, because "the 30-day history quietly scans the
hypertable" is invisible until there is a year of data to be slow about.
"""

from datetime import UTC, date, datetime

import pytest

from workers.weather.sources.base import Advisory, Forecast, Observation
from workers.weather.store import (
    active_advisories_sql,
    daily_weather_sql,
    delete_observations_sql,
    insert_observations_sql,
    latest_forecast_sql,
    reading_series_sql,
    refresh_aggregate_sql,
    upsert_advisory_sql,
    upsert_forecast_sql,
    upsert_water_balance_sql,
    water_balance_history_sql,
    write_observations,
)

SITE = "01890000-0000-7000-8000-000000000001"


class FakeConnection:
    """Records what it was asked to run. No database, no ordering surprises."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.rows: list[dict] = []

    async def execute(self, sql: str, *args):
        self.statements.append((sql, args))

    async def fetch(self, sql: str, *args):
        self.statements.append((sql, args))
        return self.rows


def observation(hour: int, **kwargs) -> Observation:
    return Observation(
        time=datetime(2026, 6, 1, hour, tzinfo=UTC),
        temperature_c=20.0,
        precip_mm=1.0,
        **kwargs,
    )


def test_history_reads_the_continuous_aggregate_not_the_raw_rows():
    """``reading`` is dropped after 400 days; the rollups carry the history."""
    sql, params = daily_weather_sql(SITE, date(2026, 5, 1), date(2026, 5, 31))
    assert "FROM weather_daily" in sql
    assert "weather_obs" not in sql
    assert params == [SITE, date(2026, 5, 1), date(2026, 5, 31)]


def test_indoor_and_sensor_history_reads_the_reading_rollups():
    daily, params = reading_series_sql(
        "soil_moisture_pct",
        specimen_id="spec",
        start=date(2026, 5, 1),
        end=date(2026, 5, 8),
    )
    assert "FROM reading_daily" in daily
    assert "specimen_id = $4" in daily
    assert params == ["soil_moisture_pct", date(2026, 5, 1), date(2026, 5, 8), "spec"]

    hourly, _ = reading_series_sql(
        "temperature_c",
        location_id="loc",
        start=date(2026, 5, 1),
        end=date(2026, 5, 2),
        daily=False,
    )
    assert "FROM reading_hourly" in hourly


def test_a_write_replaces_its_window_rather_than_adding_to_it(run):
    """``weather_daily`` sums precip across the bucket with no source column.

    Two sources surviving for one hour doubles the day's rain, which clears a
    deficit nothing cleared and leaves a plant unwatered. Re-ingesting the same
    hours therefore deletes first — ``weather_obs`` has no unique index in the
    frozen schema, so ``ON CONFLICT`` is not available.
    """
    connection = FakeConnection()
    rows = [observation(hour) for hour in (10, 11, 12)]
    written = run(write_observations(connection, SITE, rows))

    assert written == 3
    assert len(connection.statements) == 2
    delete_sql, delete_params = connection.statements[0]
    insert_sql, _ = connection.statements[1]
    assert delete_sql.startswith("DELETE FROM weather_obs")
    assert delete_params[1] == datetime(2026, 6, 1, 10, tzinfo=UTC)
    assert delete_params[2] == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert insert_sql.startswith("INSERT INTO weather_obs")


def test_the_delete_covers_every_source_in_the_window():
    """Scoping it to one source is what would let the double-count survive."""
    sql, _ = delete_observations_sql(SITE, datetime.now(UTC), datetime.now(UTC))
    assert "source" not in sql


def test_nothing_is_written_for_an_empty_batch(run):
    connection = FakeConnection()
    assert run(write_observations(connection, SITE, [])) == 0
    assert connection.statements == []


def test_the_insert_binds_every_column_of_every_row():
    rows = [observation(10), observation(11)]
    sql, params = insert_observations_sql(SITE, rows)
    assert sql.count("(") == len(rows) + 1  # the column list plus one per row
    assert len(params) == 11 * len(rows)
    assert "$22" in sql and "$23" not in sql


def test_the_forecast_upsert_targets_the_contract_s_unique_key():
    """``weather_forecast_key`` is ``(site_id, horizon, time, issued_at)``."""
    sql, params = upsert_forecast_sql(
        SITE,
        Forecast(
            time=datetime(2026, 6, 1, tzinfo=UTC),
            issued_at=datetime(2026, 6, 1, tzinfo=UTC),
            horizon="daily",
            temp_min_c=9.0,
        ),
    )
    assert "ON CONFLICT (site_id, horizon, time, issued_at) DO UPDATE" in sql
    assert "temp_min_c = EXCLUDED.temp_min_c" in sql
    assert "issued_at = EXCLUDED.issued_at" not in sql, "a key is not updated"
    assert len(params) == 15


def test_the_advisory_upsert_lets_a_reissue_win():
    """NWS reuses an id when it extends or cancels; the newest text must land."""
    sql, _ = upsert_advisory_sql(
        SITE, Advisory(external_id="urn:oid:1", event="Freeze Warning")
    )
    assert "ON CONFLICT (site_id, external_id) DO UPDATE" in sql
    assert "headline = EXCLUDED.headline" in sql
    assert "fetched_at = now()" in sql
    assert "gen_random_uuid()" in sql


def test_the_water_balance_upsert_is_keyed_on_the_specimen_and_the_day():
    sql, params = upsert_water_balance_sql(
        {"day": date(2026, 6, 1), "specimen_id": "spec", "deficit_mm": 4.0}
    )
    assert "ON CONFLICT (specimen_id, day) DO UPDATE" in sql
    assert "computed_at = now()" in sql
    assert params[0] == date(2026, 6, 1)
    assert params[2] == 4.0
    assert params[3] is None, "a missing column binds NULL rather than raising"


def test_only_the_contract_s_aggregates_may_be_refreshed():
    """The view name is an identifier, so it is checked rather than bound."""
    sql, params = refresh_aggregate_sql(
        "weather_daily", date(2026, 6, 1), date(2026, 6, 2)
    )
    assert sql == "CALL refresh_continuous_aggregate('weather_daily', $1, $2)"
    assert params == [date(2026, 6, 1), date(2026, 6, 2)]

    for view in ("reading_hourly", "reading_daily"):
        refresh_aggregate_sql(view, date(2026, 6, 1), date(2026, 6, 2))

    with pytest.raises(ValueError, match="not a continuous aggregate"):
        refresh_aggregate_sql(
            "weather_daily'); DROP TABLE specimen; --",
            date(2026, 6, 1),
            date(2026, 6, 2),
        )


def test_the_almanac_reads_only_the_newest_issue_of_each_forecast_hour():
    """Every issue is kept so a forecast can be checked against what happened."""
    sql, params = latest_forecast_sql(SITE, "hourly", limit=24)
    assert "DISTINCT ON (time)" in sql
    assert "ORDER BY time, issued_at DESC" in sql
    assert params == [SITE, "hourly", 24]


def test_active_advisories_are_bounded_at_both_ends():
    moment = datetime(2026, 10, 23, 6, tzinfo=UTC)
    sql, params = active_advisories_sql(SITE, moment)
    assert "onset IS NULL OR onset <= $2" in sql
    assert "expires IS NULL OR expires >= $2" in sql
    assert params == [SITE, moment]


def test_the_balance_history_window_is_passed_in_not_read_off_the_clock():
    """A builder that called ``date.today()`` would answer differently at 23:59."""
    sql, params = water_balance_history_sql("spec", date(2026, 5, 18))
    assert "day >= $2" in sql
    assert params == ["spec", date(2026, 5, 18)]
