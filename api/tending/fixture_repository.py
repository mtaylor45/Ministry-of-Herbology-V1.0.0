"""The schedule in memory, seeded from ``fixtures/`` — mock mode.

Writes live in the process: complete a task here and it stays completed until
the API restarts, which is what lets Morning Rounds, batch completion and a
subscribable calendar be demonstrated end to end with no database attached. It is not a read-only
stub, because an an earlier release exit criterion
that only works against Postgres cannot be shown at the releases demo.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, date, datetime
from typing import Any

from app import fixtures
from tending import environment as env
from tending import relocation, tokens
from tending.defaults import default_rules
from tending.domain import Rule, Subject, registered_on
from tending.repository import (
    Completion,
    PushOutcome,
    Record,
    SchedulingInputs,
    TaskQuery,
    UnknownFeedError,
    UnknownSpecimenError,
)
from tending.tables import TASK_REGENERATED

#: The household's single member in the fixtures, matching the inventory API's
#: ``FixtureRepository``. one shared login, a member picker.
KEEPER_ID = "01890050-0000-7000-8000-000000000001"

#: Deterministic id for the feed every fresh install gets, so that restarting
#: the mock does not orphan a subscription somebody just added. The *token* is
#: minted fresh each boot and is never this predictable.
DEFAULT_FEED_ID = "01890060-0000-7000-8000-000000000001"


#: Migration 007's columns as a new feed has them.
_PUSH_NOTHING_YET: Record = {
    "push_state": {},
    "push_dirty_since": None,
    "push_last_ok_at": None,
    "push_error": None,
}


def _terminal(status: str) -> bool:
    return status in {"done", "cancelled", "skipped"}


def _instant(value: Any) -> datetime | None:
    """A fixture timestamp, which JSON can only carry as a string."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class FixtureRepository:
    """An in-memory schedule. Ordering is fixture order, then order of arrival."""

    def __init__(self) -> None:
        # Deep copies: ``app.fixtures`` caches the parsed JSON, and a store that
        # mutated it would rewrite the fixture data for every other reader.
        self._specimens: list[Record] = copy.deepcopy(fixtures.specimens())
        self._species: list[Record] = copy.deepcopy(fixtures.species())
        self._locations: list[Record] = copy.deepcopy(fixtures.locations())
        self._tasks: dict[str, Record] = {}
        self._events: list[Record] = []
        self._rules: list[Record] = []
        self._feeds: list[Record] = [self._default_feed()]
        # Mirrors the inventory API's fixture Register, which is the household this
        # mock schedules for. Completion is attributed to a member or it is not
        # history, only a checkbox.
        self._members: list[Record] = [
            {"id": KEEPER_ID, "name": "Keeper", "role": "keeper", "notify_prefs": {}},
        ]

    # ---------------------------------------------------------------- helpers

    def _default_feed(self) -> Record:
        return {
            "id": DEFAULT_FEED_ID,
            "member_id": KEEPER_ID,
            "name": "All rounds",
            "token": tokens.mint(),
            "filters": {},
            "push_target": "none",
            "push_config": {},
            **_PUSH_NOTHING_YET,
            "last_rendered_at": None,
            "revoked_at": None,
            "created_at": datetime.now(UTC),
        }

    def _species_for(self, specimen: Record) -> Record:
        species_id = specimen.get("species_id") or ""
        return next((s for s in self._species if s["id"] == species_id), {})

    def _location_for(self, specimen: Record) -> Record:
        location_id = specimen.get("location_id") or ""
        return next((row for row in self._locations if row["id"] == location_id), {})

    def _subject(self, specimen: Record) -> Subject:
        species = self._species_for(specimen)
        acquired = specimen.get("acquired_on")
        return Subject(
            specimen_id=str(specimen["id"]),
            display_name=fixtures.display_name(specimen),
            has_nickname=bool(specimen.get("nickname")),
            is_outdoor=bool(specimen.get("is_outdoor")),
            in_container=bool(specimen.get("in_container")),
            location_id=specimen.get("location_id"),
            container_litres=specimen.get("container_litres"),
            species_id=specimen.get("species_id"),
            dormancy_months=tuple(species.get("dormancy_months") or ()),
            acquired_on=date.fromisoformat(acquired) if acquired else None,
            # The fixture specimens carry no ``created_at`` today; read it when
            # one does, so the mock anchors a new plant the way Postgres does.
            added_on=registered_on(
                _instant(specimen.get("created_at")), fixtures.site().get("timezone")
            ),
        )

    def _stored_rules_for(self, specimen_id: str, species_id: str | None) -> list[Rule]:
        out: list[Rule] = []
        for row in self._rules:
            if row.get("specimen_id") == specimen_id or (
                row.get("species_id") and row.get("species_id") == species_id
            ):
                out.append(_rule_from_record(row))
        return out

    # ------------------------------------------------------------- scheduling

    async def scheduling_inputs(self) -> SchedulingInputs:
        inputs = SchedulingInputs(latitude=float(fixtures.site()["latitude"]))
        for specimen in self._specimens:
            if specimen.get("archived_at"):
                continue
            subject = self._subject(specimen)
            species = self._species_for(specimen)
            derived, reasons = default_rules(
                subject,
                species.get("care_values") or [],
                species.get("water_interval_days"),
            )
            stored = self._stored_rules_for(subject.specimen_id, subject.species_id)
            inputs.subjects.append(subject)
            # Stored rules come last so ``resolve_rules`` lets a specimen-scoped
            # rule the household wrote win over the one this package derived.
            inputs.rules[subject.specimen_id] = derived + stored
            if reasons and not stored:
                inputs.unscheduled[subject.specimen_id] = reasons

        inputs.environments = env.fixture_environments(
            [subject.specimen_id for subject in inputs.subjects],
            # the completion log is this package's, so the
            # waterings are handed to the engine rather than fetched by it.
            waterings=self._logged_waterings(inputs.subjects),
        )
        inputs.last_completed = self._last_completed()
        # One read of the frost engine per generation pass, shared between the
        # tasks it raises and the alerts Morning Rounds serves back with their
        # ``task_id`` filled. Two reads could disagree.
        inputs.frost_alerts = await self.frost_alerts()
        inputs.outlook = env.fixture_outlook()
        return inputs

    def _last_completed(self) -> dict[tuple[str, str], date]:
        out: dict[tuple[str, str], date] = {}
        for row in self._tasks.values():
            if row.get("status") != "done" or not row.get("completed_at"):
                continue
            key = (str(row["specimen_id"]), str(row["task_type"]))
            day = row["completed_at"].date()
            if key not in out or day > out[key]:
                out[key] = day
        return out

    def _logged_waterings(self, subjects: list[Subject]) -> dict[str, env.Waterings]:
        """Every watering somebody actually did, per plant and per day.

        The fact half, read off the completion log this package
        already keeps: an actor, a timestamp and a volume, with no model in it.
        What it relieved is modelled downstream (``tending.environment``) and is
        marked as modelled there.

        Same-day waterings are summed rather than fought over — two half-litres
        an hour apart are a litre, and the deficit does not care which watering
        can carried it. A completion with no ``amount_ml`` is still gathered, at
        zero, because "watered, and nobody said how much" is a different state
        from "not watered" and the reader is owed the difference.
        """
        pots = {
            subject.specimen_id: (
                subject.container_litres if subject.in_container else None
            )
            for subject in subjects
        }
        by_specimen: dict[str, dict[date, float]] = {}
        for row in self._tasks.values():
            if row.get("task_type") != "water" or row.get("status") != "done":
                continue
            at = row.get("completed_at")
            if not isinstance(at, datetime):
                continue
            day = at.date()
            days = by_specimen.setdefault(str(row["specimen_id"]), {})
            days[day] = days.get(day, 0.0) + float(row.get("amount_ml") or 0.0)
        return {
            specimen_id: env.Waterings(
                by_day=days, container_litres=pots.get(specimen_id)
            )
            for specimen_id, days in by_specimen.items()
        }

    async def upsert_tasks(self, rows: list[Record]) -> None:
        """Insert generated tasks, or move the ones that have been rescheduled.

        A task a member has already acted on is never rewritten. A task whose
        due date has moved keeps its id and its ``ics_uid`` and gains a
        ``SEQUENCE``, which is the whole reason the id is not the date.
        """
        for row in rows:
            existing = self._tasks.get(row["id"])
            if existing is None:
                self._tasks[row["id"]] = dict(row)
                self._events.append(_event(row["id"], "created"))
                continue
            if _terminal(str(existing.get("status"))) or existing.get("completed_at"):
                continue
            moved = existing["due_at"] != row["due_at"]
            # A changed event is a new SEQUENCE, not only a moved one: rain
            # settling a task changes its STATUS on the same day, and a client
            # may ignore an update that does not raise the sequence — so may
            # calendar push, which compares nothing else (tending.push).
            changed = any(existing.get(key) != row.get(key) for key in TASK_REGENERATED)
            existing.update({key: row[key] for key in TASK_REGENERATED})
            if changed:
                existing["ics_sequence"] = int(existing.get("ics_sequence") or 0) + 1
            if moved:
                self._events.append(_event(row["id"], "rescheduled"))

    # ------------------------------------------------------------------ tasks

    async def tasks(self, query: TaskQuery) -> list[Record]:
        rows = [dict(row) for row in self._tasks.values()]
        if query.status:
            rows = [row for row in rows if row["status"] == query.status]
        if query.specimen_id:
            rows = [row for row in rows if row["specimen_id"] == query.specimen_id]
        if query.due_before:
            rows = [row for row in rows if row["due_at"] < query.due_before]
        if query.due_after:
            rows = [row for row in rows if row["due_at"] >= query.due_after]
        rows.sort(key=lambda row: (row["due_at"], row["task_type"]))
        return [self._hydrate(row) for row in rows]

    async def task(self, task_id: str) -> Record | None:
        row = self._tasks.get(task_id)
        return self._hydrate(dict(row)) if row else None

    def _hydrate(self, row: Record) -> Record:
        specimen = next(
            (s for s in self._specimens if s["id"] == row["specimen_id"]), None
        )
        row["specimen"] = {
            "id": row["specimen_id"],
            "display_name": (
                fixtures.display_name(specimen) if specimen else "Unnamed specimen"
            ),
            "is_outdoor": bool(specimen.get("is_outdoor")) if specimen else False,
            "thumb_url": None,
        }
        # Not part of the contract's ``Task``; carried on the stored row so a
        # feed's ``location_ids`` filter has something to read.
        row["location_id"] = specimen.get("location_id") if specimen else None
        row["completed_by"] = self._member(row.get("completed_by"))
        return row

    def _member(self, member_id: Any) -> Record | None:
        if not member_id:
            return None
        if isinstance(member_id, dict):
            return member_id
        return next((dict(m) for m in self._members if m["id"] == str(member_id)), None)

    async def complete(
        self, task_ids: list[str], completion: Completion
    ) -> list[Record]:
        """Tick tasks off, log who did it, and retire the cycle they belonged to.

        The history is the point: people want to know when the lemon was last
        fed, so every completion writes a ``task_event`` rather than only
        stamping the task.
        """
        now = datetime.now(UTC)
        completed: list[Record] = []
        for task_id in task_ids:
            row = self._tasks.get(task_id)
            if row is None or _terminal(str(row.get("status"))):
                continue
            row["status"] = "done"
            row["completed_at"] = now
            row["completed_by"] = completion.completed_by or KEEPER_ID
            if completion.amount_ml is not None:
                row["amount_ml"] = completion.amount_ml
            if completion.notes:
                row["notes"] = completion.notes
            row["ics_sequence"] = int(row.get("ics_sequence") or 0) + 1
            data: dict[str, Any] = {}
            if completion.amount_ml is not None:
                data["amount_ml"] = completion.amount_ml
            if completion.new_location_id:
                # The move itself is ``tending.service.complete`` calling
                # The inventory API's write, and it has already happened by the time
                # this runs — a completion that could not move the plant does
                # not become a completion at all. This is the history of it.
                data["new_location_id"] = completion.new_location_id
            self._events.append(
                _event(
                    task_id,
                    "completed",
                    by_member=row["completed_by"],
                    data=data,
                    at=now,
                )
            )
            self._retire_cycle(row, now)
            completed.append(self._hydrate(dict(row)))
        return completed

    def _retire_cycle(self, done: Record, now: datetime) -> None:
        """Cancel what the old cycle had scheduled, so the calendar lets go.

        Completion moves the anchor, so every occurrence counted from the old
        one is now fiction. Left alone they would sit in a subscriber's calendar
        as events for waterings that will never be asked for; cancelled, the
        feed removes them by UID on its next fetch.
        """
        for row in self._tasks.values():
            if row["id"] == done["id"]:
                continue
            if row["specimen_id"] != done["specimen_id"]:
                continue
            if row["task_type"] != done["task_type"]:
                continue
            if _terminal(str(row.get("status"))):
                continue
            row["status"] = "cancelled"
            row["ics_sequence"] = int(row.get("ics_sequence") or 0) + 1
            self._events.append(_event(row["id"], "cancelled", at=now))

    async def withdraw_tasks(self, task_ids: list[str], *, detail: str) -> None:
        """Withdraw tasks nobody is being asked for any more.

        ``satisfied``/``forecast_change``, not deleted and not hidden: the task
        stays on the screen saying the frost passed, and the calendar cancels
        the event by UID because that is the only way a subscribed feed can say
        "this one is gone". ``SEQUENCE`` is bumped so the cancellation is a
        later version of the event the subscriber already holds.
        """
        now = datetime.now(UTC)
        for task_id in task_ids:
            row = self._tasks.get(task_id)
            if row is None or _terminal(str(row.get("status"))):
                continue
            row["status"] = "satisfied"
            row["satisfied_by"] = "forecast_change"
            row["detail"] = detail
            row["ics_sequence"] = int(row.get("ics_sequence") or 0) + 1
            self._events.append(_event(task_id, "satisfied", at=now))

    async def cancel_tasks(self, task_ids: list[str]) -> None:
        """Cancel occurrences counted from an anchor that no longer holds."""
        now = datetime.now(UTC)
        for task_id in task_ids:
            row = self._tasks.get(task_id)
            if row is None or _terminal(str(row.get("status"))):
                continue
            if row.get("completed_at"):
                continue
            row["status"] = "cancelled"
            row["ics_sequence"] = int(row.get("ics_sequence") or 0) + 1
            self._events.append(_event(task_id, "cancelled", at=now))

    async def relocate_specimen(self, specimen_id: str, location_id: str) -> None:
        """Move the plant through the inventory API's write, then follow it here.

        The mock keeps its own copy of the Register — the inventory API's store does too, and
        both were seeded from ``fixtures/`` — so the second line is not
        bookkeeping, it is the difference between one answer and two. Without it
        ``GET /specimens`` would report a lemon on the kitchen table while
        ``GET /tending/rounds`` went on calling it an outdoor plant on the water
        balance. In live mode there is one ``specimen`` table and the inventory API's write is
        the whole story.
        """
        moved = await relocation.relocate(specimen_id, location_id)
        for row in self._specimens:
            if row["id"] == specimen_id:
                row["location_id"] = moved.get("location_id")
                row["is_outdoor"] = bool(moved.get("is_outdoor"))

    # ------------------------------------------------------------- care rules

    async def care_rules(self, specimen_id: str | None = None) -> list[Record]:
        inputs = await self.scheduling_inputs()
        out: list[Record] = []
        for subject in inputs.subjects:
            if specimen_id and subject.specimen_id != specimen_id:
                continue
            for rule in inputs.rules.get(subject.specimen_id, []):
                out.append(_rule_record(rule))
        return out

    async def create_care_rule(self, record: Record) -> Record:
        specimen_id = record.get("specimen_id")
        if specimen_id and not any(s["id"] == specimen_id for s in self._specimens):
            raise UnknownSpecimenError(str(specimen_id))
        stored = dict(record)
        stored.setdefault("id", str(uuid.uuid4()))
        stored.setdefault("created_at", datetime.now(UTC))
        self._rules.append(stored)
        return dict(stored)

    # ------------------------------------------------------------------ feeds

    async def feeds(self) -> list[Record]:
        return [dict(row) for row in self._feeds]

    async def create_feed(self, record: Record) -> Record:
        stored = dict(record)
        stored.setdefault("id", str(uuid.uuid4()))
        # One feed, one token: revoking a phone's subscription must not disturb
        # anybody else's, so no token is ever shared between two feeds.
        stored["token"] = tokens.mint()
        stored.setdefault("push_config", {})
        for key, value in _PUSH_NOTHING_YET.items():
            stored.setdefault(key, copy.deepcopy(value))
        stored.setdefault("created_at", datetime.now(UTC))
        stored.setdefault("last_rendered_at", None)
        stored.setdefault("revoked_at", None)
        self._feeds.append(stored)
        return dict(stored)

    async def revoke_feed(self, feed_id: str) -> Record:
        for row in self._feeds:
            if row["id"] == feed_id:
                row["revoked_at"] = datetime.now(UTC)
                # Rotated as well as marked: a token that stays valid in the
                # database after a revoke is a revoke that did not happen.
                row["token"] = tokens.mint()
                return dict(row)
        raise UnknownFeedError(feed_id)

    async def feed_by_token(self, token: str) -> Record | None:
        for row in self._feeds:
            if row.get("revoked_at"):
                continue
            if tokens.matches(token, str(row["token"])):
                return dict(row)
        return None

    async def touch_feed(self, feed_id: str) -> None:
        for row in self._feeds:
            if row["id"] == feed_id:
                row["last_rendered_at"] = datetime.now(UTC)

    async def feed(self, feed_id: str) -> Record | None:
        for row in self._feeds:
            if row["id"] == feed_id:
                return copy.deepcopy(row)
        return None

    def _live_feed(self, feed_id: str) -> Record | None:
        for row in self._feeds:
            if row["id"] == feed_id and not row.get("revoked_at"):
                return row
        return None

    async def mark_push_owed(self, feed_id: str, since: datetime) -> None:
        row = self._live_feed(feed_id)
        if row is not None and row.get("push_dirty_since") is None:
            row["push_dirty_since"] = since

    async def record_push(self, feed_id: str, outcome: PushOutcome) -> None:
        row = self._live_feed(feed_id)
        if row is None:
            return
        row["push_state"] = copy.deepcopy(outcome.state)
        if outcome.ok_at is None:
            row["push_error"] = outcome.error
            return
        row["push_last_ok_at"] = outcome.ok_at
        row["push_error"] = None
        dirty = row.get("push_dirty_since")
        if dirty is not None and dirty <= outcome.started_at:
            row["push_dirty_since"] = None

    # ------------------------------------------------------------ environment

    async def members(self) -> list[Record]:
        return [dict(row) for row in self._members]

    async def frost_alerts(self) -> list[Record]:
        return env.fixture_frost_alerts()

    async def weather_today(self) -> Record | None:
        return env.fixture_weather_today()


