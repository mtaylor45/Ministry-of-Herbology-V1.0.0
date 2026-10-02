"""Persistence and the Almanac's query paths — the weather engine.

Two halves, and the split is the point: every statement is built by a **pure
function** returning ``(sql, params)``, and a thin async layer runs them. A
database is not needed to test that the 30-day history reads the continuous
aggregate instead of scanning raw hypertable rows, and that is the kind of
mistake that stays invisible until a year of data makes it slow.

## Feeding the rollups correctly

``contracts/schema/002_rollups.sql`` defines ``weather_daily`` as

    sum(precip_mm), sum(et0_mm) … FROM weather_obs GROUP BY bucket, site_id

with **no source in the grouping**. Two consequences drive the writes here:

1. **One source per hour, per site.** If Open-Meteo's 14:00 row and NWS's 14:00
   row both survive, the day's rainfall doubles. Rain that fell twice clears a
   deficit that was never cleared, and the plant does not get watered. So a
   write replaces the whole window it covers rather than adding to it.
2. **Re-ingesting must be idempotent.** ``weather_obs`` carries no unique
   index in the frozen schema, so ``ON CONFLICT`` is not available and the
   delete-then-insert below stands in for it. A unique index on
   ``(site_id, time)`` would let the database enforce what this module can only
   promise — that is a contract change, so it is a request to the maintainers in the earlier pull
   request rather than an edit here.

``weather_forecast`` and ``weather_alert`` both have unique keys, so those are
ordinary upserts.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from .sources.base import Advisory, Forecast, Observation

#: Windows the Almanac offers, in days. The contract fixes the enum.
WINDOW_DAYS = {"1d": 1, "7d": 7, "30d": 30}

#: Metrics the contract's ``/almanac/history`` enum allows, and where each one
#: lives. Site weather comes from the weather rollup; anything about a room or
#: a pot comes from ``reading``, which the hub fills.
SITE_METRICS = {
    "temperature_c": "avg_temp_c",
    "humidity_pct": "avg_humidity_pct",
    "precip_mm": "precip_mm",
    "et0_mm": "et0_mm",
}
READING_METRICS = ("temperature_c", "humidity_pct", "soil_moisture_pct")


@runtime_checkable
class Connection(Protocol):
    """The slice of an asyncpg connection this module uses."""

    async def execute(self, sql: str, *args: Any) -> Any: ...

    async def fetch(self, sql: str, *args: Any) -> list[Any]: ...


Statement = tuple[str, list[Any]]


# ------------------------------------------------------------------- writes


def delete_observations_sql(site_id: str, start: datetime, end: datetime) -> Statement:
    """Clear a window before rewriting it. See the module note on rollups."""
    return (
        "DELETE FROM weather_obs WHERE site_id = $1 AND time >= $2 AND time <= $3",
        [site_id, start, end],
    )


def insert_observations_sql(
    site_id: str, observations: Sequence[Observation]
) -> Statement:
    """One multi-row INSERT. The rows are already one-per-hour by construction."""
    columns = (
        "time",
        "site_id",
        "temperature_c",
        "humidity_pct",
        "precip_mm",
        "et0_mm",
        "wind_kph",
        "solar_wm2",
        "cloud_pct",
        "condition",
        "source",
    )
    values: list[Any] = []
    tuples: list[str] = []
    for index, observation in enumerate(observations):
        row = observation.to_row(site_id)
        placeholders = ", ".join(
            f"${index * len(columns) + position + 1}"
            for position in range(len(columns))
        )
        tuples.append(f"({placeholders})")
        values.extend(row[column] for column in columns)
    sql = f"INSERT INTO weather_obs ({', '.join(columns)}) VALUES {', '.join(tuples)}"
    return sql, values


def upsert_forecast_sql(site_id: str, forecast: Forecast) -> Statement:
    """``weather_forecast_key`` is ``(site_id, horizon, time, issued_at)``.

    Re-running an ingest inside the same second must update rather than
    duplicate, or the Almanac shows two forecasts for one hour.
    """
    columns = (
        "time",
        "site_id",
        "issued_at",
        "horizon",
        "temperature_c",
        "temp_min_c",
        "temp_max_c",
        "precip_mm",
        "precip_prob_pct",
        "et0_mm",
        "wind_kph",
        "condition",
        "sunrise",
        "sunset",
        "source",
    )
    row = forecast.to_row(site_id)
    placeholders = ", ".join(f"${index + 1}" for index in range(len(columns)))
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in {"time", "site_id", "issued_at", "horizon"}
    )
    sql = (
        f"INSERT INTO weather_forecast ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (site_id, horizon, time, issued_at) DO UPDATE SET {updates}"
    )
    return sql, [row[column] for column in columns]


def upsert_advisory_sql(site_id: str, advisory: Advisory) -> Statement:
    """``weather_alert`` is keyed ``(site_id, external_id)``.

    NWS re-issues an advisory with the same id when it extends or cancels it,
    so the newest text must win rather than being dropped as a duplicate.
    """
    row = advisory.to_row(site_id)
    columns = (
        "site_id",
        "external_id",
        "event",
        "severity",
        "onset",
        "expires",
        "headline",
        "description",
    )
    placeholders = ", ".join(f"${index + 1}" for index in range(len(columns)))
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in {"site_id", "external_id"}
    )
    sql = (
        f"INSERT INTO weather_alert (id, {', '.join(columns)}) "
        f"VALUES (gen_random_uuid(), {placeholders}) "
        f"ON CONFLICT (site_id, external_id) DO UPDATE SET {updates}, "
        "fetched_at = now()"
    )
    return sql, [row[column] for column in columns]


#: Columns of ``water_balance`` a computed row fills. The last three are design decision
#: 0020 §4: the certainty that ``quality.py`` worked out, kept rather than
#: recomputed. Before them, a live deployment read a deficit with no
#: provenance and reported a flat ``medium`` — the live path quieter about its
#: own doubt than the fixture-backed one, which is exactly backwards.
WATER_BALANCE_COLUMNS = (
    "day",
    "specimen_id",
    "deficit_mm",
    "capacity_mm",
    "threshold_mm",
    "et0_mm",
    "k_c",
    "precip_mm",
    "irrigation_mm",
    "cover_factor",
    "sensor_override_pct",
    "confidence",
    "degraded",
    "degradations",
)

#: ``jsonb`` columns among them. asyncpg binds a Python list as an array, not
#: as json, so the value is serialised by :func:`water_balance_row` and the
#: placeholder is cast here. One entry today; a tuple so the next one is a
#: one-line change rather than a second special case.
_JSONB_COLUMNS = ("degradations",)


def water_balance_row(
    *,
    day: date,
    specimen_id: str,
    series: Any,
    last: Any,
    cover_factor: float,
    sensor_override_pct: float | None,
) -> dict[str, Any]:
    """A ``water_balance`` row from a finished :class:`BalanceSeries`.

    Built here rather than inline in the job because the job is not the only
    thing that will ever write one, and because the certainty fields are the
    part that is easy to leave off — the design exists because they were.

    ``degradations`` is serialised to a json string, not left as a list: see
    :data:`_JSONB_COLUMNS`.
    """
    assessment = series.assessment
    return {
        "day": day,
        "specimen_id": specimen_id,
        "deficit_mm": series.deficit_mm,
        "capacity_mm": series.capacity_mm,
        "threshold_mm": series.threshold_mm,
        "et0_mm": last.demand_mm,
        "k_c": series.k_c.effective,
        "precip_mm": last.precip_mm,
        "irrigation_mm": last.irrigation_mm,
        "cover_factor": cover_factor,
        "sensor_override_pct": sensor_override_pct,
        "confidence": assessment.confidence,
        "degraded": assessment.is_degraded,
        "degradations": json.dumps(
            [degradation.to_dict() for degradation in assessment.degradations]
        ),
    }


def upsert_water_balance_sql(row: dict[str, Any]) -> Statement:
    """One ``water_balance`` row per specimen per day, keyed on both.

    A row written without ``confidence``/``degraded``/``degradations`` is
    accepted — migration 004 defaults them — and reads afterwards as "it did
    not say", which is what the design asks for and is not the same as "it was
    certain".
    """
    columns = WATER_BALANCE_COLUMNS
    placeholders = ", ".join(
        f"${index + 1}::jsonb" if column in _JSONB_COLUMNS else f"${index + 1}"
        for index, column in enumerate(columns)
    )
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in {"day", "specimen_id"}
    )
    sql = (
        f"INSERT INTO water_balance ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (specimen_id, day) DO UPDATE SET {updates}, computed_at = now()"
    )
    return sql, [row.get(column) for column in columns]


def refresh_aggregate_sql(view: str, start: date, end: date) -> Statement:
    """Refresh a continuous aggregate over the window an ingest just touched.

    The scheduled policies in ``002_rollups.sql`` run hourly, which is right for
    steady state and too slow after a backfill: a user who has just added a
    site should not wait an hour to see any history. Timescale refuses this
    inside a transaction, so the caller runs it outside one.

    The view name is interpolated rather than bound because it is an identifier,
    not a value; it is checked against the three the contract defines.
    """
    if view not in {"reading_hourly", "reading_daily", "weather_daily"}:
        raise ValueError(f"not a continuous aggregate in the contract: {view!r}")
    return (f"CALL refresh_continuous_aggregate('{view}', $1, $2)", [start, end])


# -------------------------------------------------------------------- reads


def daily_weather_sql(site_id: str, start: date, end: date) -> Statement:
    """The Almanac's history, read from ``weather_daily`` — never from raw rows.

    The retention policy drops raw ``reading`` rows after 400 days and the
    rollups carry the long history, so a query that scans the hypertable is
    both slower and, eventually, wrong.
    """
    sql = (
        "SELECT bucket, avg_temp_c, min_temp_c, max_temp_c, avg_humidity_pct, "
        "precip_mm, et0_mm FROM weather_daily "
        "WHERE site_id = $1 AND bucket >= $2 AND bucket < $3 ORDER BY bucket"
    )
    return sql, [site_id, start, end]


def reading_series_sql(
    metric: str,
    *,
    location_id: str | None = None,
    specimen_id: str | None = None,
    start: date,
    end: date,
    daily: bool = True,
) -> Statement:
    """Indoor and sensor history, from ``reading_daily`` or ``reading_hourly``."""
    view = "reading_daily" if daily else "reading_hourly"
    conditions = ["metric = $1", "bucket >= $2", "bucket < $3"]
    params: list[Any] = [metric, start, end]
    if location_id:
        params.append(location_id)
        conditions.append(f"location_id = ${len(params)}")
    if specimen_id:
        params.append(specimen_id)
        conditions.append(f"specimen_id = ${len(params)}")
    sql = (
        f"SELECT bucket, avg_value, min_value, max_value, samples FROM {view} "
        f"WHERE {' AND '.join(conditions)} ORDER BY bucket"
    )
    return sql, params


def latest_forecast_sql(site_id: str, horizon: str, *, limit: int) -> Statement:
    """The most recently issued forecast for each time, and nothing older.

    ``weather_forecast`` keeps every issue so a forecast can be compared with
    what happened. The Almanac wants only the newest per hour or day, which is
    what ``DISTINCT ON`` gives.
    """
    sql = (
        "SELECT DISTINCT ON (time) time, temperature_c, temp_min_c, temp_max_c, "
        "precip_mm, precip_prob_pct, et0_mm, wind_kph, condition, sunrise, "
        "sunset, source, issued_at FROM weather_forecast "
        "WHERE site_id = $1 AND horizon = $2 AND time >= now() - INTERVAL '1 hour' "
        "ORDER BY time, issued_at DESC LIMIT $3"
    )
    return sql, [site_id, horizon, limit]


def latest_observation_time_sql(site_id: str) -> Statement:
    """How stale the ingest is — the number the water balance has to publish."""
    return (
        "SELECT max(time) AS newest FROM weather_obs WHERE site_id = $1",
        [site_id],
    )


def active_advisories_sql(site_id: str, moment: datetime) -> Statement:
    sql = (
        "SELECT external_id, event, severity, onset, expires, headline, description "
        "FROM weather_alert WHERE site_id = $1 "
        "AND (onset IS NULL OR onset <= $2) AND (expires IS NULL OR expires >= $2) "
        "ORDER BY onset NULLS FIRST"
    )
    return sql, [site_id, moment]


def water_balance_history_sql(specimen_id: str, since: date) -> Statement:
    """``since`` is passed in rather than read off the clock.

    A query builder that calls ``date.today()`` answers differently at 23:59
    and 00:01, which makes both the test and the bug report irreproducible.
    """
    sql = (
        "SELECT day, deficit_mm, capacity_mm, threshold_mm, et0_mm, k_c, "
        "precip_mm, irrigation_mm, cover_factor, sensor_override_pct, "
        # the design. Selected here so a database-backed read can answer with
        # the doubt the engine recorded, instead of the flat `medium` that was
        # all a row without these columns could honestly support.
        "confidence, degraded, degradations "
        "FROM water_balance WHERE specimen_id = $1 AND day >= $2 ORDER BY day"
    )
    return sql, [specimen_id, since]


# ---------------------------------------------------------------- execution


async def write_observations(
    connection: Connection, site_id: str, observations: Sequence[Observation]
) -> int:
    """Replace a window of ``weather_obs`` with these rows. Returns the count.

    Caller should hold a transaction: the delete and the insert are one change,
    and a crash between them would leave a hole in the rollups that nothing
    would ever refill.
    """
    if not observations:
        return 0
    times = [observation.time for observation in observations]
    sql, params = delete_observations_sql(site_id, min(times), max(times))
    await connection.execute(sql, *params)
    sql, params = insert_observations_sql(site_id, observations)
    await connection.execute(sql, *params)
    return len(observations)


async def write_forecasts(
    connection: Connection, site_id: str, forecasts: Sequence[Forecast]
) -> int:
    for forecast in forecasts:
        sql, params = upsert_forecast_sql(site_id, forecast)
        await connection.execute(sql, *params)
    return len(forecasts)


async def write_advisories(
    connection: Connection, site_id: str, advisories: Sequence[Advisory]
) -> int:
    for advisory in advisories:
        sql, params = upsert_advisory_sql(site_id, advisory)
        await connection.execute(sql, *params)
    return len(advisories)


async def write_water_balance(
    connection: Connection, rows: Sequence[dict[str, Any]]
) -> int:
    for row in rows:
        sql, params = upsert_water_balance_sql(row)
        await connection.execute(sql, *params)
    return len(rows)


async def refresh_aggregates(
    connection: Connection,
    start: date,
    end: date,
    views: Sequence[str] = ("weather_daily",),
) -> None:
    for view in views:
        sql, params = refresh_aggregate_sql(view, start, end)
        await connection.execute(sql, *params)
