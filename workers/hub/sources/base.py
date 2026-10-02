"""The shape the hub adapter is built from — the hub.

The same three-part split the botany worker and the weather engine used, for the same reason:
exactly one part touches the network, so the other two are testable against a
payload forever.

1. a **fetcher**, the only thing that opens a socket;
2. **pure functions** over a payload, returning rows;
3. a **source** binding the two, which also reports *why* it came back with
   nothing — because Home Assistant is the only route to indoor
   conditions, and "the study is 21 °C" and "nobody has been able to ask since
   Tuesday" must never reach a screen looking the same.

:class:`Reading` mirrors ``contracts/schema/001_init.sql`` column for column.
A parser that invents a field it cannot store should not typecheck.

## Why an entity that answers can still be dropped

Home Assistant serves the last state it saw, with no expiry. A sensor whose
battery died in March still answers in July, with March's number and March's
``last_updated``. :class:`EntityState.is_fresh` is the check that turns that
into an absence, and the design rule — where a reading is absent the API says
absent, never a plausible default — is why the value is dropped rather than
stored with a caveat.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

HOME_ASSISTANT = "home_assistant"

#: Home Assistant's own words for "I do not have a value". They arrive in the
#: ``state`` field exactly where a number would be, and reading either of them
#: as zero would put a 0 °C room and a 0 % soil probe into the hypertable.
ABSENT_STATES = frozenset({"unavailable", "unknown", "none", "", "null"})


class HubUnavailable(RuntimeError):
    """Home Assistant could not be reached, or would not answer.

    Distinct from Home Assistant answering with nothing. "That entity does not
    exist" is a fact about the configuration; "the hub refused the token" is a
    fact about us, and the Ministry Office must not print the second as the
    first.
    """


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One payload, and the request that produced it."""

    url: str
    payload: Any
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_mock: bool = False


@runtime_checkable
class Fetcher(Protocol):
    """The only thing in this worker allowed to touch the network."""

    async def get_json(
        self, kind: str, path: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult: ...


@runtime_checkable
class Poster(Protocol):
    """A fetcher that can also *ask Home Assistant to do something*.

    Kept apart from :class:`Fetcher` deliberately. Everything read state
    and changed nothing, and a read-only adapter is a safe thing to point at
    somebody's house. an earlier release adds notifications, which are a service call — so the
    ability to act is a second, narrower protocol that a caller has to ask for,
    rather than a method quietly added to the one every poller already holds.
    """

    async def post_json(
        self, kind: str, path: str, body: Mapping[str, Any] | None = None
    ) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class EntityState:
    """One entity as ``GET /api/states`` returns it.

    ``last_updated`` is Home Assistant's, not ours, and it is the only
    evidence available about whether the underlying device is still alive.
    """

    entity_id: str
    state: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    last_changed: datetime | None = None
    last_updated: datetime | None = None

    @property
    def unit(self) -> str | None:
        value = self.attributes.get("unit_of_measurement")
        return str(value) if value is not None else None

    @property
    def device_class(self) -> str | None:
        value = self.attributes.get("device_class")
        return str(value).lower() if value is not None else None

    @property
    def friendly_name(self) -> str:
        return str(self.attributes.get("friendly_name") or self.entity_id)

    @property
    def is_absent(self) -> bool:
        """Did Home Assistant say it has no value?"""
        return self.state.strip().lower() in ABSENT_STATES

    @property
    def numeric(self) -> float | None:
        """The state as a number, or ``None`` — never a zero standing in."""
        return None if self.is_absent else as_float(self.state)

    def age(self, now: datetime) -> timedelta | None:
        if self.last_updated is None:
            return None
        return now - self.last_updated

    def is_fresh(self, now: datetime, max_age_s: float) -> bool:
        """Is this a measurement, or a memory?

        An entity with no ``last_updated`` at all is treated as **not** fresh.
        HA always sends one; a payload without it is a payload we do not
        understand, and guessing in the generous direction is how a dead
        sensor goes on reporting.
        """
        age = self.age(now)
        if age is None:
            return False
        # A stamp in the future is a clock disagreement, not staleness. It is
        # allowed through: the alternative is dropping every reading from a
        # hub whose NTP is a few seconds ahead.
        return age.total_seconds() <= max_age_s


@dataclass(frozen=True, slots=True)
class Reading:
    """One row of ``reading``: what a sensor said, and where it belongs."""

    time: datetime
    source_id: str
    metric: str
    value: float
    location_id: str | None = None
    specimen_id: str | None = None
    #: The entity it came from. Not a column — carried for the job's report and
    #: for the error message when a mapping turns out to be wrong.
    entity_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "source_id": self.source_id,
            "metric": self.metric,
            "value": self.value,
            "location_id": self.location_id,
            "specimen_id": self.specimen_id,
        }


@dataclass(frozen=True, slots=True)
class Skipped:
    """An entity that was asked for and did not become a reading.

    Every one of these is named in the job's report. A poll that quietly
    returns four readings where five were configured is the silent failure
    this parts of the project exists to prevent.
    """

    entity_id: str
    metric: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "entity_id": self.entity_id,
            "metric": self.metric,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PollResult:
    """What one poll of Home Assistant came back with."""

    readings: tuple[Reading, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    #: Set when Home Assistant could not be reached at all. A hub that is down
    #: must not look like a hub with nothing to report.
    error: str | None = None
    is_mock: bool = False
    polled_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "is_mock": self.is_mock,
            "readings": len(self.readings),
            "metrics": sorted({reading.metric for reading in self.readings}),
            "skipped": [item.to_dict() for item in self.skipped],
            "polled_at": (
                self.polled_at.isoformat() if self.polled_at is not None else None
            ),
        }


def as_float(value: Any) -> float | None:
    """A number, or ``None`` — never a zero standing in for a missing reading."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_time(value: Any) -> datetime | None:
    """ISO-8601 in, aware UTC out.

    Home Assistant sends offsets (usually ``+00:00``); everything is stored
    UTC (``timestamptz``), so this is where the two meet. A naive stamp is
    read as UTC, which is what HA means when it omits the offset.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (
        moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    )


def parse_state(row: Any) -> EntityState | None:
    """One element of ``GET /api/states`` into an :class:`EntityState`."""
    if not isinstance(row, Mapping):
        return None
    entity_id = row.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        return None
    attributes = row.get("attributes")
    return EntityState(
        entity_id=entity_id,
        state="" if row.get("state") is None else str(row.get("state")),
        attributes=dict(attributes) if isinstance(attributes, Mapping) else {},
        last_changed=parse_time(row.get("last_changed")),
        last_updated=parse_time(row.get("last_updated")),
    )


def parse_states(payload: Any) -> dict[str, EntityState]:
    """The whole ``/api/states`` collection, keyed by entity id.

    A single-entity ``GET /api/states/<id>`` returns the bare object rather
    than a list, so both shapes are accepted here instead of at two call
    sites.
    """
    rows = payload if isinstance(payload, list) else [payload]
    states: dict[str, EntityState] = {}
    for row in rows:
        state = parse_state(row)
        if state is not None:
            states[state.entity_id] = state
    return states