def _event(
    task_id: str,
    kind: str,
    *,
    by_member: str | None = None,
    data: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> Record:
    return {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "at": at or datetime.now(UTC),
        "kind": kind,
        "by_member": by_member,
        "data": data or {},
    }


def _rule_from_record(row: Record) -> Rule:
    return Rule(
        id=str(row["id"]),
        task_type=str(row["task_type"]),
        strategy=str(row.get("strategy") or "interval"),
        base_interval_days=row.get("base_interval_days"),
        amount_ml=row.get("amount_ml"),
        modifiers=dict(row.get("modifiers") or {}),
        months=tuple(row.get("months") or ()),
        enabled=bool(row.get("enabled", True)),
        specimen_id=row.get("specimen_id"),
        species_id=row.get("species_id"),
    )


def _rule_record(rule: Rule) -> Record:
    return {
        "id": rule.id,
        "species_id": rule.species_id,
        "specimen_id": rule.specimen_id,
        "task_type": rule.task_type,
        "strategy": rule.strategy,
        "base_interval_days": rule.base_interval_days,
        "amount_ml": rule.amount_ml,
        "modifiers": rule.modifiers,
        "months": list(rule.months),
        "enabled": rule.enabled,
    }


_INSTANCE: FixtureRepository | None = None


def fixture_repository() -> FixtureRepository:
    """One store per process, so a completion survives the next request."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FixtureRepository()
    return _INSTANCE


def reset_fixture_repository() -> None:
    """Drop the in-memory schedule. For tests, which must not share state."""
    global _INSTANCE
    _INSTANCE = None
