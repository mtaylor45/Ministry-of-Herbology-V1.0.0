"""The storage seam.

Two implementations answer one protocol, exactly as the inventory API's Register
does: ``FixtureRepository`` keeps the schedule in memory seeded from
``fixtures/`` (``MOH_MOCK_MODE=true``, how every other parts of the project runs the
stack), and ``DatabaseRepository`` talks to the Postgres the deployment ships
with. The router and the service know only this interface, so neither path can
quietly grow behaviour the other lacks — and "daily care runs from the app"
has to be true in both, because the demo runs in one and the household runs in
the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from app.settings import get_settings
from tending.domain import Environment, Outlook, Rule, Subject

#: A stored row, hydrated with whatever the response needs joined onto it.
Record = dict[str, Any]


class UnknownFeedError(LookupError):
    """A revoke named a feed nothing matches. The router answers 404."""


class UnknownMemberError(LookupError):
    """A feed or completion named a member nothing matches. The router answers 422."""


class UnknownSpecimenError(LookupError):
    """A care rule named a specimen nothing matches. The router answers 422."""


@dataclass(frozen=True, slots=True)
class TaskQuery:
    """``GET /tending/tasks``, as the contract declares its filters."""

    status: str | None = None
    specimen_id: str | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    """What a member says when they tick something off."""

    completed_by: str | None = None
    amount_ml: int | None = None
    notes: str | None = None
    #: A ``bring_indoors`` or ``return_outdoors`` completion moves the plant:
    #: recorded on the task event *and* written through the inventory API's own
    #: ``update_specimen`` (see ``tending.relocation``). The contract documents
    #: it as "set when completing a bring_indoors task", and a completion of
    #: anything else that carries one is refused rather than silently ignored.
    new_location_id: str | None = None


@dataclass(slots=True)
class SchedulingInputs:
    """Everything :func:`tending.service.generate_tasks` needs, gathered once.

    One object rather than six calls because the database path fetches it in a
    handful of queries: a schedule that ran a query per plant would be twelve
    round trips for Morning Rounds and would get slower with every plant added.
    """

    subjects: list[Subject] = field(default_factory=list)
    rules: dict[str, list[Rule]] = field(default_factory=dict)
    #: Why a plant has no rule for something it plainly needs. Surfaced, never
    #: swallowed — see ``tending.defaults``.
    unscheduled: dict[str, list[str]] = field(default_factory=dict)
    environments: dict[str, Environment] = field(default_factory=dict)
    #: ``(specimen_id, task_type) -> the day it was last actually done``.
    last_completed: dict[tuple[str, str], date] = field(default_factory=dict)
    latitude: float = 0.0
    #: The weather engine's open frost alerts, exactly as it serves them. The frost
    #: guard's tasks are raised from these (``tending.frost``), and Morning
    #: Rounds serves them back with ``task_id`` filled, so both halves of the
    #: link come from one read of one engine.
    frost_alerts: list[Record] = field(default_factory=list)
    #: The nights ahead and the sunsets that end the days, from the weather engine's forecast.
    outlook: Outlook = field(default_factory=Outlook)


@dataclass(frozen=True, slots=True)
class PushOutcome:
    """What one calendar push leaves behind on its feed (migration 007).

    ``state`` always replaces ``push_state``. ``ok_at`` set means the push
    finished clean: ``push_last_ok_at`` takes it, ``push_error`` is cleared,
    and ``push_dirty_since`` is cleared **only if** it is no later than
    ``started_at`` — a change that landed while the push was running is still
    owed. ``ok_at`` unset means ``push_error`` takes ``error``.
    """

    state: dict[str, Any]
    started_at: datetime
    ok_at: datetime | None = None
    error: str | None = None


class TendingRepository(Protocol):
    """Everything the tending service needs from storage."""

    async def scheduling_inputs(self) -> SchedulingInputs: ...

    async def upsert_tasks(self, rows: list[Record]) -> None: ...

    async def tasks(self, query: TaskQuery) -> list[Record]: ...

    async def task(self, task_id: str) -> Record | None: ...

    async def complete(
        self, task_ids: list[str], completion: Completion
    ) -> list[Record]: ...

    async def withdraw_tasks(self, task_ids: list[str], *, detail: str) -> None: ...

    async def cancel_tasks(self, task_ids: list[str]) -> None: ...

    async def relocate_specimen(self, specimen_id: str, location_id: str) -> None: ...

    async def care_rules(self, specimen_id: str | None = None) -> list[Record]: ...

    async def create_care_rule(self, record: Record) -> Record: ...

    async def feeds(self) -> list[Record]: ...

    async def create_feed(self, record: Record) -> Record: ...

    async def revoke_feed(self, feed_id: str) -> Record: ...

    async def feed_by_token(self, token: str) -> Record | None: ...

    async def touch_feed(self, feed_id: str) -> None: ...

    async def feed(self, feed_id: str) -> Record | None: ...

    async def mark_push_owed(self, feed_id: str, since: datetime) -> None:
        """Set ``push_dirty_since`` unless it is already set. Never on a revoked feed."""
        ...

    async def record_push(self, feed_id: str, outcome: PushOutcome) -> None:
        """Store what one push did. Never on a revoked feed."""
        ...

    async def frost_alerts(self) -> list[Record]: ...

    async def weather_today(self) -> Record | None: ...


async def get_repository() -> TendingRepository:
    """FastAPI dependency: fixtures when mocking, Postgres when not.

    Mock mode is the default and stays a complete, writable API —
    completion, feed creation and revocation all work there, because the earlier
    exit criterion is demonstrated on the mock stack before it is demonstrated
    on a deployment.
    """
    if get_settings().mock_mode:
        from tending.fixture_repository import fixture_repository

        return fixture_repository()

    from tending.database_repository import DatabaseRepository
    from tending.db import get_engine

    return DatabaseRepository(get_engine())
