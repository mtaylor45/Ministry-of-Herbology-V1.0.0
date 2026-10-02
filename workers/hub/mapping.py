"""Which entity is which plant — the hub.

``sensor_source`` in the frozen schema is the mapping table, and this module is
that row as a value object plus the rules it has to satisfy. The interesting
column is ``external_ids``, a JSON object the contract types as
``{string: string}`` and which this adapter reads as **metric to HA entity
id**::

    {"temperature_c": "sensor.study_temperature",
     "humidity_pct": "sensor.study_humidity"}

One row can therefore carry a thermostat's two entities together, which is
what makes "the Study" a thing the Almanac can chart rather than two unrelated
series.

## Where a row points

``location_id`` and ``specimen_id`` are both nullable, and the difference is
the whole 's soil-probe seam:

* a row with a **location** is room climate — a thermostat, a hygrometer;
* a row with a **specimen** is a probe in one pot, and its readings are what
  The weather engine's water balance honours over its own model.

So a soil metric on a row with no specimen is refused by
:func:`validation_errors`. A ``soil_moisture_pct`` series that belongs to a
room rather than to a pot is not a mislabelled row — it is the app claiming a
soil probe exists, and the design is explicit that none does. The path stays
complete and nothing pretends.

## Polling cadence

``poll_seconds`` is per row, and :meth:`SensorSource.is_due` is the whole of
the brief's "a thermostat is not a soil probe". The job runs on a fixed five
minute cron and asks each row whether it wants to be read yet, rather than
every row having to share one interval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .entities import SOIL_METRICS, SUPPORTED_METRICS
from .sources.base import HOME_ASSISTANT

#: ``sensor_source.adapter`` values this worker polls. The column's CHECK
#: allows six; the design says only one of them has a poller in v1.0, and
#: ``manual`` rows are written by a person rather than read from anywhere.
POLLED_ADAPTERS = frozenset({HOME_ASSISTANT})

#: A Home Assistant entity id is ``<domain>.<object_id>``. Only the domains
#: that can carry a number are worth mapping; a ``light.`` or a ``switch.``
#: in ``external_ids`` is a configuration mistake worth naming rather than a
#: row to poll quietly.
NUMERIC_DOMAINS = frozenset({"sensor", "number", "input_number", "climate"})


@dataclass(frozen=True, slots=True)
class SensorSource:
    """One row of ``sensor_source``."""

    id: str
    name: str
    adapter: str = HOME_ASSISTANT
    external_ids: Mapping[str, str] = field(default_factory=dict)
    location_id: str | None = None
    specimen_id: str | None = None
    poll_seconds: int = 300
    enabled: bool = True
    last_seen_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> SensorSource:
        """Build from a database row or a fixture object, tolerating either.

        asyncpg hands back a ``Record``; the fixture loader hands back a dict
        of JSON. Both are mappings with the contract's column names, so one
        constructor serves both and the job does not care which it got.
        """
        external = row.get("external_ids") or {}
        if isinstance(external, str):  # jsonb arriving as text
            import json

            external = json.loads(external)
        last_seen = row.get("last_seen_at")
        if isinstance(last_seen, str):
            from .sources.base import parse_time

            last_seen = parse_time(last_seen)
        return cls(
            id=str(row["id"]),
            name=str(row.get("name") or row["id"]),
            adapter=str(row.get("adapter") or HOME_ASSISTANT),
            external_ids={
                str(key): str(value) for key, value in dict(external).items()
            },
            location_id=_optional_str(row.get("location_id")),
            specimen_id=_optional_str(row.get("specimen_id")),
            poll_seconds=int(row.get("poll_seconds") or 300),
            enabled=bool(row.get("enabled", True)),
            last_seen_at=last_seen,
        )

    @property
    def is_soil_probe(self) -> bool:
        return any(metric in SOIL_METRICS for metric in self.external_ids)

    def bindings(self) -> tuple[tuple[str, str], ...]:
        """``(metric, entity_id)`` for the metrics this adapter can store.

        Sorted, so a poll's report and a test's expectation do not depend on
        the order a JSON object happened to be written in.
        """
        return tuple(
            sorted(
                (metric, entity)
                for metric, entity in self.external_ids.items()
                if metric in SUPPORTED_METRICS
            )
        )

    def entity_ids(self) -> tuple[str, ...]:
        return tuple(entity for _, entity in self.bindings())

    def is_due(self, now: datetime, *, last_polled_at: datetime | None = None) -> bool:
        """Has ``poll_seconds`` elapsed since this row last produced anything?

        A row that has never been polled is always due — a new thermostat
        should appear on the next run, not on the next hour. ``last_polled_at``
        overrides ``last_seen_at`` for the caller that knows better (the job
        tracks its own attempts, and an attempt that failed still counts as an
        attempt or a dead hub would be hammered every five minutes).
        """
        if not self.enabled:
            return False
        marker = last_polled_at or self.last_seen_at
        if marker is None:
            return True
        return now - marker >= timedelta(seconds=max(self.poll_seconds, 1))

    def to_dict(self) -> dict[str, Any]:
        """The contract's ``SensorSource`` shape, for a report or a mock API."""
        return {
            "id": self.id,
            "name": self.name,
            "adapter": self.adapter,
            "external_ids": dict(self.external_ids),
            "location_id": self.location_id,
            "specimen_id": self.specimen_id,
            "poll_seconds": self.poll_seconds,
            "enabled": self.enabled,
            "last_seen_at": (
                self.last_seen_at.isoformat() if self.last_seen_at else None
            ),
        }


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def validation_errors(source: SensorSource) -> list[str]:
    """Everything wrong with this row, in words an operator can act on.

    Returned rather than raised: one bad row must not stop the other eleven
    from being polled, and the list is what lands on ``integration.last_error``
    so the Ministry Office can show it.
    """
    problems: list[str] = []
    if not source.external_ids:
        problems.append(f"{source.name}: no external_ids, so nothing to read")
    for metric, entity in sorted(source.external_ids.items()):
        if metric not in SUPPORTED_METRICS:
            problems.append(
                f"{source.name}: {metric!r} is not a metric the contract stores"
            )
            continue
        domain = entity.split(".", 1)[0] if "." in entity else ""
        if not domain:
            problems.append(
                f"{source.name}: {entity!r} is not a Home Assistant entity id"
            )
        elif domain not in NUMERIC_DOMAINS:
            problems.append(
                f"{source.name}: {entity!r} is a {domain} entity, which carries "
                "no reading"
            )
        if metric in SOIL_METRICS and not source.specimen_id:
            problems.append(
                f"{source.name}: {metric} needs a specimen_id — a soil metric "
                "with no pot behind it would invent a probe"
            )
    if source.poll_seconds <= 0:
        problems.append(f"{source.name}: poll_seconds must be positive")
    return problems


def pollable(sources: list[SensorSource]) -> list[SensorSource]:
    """Enabled rows this worker is the poller for.

    ``manual`` rows and the adapters the design leaves unbuilt are skipped here
    rather than erroring: the enum keeps them as a label for where a reading
    ultimately came from, and a row labelled ``nest`` is a note about
    provenance, not a request for a Nest integration.
    """
    return [
        source
        for source in sources
        if source.enabled and source.adapter in POLLED_ADAPTERS
    ]
