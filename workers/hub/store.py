"""Persistence for the hub — the hub.

The same two halves the weather engine used, and the split is the point: every
statement is built by a **pure function** returning ``(sql, params)``, and a
thin async layer runs them. No database is needed to prove that a poll writes
``reading`` rows at the poll's own timestamp, that a failure lands on
``integration.last_error`` rather than in a log, or that the rollup covering
the touched hour is refreshed — and those are the mistakes that stay invisible
until a month of data makes them obvious.

## Two notes on the frozen schema

**``reading`` carries no unique index**, so ``ON CONFLICT`` is not available.
It does not need to be, because :func:`insert_readings_sql` writes at the
poll's timestamp: two runs of the same job produce two different seconds
rather than a collision. What *is* guarded is a job re-run within one poll
interval, and that is guarded in :mod:`workers.hub.tasks` by asking each
source whether it is due. A unique index on
``(source_id, metric, time)`` would let the database enforce what this module
can only promise; that is a contract change, so it is a request to the maintainers in the
pull request rather than an edit here.

**``integration`` is keyed only on ``id``.** There is no unique constraint on
``(kind, name)``, so "record that Home Assistant answered" cannot be a plain
upsert without knowing the row's id first. :func:`integration_id_for` derives
a stable UUID from the kind and name so the worker and the API agree on it
with no lookup and no race. That is a workaround for a missing index and it is
also on the list for the maintainers.

Both writes are small on purpose. The Ministry Office asks a question — *is
the hub answering?* — and a health record that is itself expensive to write is
a health record that stops being written on the day it matters.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .sources.base import Reading

if TYPE_CHECKING:
    from .mapping import SensorSource

#: Namespace for :func:`integration_id_for`. Fixed forever — changing it
#: orphans every existing row.
INTEGRATION_NAMESPACE = uuid.UUID("6f6d6f68-0000-5000-8000-000000000f00")

#: The continuous aggregates over ``reading`` that a poll can touch.
READING_AGGREGATES = ("reading_hourly", "reading_daily")


@runtime_checkable
class Connection(Protocol):
    """The slice of an asyncpg connection this module uses."""

    async def execute(self, sql: str, *args: Any) -> Any: ...

    async def fetch(self, sql: str, *args: Any) -> list[Any]: ...


Statement = tuple[str, list[Any]]


def integration_id_for(kind: str, name: str) -> str:
    """A stable id for one integration, derived rather than stored.

    See the module note: without a unique index on ``(kind, name)`` the
    alternative is a select-then-insert, which two workers racing at startup
    turn into two rows for one Home Assistant.
    """
    return str(uuid.uuid5(INTEGRATION_NAMESPACE, f"{kind}:{name}"))


# ------------------------------------------------------------------- writes


def insert_readings_sql(readings: Sequence[Reading]) -> Statement:
    """One multi-row INSERT into the ``reading`` hypertable."""
    columns = ("time", "source_id", "metric", "value", "location_id", "specimen_id")
    values: list[Any] = []
    tuples: list[str] = []
    for index, reading in enumerate(readings):
        row = reading.to_row()
        placeholders = ", ".join(
            f"${index * len(columns) + position + 1}"
            for position in range(len(columns))
        )
        tuples.append(f"({placeholders})")
        values.extend(row[column] for column in columns)
    sql = f"INSERT INTO reading ({', '.join(columns)}) VALUES {', '.join(tuples)}"
    return sql, values


def touch_sensor_source_sql(source_id: str, seen_at: datetime) -> Statement:
    """Record that a source produced something.

    Only called when it actually did. ``last_seen_at`` is what
    :class:`~workers.hub.health.SourceHealth` reads to say *no recent
    reading*, so stamping it on a poll that returned nothing would make a dead
    sensor look alive — which is the exact failure the design asks F to prevent.
    """
    sql = "UPDATE sensor_source SET last_seen_at = $2 WHERE id = $1"
    return sql, [source_id, seen_at]


def insert_sensor_source_sql(source: SensorSource) -> Statement:
    """One new ``sensor_source`` row, as ``POST /hub/sensors`` received it.

    ``last_seen_at`` is not written: a row nobody has polled has not been seen,
    and :class:`~workers.hub.health.SourceHealth` says *never reported* until
    the poll proves otherwise.
    """
    import json

    sql = (
        "INSERT INTO sensor_source (id, name, adapter, external_ids, location_id, "
        "specimen_id, poll_seconds, enabled) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)"
    )
    return sql, [
        source.id,
        source.name,
        source.adapter,
        json.dumps(dict(source.external_ids), sort_keys=True),
        source.location_id,
        source.specimen_id,
        source.poll_seconds,
        source.enabled,
    ]


def ensure_integration_sql(kind: str, name: str) -> Statement:
    """Create the ``integration`` row if this deployment has not got one."""
    sql = (
        "INSERT INTO integration (id, kind, name) VALUES ($1, $2, $3) "
        "ON CONFLICT (id) DO NOTHING"
    )
    return sql, [integration_id_for(kind, name), kind, name]


def record_integration_ok_sql(kind: str, name: str, at: datetime) -> Statement:
    """It worked: stamp ``last_ok_at`` and clear the error.

    The error is cleared rather than kept. A stale error beside a fresh
    success is a screen that cries wolf, and the history of failures belongs
    in ``job_run``, which keeps one row per run.
    """
    sql = "UPDATE integration SET last_ok_at = $2, last_error = NULL WHERE id = $1"
    return sql, [integration_id_for(kind, name), at]


def record_integration_error_sql(kind: str, name: str, error: str) -> Statement:
    """It did not work. ``last_ok_at`` is left alone — it is still true.

    The caller passes text that has already been through
    :func:`workers.hub.health.redact`; this function does not redact, so that
    a reviewer can see in one place that the scrubbing happens before the
    value is anywhere near a statement.
    """
    sql = "UPDATE integration SET last_error = $2 WHERE id = $1"
    return sql, [integration_id_for(kind, name), error]


def record_job_run_sql(
    job: str,
    *,
    started_at: datetime,
    finished_at: datetime,
    ok: bool,
    detail: dict[str, Any],
) -> Statement:
    """One row per run in ``job_run``, so "when did this last work" is answerable.

    ``integration.last_error`` holds the current state and nothing more. The
    question an operator actually asks — *has this been failing since
    Tuesday, or since the restart?* — needs the history, and this is it.
    """
    import json

    sql = (
        "INSERT INTO job_run (id, job, started_at, finished_at, ok, detail) "
        "VALUES ($1, $2, $3, $4, $5, $6)"
    )
    return sql, [
        str(uuid.uuid4()),
        job,
        started_at,
        finished_at,
        ok,
        json.dumps(detail, default=str),
    ]


def refresh_aggregate_sql(view: str, start: date, end: date) -> Statement:
    """Refresh a continuous aggregate over the window a poll just touched.

    The scheduled policies in ``002_rollups.sql`` run hourly, which is right
    for steady state and too slow for a screen someone is looking at now.
    Timescale refuses this inside a transaction, so the caller runs it outside
    one.

    The view name is interpolated because it is an identifier, not a value; it
    is checked against the two the contract defines over ``reading``.
    """
    if view not in READING_AGGREGATES:
        raise ValueError(f"not a continuous aggregate over reading: {view!r}")
    return (f"CALL refresh_continuous_aggregate('{view}', $1, $2)", [start, end])


# -------------------------------------------------------------------- reads


def sensor_sources_sql(*, adapter: str | None = None) -> Statement:
    """Every configured source, newest mapping last.

    Disabled rows are **not** filtered out in SQL. The Ministry Office has to
    show a source somebody turned off as disabled rather than as missing, and
    a query that hides it makes that impossible without a second query.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if adapter:
        params.append(adapter)
        conditions.append(f"adapter = ${len(params)}")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        "SELECT id, name, adapter, external_ids, location_id, specimen_id, "
        f"poll_seconds, enabled, last_seen_at FROM sensor_source{where} "
        "ORDER BY created_at"
    )
    return sql, params


def integrations_sql() -> Statement:
    """What the Ministry Office reads. ``config`` is deliberately not selected.

    ``integration.config`` is a jsonb blob whose comment in the schema says
    secrets live in the secret store — which is a convention, not a
    constraint. Not selecting it means a misconfigured deployment that put one
    there cannot leak it through a health screen.
    """
    sql = (
        "SELECT id, kind, name, enabled, last_ok_at, last_error "
        "FROM integration ORDER BY kind, name"
    )
    return sql, []


def notified_keys_sql(since: datetime, jobs: Sequence[str]) -> Statement:
    """Every notification key the notify jobs recorded since ``since``.

    There is no ``notification`` table in the frozen schema, so "have we
    already told them this?" is answered from ``job_run``, which each job
    writes anyway. ``job_run_job_idx`` is on ``(job, started_at DESC)``, so
    this is an index scan over a bounded window rather than a table sweep.

    It is a workaround for a missing table and it is on the list for the maintainers. What it
    cannot do is what a real table would: expire one key, or record *which*
    member a key went to without unpacking the blob. What it can do is stop a
    household being told the same thing twice, which is the whole requirement
    today.
    """
    placeholders = ", ".join(f"${index + 2}" for index in range(len(jobs)))
    sql = (
        "SELECT detail FROM job_run WHERE started_at >= $1 "
        f"AND job IN ({placeholders}) ORDER BY started_at DESC LIMIT 500"
    )
    return sql, [since, *jobs]


def latest_reading_sql(source_id: str, metric: str) -> Statement:
    """The newest stored reading for one source and metric.

    Used to answer "is this series live" without scanning, and to keep a
    re-run from stacking a second row inside one poll interval.
    """
    sql = (
        "SELECT time, value FROM reading WHERE source_id = $1 AND metric = $2 "
        "ORDER BY time DESC LIMIT 1"
    )
    return sql, [source_id, metric]


# ---------------------------------------------------------------- execution


async def write_readings(connection: Connection, readings: Sequence[Reading]) -> int:
    """Insert the poll's rows and stamp every source that produced one."""
    if not readings:
        return 0
    sql, params = insert_readings_sql(readings)
    await connection.execute(sql, *params)
    seen: dict[str, datetime] = {}
    for reading in readings:
        current = seen.get(reading.source_id)
        if current is None or reading.time > current:
            seen[reading.source_id] = reading.time
    for source_id, moment in seen.items():
        sql, params = touch_sensor_source_sql(source_id, moment)
        await connection.execute(sql, *params)
    return len(readings)


async def record_ok(connection: Connection, kind: str, name: str, at: datetime) -> None:
    for builder in (ensure_integration_sql(kind, name),):
        await connection.execute(builder[0], *builder[1])
    sql, params = record_integration_ok_sql(kind, name, at)
    await connection.execute(sql, *params)


async def record_error(
    connection: Connection, kind: str, name: str, error: str
) -> None:
    sql, params = ensure_integration_sql(kind, name)
    await connection.execute(sql, *params)
    sql, params = record_integration_error_sql(kind, name, error)
    await connection.execute(sql, *params)


async def record_job_run(
    connection: Connection,
    job: str,
    *,
    started_at: datetime,
    finished_at: datetime,
    ok: bool,
    detail: dict[str, Any],
) -> None:
    sql, params = record_job_run_sql(
        job,
        started_at=started_at,
        finished_at=finished_at,
        ok=ok,
        detail=detail,
    )
    await connection.execute(sql, *params)


async def refresh_aggregates(
    connection: Connection,
    start: date,
    end: date,
    views: Sequence[str] = READING_AGGREGATES,
) -> None:
    for view in views:
        sql, params = refresh_aggregate_sql(view, start, end)
        await connection.execute(sql, *params)


async def read_sensor_sources(
    connection: Connection, *, adapter: str | None = None
) -> list[Any]:
    sql, params = sensor_sources_sql(adapter=adapter)
    return await connection.fetch(sql, *params)


async def read_integrations(connection: Connection) -> list[Any]:
    sql, params = integrations_sql()
    return await connection.fetch(sql, *params)


async def read_notified_keys(
    connection: Connection, since: datetime, jobs: Sequence[str] | None = None
) -> list[Any]:
    from .notify.policy import NOTIFY_JOBS

    sql, params = notified_keys_sql(since, tuple(jobs or NOTIFY_JOBS))
    return await connection.fetch(sql, *params)
