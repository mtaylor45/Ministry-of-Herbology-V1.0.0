"""The live schedule, on Postgres.

Same protocol as the fixture store, so the router and the service are unchanged
between mock and live mode. The shapes differ nowhere, because both serialise
through ``tending.schemas``.

Reads are gathered, not looped: :meth:`scheduling_inputs` fetches every plant,
its species, its cited intervals, its rules, its latest water balance and its
completion history in six statements rather than six per plant. Morning Rounds
generates the whole household's schedule on one request, and a query per plant
would make the home screen slower with every plant added — which is the one
direction this app only moves in.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, null, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tending import environment as env
from tending import relocation, tokens
from tending.defaults import default_rules
from tending.domain import Environment, Rule, Subject, registered_on
from tending.repository import (
    Completion,
    PushOutcome,
    Record,
    SchedulingInputs,
    TaskQuery,
    TendingRepository,
    UnknownFeedError,
    UnknownMemberError,
    UnknownSpecimenError,
)
from tending.tables import (
    TASK_REGENERATED,
    calendar_feed,
    care_rule,
    care_value,
    member,
    site,
    species,
    specimen,
    task,
    task_event,
    water_balance,
)

TERMINAL_STATUSES = ("done", "cancelled", "skipped")


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _display_name(row: Any) -> str:
    """The inventory API's rule, applied to a joined row rather than a fixture dict."""
    if row.nickname:
        return str(row.nickname)
    names = list(row.common_names or [])
    if names:
        return str(names[0]).capitalize()
    if row.accepted_name:
        return str(row.accepted_name)
    return "Unnamed specimen"


class DatabaseRepository(TendingRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------- scheduling

    async def scheduling_inputs(self) -> SchedulingInputs:
        async with self._engine.connect() as connection:
            place = (
                await connection.execute(
                    select(site.c.latitude, site.c.timezone).limit(1)
                )
            ).first()
            latitude = place.latitude if place else None
            timezone = place.timezone if place else None
            plants = (
                await connection.execute(
                    select(
                        specimen.c.id,
                        specimen.c.species_id,
                        specimen.c.nickname,
                        specimen.c.location_id,
                        specimen.c.is_outdoor,
                        specimen.c.in_container,
                        specimen.c.container_litres,
                        specimen.c.acquired_on,
                        specimen.c.water_interval_days_override,
                        specimen.c.created_at,
                        species.c.accepted_name,
                        species.c.common_names,
                        species.c.water_interval_days,
                        species.c.dormancy_months,
                    )
                    .select_from(
                        specimen.outerjoin(
                            species, species.c.id == specimen.c.species_id
                        )
                    )
                    .where(specimen.c.archived_at.is_(None))
                    .order_by(specimen.c.created_at)
                )
            ).all()

            intervals = (
                await connection.execute(
                    select(
                        care_value.c.species_id,
                        care_value.c.value,
                        care_value.c.confidence,
                        care_value.c.source_id,
                        care_value.c.is_user_override,
                    ).where(care_value.c.field == "water_interval_days")
                )
            ).all()

            rules = (
                await connection.execute(select(care_rule).where(care_rule.c.enabled))
            ).all()

            # One row per specimen, the newest day the weather engine has computed.
            latest = (
                await connection.execute(
                    select(water_balance)
                    .distinct(water_balance.c.specimen_id)
                    .order_by(water_balance.c.specimen_id, water_balance.c.day.desc())
                )
            ).all()

            completions = (
                await connection.execute(
                    select(
                        task.c.specimen_id,
                        task.c.task_type,
                        func.max(task.c.completed_at).label("last"),
                    )
                    .where(task.c.status == "done")
                    .group_by(task.c.specimen_id, task.c.task_type)
                )
            ).all()

        cited: dict[str, list[dict[str, Any]]] = {}
        for row in intervals:
            cited.setdefault(str(row.species_id), []).append(
                {
                    "field": "water_interval_days",
                    "value": row.value,
                    "confidence": row.confidence,
                    # A value the household edited is attested by the household,
                    # which is what the design means by an override.
                    "source_id": row.source_id or (row.is_user_override or None),
                }
            )

        stored_rules: dict[str, list[Rule]] = {}
        for row in rules:
            key = str(row.specimen_id or row.species_id)
            stored_rules.setdefault(key, []).append(_rule_from_row(row))

        balances = {str(row.specimen_id): row for row in latest}
        today = datetime.now(UTC).date()

        inputs = SchedulingInputs(latitude=float(latitude or 0.0))
        for plant in plants:
            subject = Subject(
                specimen_id=str(plant.id),
                display_name=_display_name(plant),
                has_nickname=bool(plant.nickname),
                is_outdoor=bool(plant.is_outdoor),
                in_container=bool(plant.in_container),
                location_id=str(plant.location_id) if plant.location_id else None,
                container_litres=plant.container_litres,
                species_id=str(plant.species_id) if plant.species_id else None,
                dormancy_months=tuple(plant.dormancy_months or ()),
                acquired_on=plant.acquired_on,
                added_on=registered_on(plant.created_at, timezone),
            )
            # A per-specimen override is the household's own instruction and
            # outranks whatever the species says.
            fallback = plant.water_interval_days_override or plant.water_interval_days
            care_values = (
                []
                if plant.water_interval_days_override
                else cited.get(str(plant.species_id), [])
            )
            if plant.water_interval_days_override:
                fallback = plant.water_interval_days_override
            derived, reasons = default_rules(subject, care_values, fallback)
            own = stored_rules.get(subject.specimen_id, []) + stored_rules.get(
                subject.species_id or "", []
            )
            inputs.subjects.append(subject)
            inputs.rules[subject.specimen_id] = derived + own
            if reasons and not own:
                inputs.unscheduled[subject.specimen_id] = reasons
            inputs.environments[subject.specimen_id] = (
                env.from_balance_row(balances.get(subject.specimen_id), today=today)
                if subject.is_outdoor
                else Environment()
            )

        for done in completions:
            if done.last is not None:
                inputs.last_completed[(str(done.specimen_id), str(done.task_type))] = (
                    done.last.date()
                )
        # One read of the frost engine per pass, shared between the tasks it
        # raises and the alerts Morning Rounds serves back linked to them.
        inputs.frost_alerts = await self.frost_alerts()
        inputs.outlook = env.fixture_outlook()
        return inputs

    # ------------------------------------------------------------------ tasks

    async def upsert_tasks(self, rows: list[Record]) -> None:
        """Insert new occurrences; move the ones that were rescheduled.

        A task a member has already acted on is never rewritten — the ``WHERE``
        on the conflict clause is what guarantees it, rather than a read-then-write
        that another request could interleave with. A moved occurrence keeps its
        id and its ``ics_uid`` and gains a ``SEQUENCE``.
        """
        if not rows:
            return
        values = [_task_values(row) for row in rows]
        ids = [value["id"] for value in values]

        async with self._engine.begin() as connection:
            # A rule derived from cited care values (tending.defaults) has a
            # stable id and no ``care_rule`` row, and ``task.care_rule_id`` is a
            # foreign key: such a task names no rule rather than failing the
            # whole generation. It failed it, on every live read.
            rule_ids = {v["care_rule_id"] for v in values if v["care_rule_id"]}
            stored_rules = (
                set(
                    (
                        await connection.execute(
                            select(care_rule.c.id).where(care_rule.c.id.in_(rule_ids))
                        )
                    ).scalars()
                )
                if rule_ids
                else set()
            )
            for value in values:
                if value["care_rule_id"] not in stored_rules:
                    value["care_rule_id"] = None
            existing = {
                str(row.id): row.due_at
                for row in (
                    await connection.execute(
                        select(task.c.id, task.c.due_at).where(task.c.id.in_(ids))
                    )
                ).all()
            }
            statement = pg_insert(task).values(values)
            statement = statement.on_conflict_do_update(
                index_elements=[task.c.id],
                set_={
                    **{
                        column: statement.excluded[column]
                        for column in TASK_REGENERATED
                    },
                    # Any change to what the event says is a new SEQUENCE, not
                    # only a move: rain settling a task changes its STATUS on
                    # the same day (see FixtureRepository.upsert_tasks).
                    "ics_sequence": case(
                        (
                            or_(
                                *(
                                    task.c[column].is_distinct_from(
                                        statement.excluded[column]
                                    )
                                    for column in TASK_REGENERATED
                                )
                            ),
                            task.c.ics_sequence + 1,
                        ),
                        else_=task.c.ics_sequence,
                    ),
                    "updated_at": func.now(),
                },
                where=and_(
                    task.c.status.notin_(TERMINAL_STATUSES),
                    task.c.completed_at.is_(None),
                ),
            )
            await connection.execute(statement)

            events = [
                _event_values(value["id"], "created")
                for value in values
                if str(value["id"]) not in existing
            ] + [
                _event_values(value["id"], "rescheduled")
                for value in values
                if str(value["id"]) in existing
                and existing[str(value["id"])] != value["due_at"]
            ]
            if events:
                await connection.execute(pg_insert(task_event), events)

    async def tasks(self, query: TaskQuery) -> list[Record]:
        statement = self._task_select()
        if query.status:
            statement = statement.where(task.c.status == query.status)
        if query.specimen_id:
            statement = statement.where(
                task.c.specimen_id == _as_uuid(query.specimen_id)
            )
        if query.due_before:
            statement = statement.where(task.c.due_at < query.due_before)
        if query.due_after:
            statement = statement.where(task.c.due_at >= query.due_after)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
            members = await self._members(connection)
        return [_task_record(row, members) for row in rows]

    async def task(self, task_id: str) -> Record | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    self._task_select().where(task.c.id == _as_uuid(task_id))
                )
            ).first()
            members = await self._members(connection)
        return _task_record(row, members) if row else None

    def _task_select(self) -> Any:
        return (
            select(
                task,
                specimen.c.nickname,
                specimen.c.is_outdoor,
                specimen.c.location_id,
                species.c.accepted_name,
                species.c.common_names,
            )
            .select_from(
                task.join(specimen, specimen.c.id == task.c.specimen_id).outerjoin(
                    species, species.c.id == specimen.c.species_id
                )
            )
            .order_by(task.c.due_at, task.c.task_type)
        )

    async def _members(self, connection: AsyncConnection) -> dict[str, Record]:
        rows = (await connection.execute(select(member))).all()
        return {
            str(row.id): {
                "id": str(row.id),
                "name": row.name,
                "role": row.role,
                "notify_prefs": row.notify_prefs or {},
            }
            for row in rows
        }

    async def complete(
        self, task_ids: list[str], completion: Completion
    ) -> list[Record]:
        """Tick tasks off, log who did it, and retire the cycle they belonged to."""
        wanted = [uid for uid in (_as_uuid(value) for value in task_ids) if uid]
        if not wanted:
            return []
        now = datetime.now(UTC)
        by_member = _as_uuid(completion.completed_by)

        async with self._engine.begin() as connection:
            if by_member is not None:
                known = await connection.scalar(
                    select(func.count())
                    .select_from(member)
                    .where(member.c.id == by_member)
                )
                if not known:
                    raise UnknownMemberError(str(completion.completed_by))

            open_rows = (
                await connection.execute(
                    select(task.c.id, task.c.specimen_id, task.c.task_type).where(
                        task.c.id.in_(wanted),
                        task.c.status.notin_(TERMINAL_STATUSES),
                    )
                )
            ).all()
            if not open_rows:
                return []
            done_ids = [row.id for row in open_rows]

            patch: dict[str, Any] = {
                "status": "done",
                "completed_at": now,
                "completed_by": by_member,
                "ics_sequence": task.c.ics_sequence + 1,
                "updated_at": now,
            }
            if completion.amount_ml is not None:
                patch["amount_ml"] = completion.amount_ml
            if completion.notes:
                patch["notes"] = completion.notes
            await connection.execute(
                task.update().where(task.c.id.in_(done_ids)).values(**patch)
            )

            data: dict[str, Any] = {}
            if completion.amount_ml is not None:
                data["amount_ml"] = completion.amount_ml
            if completion.new_location_id:
                # The move itself is ``tending.service.complete`` calling
                # The inventory API's write, and it has already happened by the time
                # this runs. This is the history of it.
                data["new_location_id"] = completion.new_location_id
            await connection.execute(
                pg_insert(task_event),
                [
                    _event_values(
                        task_id, "completed", at=now, by_member=by_member, data=data
                    )
                    for task_id in done_ids
                ],
            )

            # Completion moves the anchor, so every occurrence counted from the
            # old one is now fiction. Cancelled rather than deleted: a
            # subscriber's calendar only lets go of an event it is told about.
            retired = (
                await connection.execute(
                    task.update()
                    .where(
                        task.c.id.notin_(done_ids),
                        task.c.status.notin_(TERMINAL_STATUSES),
                        _same_cycle(open_rows),
                    )
                    .values(
                        status="cancelled",
                        ics_sequence=task.c.ics_sequence + 1,
                        updated_at=now,
                    )
                    .returning(task.c.id)
                )
            ).all()
            if retired:
                await connection.execute(
                    pg_insert(task_event),
                    [_event_values(row.id, "cancelled", at=now) for row in retired],
                )

        return [
            row
            for row in await self.tasks(TaskQuery())
            if str(row["id"]) in {str(value) for value in done_ids}
        ]

    async def withdraw_tasks(self, task_ids: list[str], *, detail: str) -> None:
        """Withdraw tasks nobody is being asked for any more.

        ``satisfied``/``forecast_change`` — the contract's own vocabulary for a
        task a change in the weather has taken off the list — with ``SEQUENCE``
        bumped so the subscriber's calendar treats the cancellation as a later
        version of the event it already holds. Never deleted: a feed can only say
        "this is gone" by saying so.

        The ``WHERE`` does the guarding rather than a read-then-write, for the
        same reason ``upsert_tasks`` does: a task somebody completed on a phone
        while this ran must not be reopened as satisfied.
        """
        wanted = [uid for uid in (_as_uuid(value) for value in task_ids) if uid]
        if not wanted:
            return
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            withdrawn = (
                await connection.execute(
                    task.update()
                    .where(
                        task.c.id.in_(wanted),
                        task.c.status == "due",
                        task.c.completed_at.is_(None),
                    )
                    .values(
                        status="satisfied",
                        satisfied_by="forecast_change",
                        detail=detail,
                        ics_sequence=task.c.ics_sequence + 1,
                        updated_at=now,
                    )
                    .returning(task.c.id)
                )
            ).all()
            if withdrawn:
                await connection.execute(
                    pg_insert(task_event),
                    [_event_values(row.id, "satisfied", at=now) for row in withdrawn],
                )

    async def cancel_tasks(self, task_ids: list[str]) -> None:
        """Cancel occurrences counted from an anchor that no longer holds.

        The same move as completion's retirement of the old cycle: cancelled,
        never deleted, ``SEQUENCE`` bumped, so a subscribed calendar lets go of
        the event by UID. Guarded in the ``WHERE`` like every other write here,
        so a task somebody completed meanwhile is left as they left it.
        """
        wanted = [uid for uid in (_as_uuid(value) for value in task_ids) if uid]
        if not wanted:
            return
        now = datetime.now(UTC)
        async with self._engine.begin() as connection:
            cancelled = (
                await connection.execute(
                    task.update()
                    .where(
                        task.c.id.in_(wanted),
                        task.c.status.notin_(TERMINAL_STATUSES),
                        task.c.completed_at.is_(None),
                    )
                    .values(
                        status="cancelled",
                        ics_sequence=task.c.ics_sequence + 1,
                        updated_at=now,
                    )
                    .returning(task.c.id)
                )
            ).all()
            if cancelled:
                await connection.execute(
                    pg_insert(task_event),
                    [_event_values(row.id, "cancelled", at=now) for row in cancelled],
                )

    async def relocate_specimen(self, specimen_id: str, location_id: str) -> None:
        """Move the plant, through the inventory API's own write path.

        One ``specimen`` table, so the inventory API's write is the whole story here: the next
        generation pass reads the new location and the new ``is_outdoor`` from
        the same rows this repository already joins.
        """
        await relocation.relocate(specimen_id, location_id)

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
        values = {
            "id": _as_uuid(record.get("id")) or uuid.uuid4(),
            "species_id": _as_uuid(record.get("species_id")),
            "specimen_id": _as_uuid(record.get("specimen_id")),
            "task_type": record["task_type"],
            "strategy": record.get("strategy") or "interval",
            "base_interval_days": record.get("base_interval_days"),
            "amount_ml": record.get("amount_ml"),
            "modifiers": record.get("modifiers") or {},
            "months": list(record.get("months") or []),
            "enabled": bool(record.get("enabled", True)),
            "created_at": datetime.now(UTC),
        }
        async with self._engine.begin() as connection:
            if values["specimen_id"] is not None:
                known = await connection.scalar(
                    select(func.count())
                    .select_from(specimen)
                    .where(specimen.c.id == values["specimen_id"])
                )
                if not known:
                    raise UnknownSpecimenError(str(record.get("specimen_id")))
            await connection.execute(care_rule.insert().values(**values))
        return {**values, "id": str(values["id"])}

    # ------------------------------------------------------------------ feeds

    async def feeds(self) -> list[Record]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(calendar_feed).order_by(calendar_feed.c.created_at)
                )
            ).all()
        return [dict(row._mapping) for row in rows]

    async def create_feed(self, record: Record) -> Record:
        values = {
            "id": uuid.uuid4(),
            "member_id": _as_uuid(record["member_id"]),
            "name": record["name"],
            # One feed, one token: revoking a phone's subscription must not
            # disturb anybody else's.
            "token": tokens.mint(),
            "filters": record.get("filters") or {},
            "push_target": record.get("push_target") or "none",
            "push_config": {},
            "push_state": {},
            "push_dirty_since": None,
            "push_last_ok_at": None,
            "push_error": None,
            "last_rendered_at": None,
            "revoked_at": None,
            "created_at": datetime.now(UTC),
        }
        async with self._engine.begin() as connection:
            known = await connection.scalar(
                select(func.count())
                .select_from(member)
                .where(member.c.id == values["member_id"])
            )
            if not known:
                raise UnknownMemberError(str(record["member_id"]))
            await connection.execute(calendar_feed.insert().values(**values))
        return {**values, "id": str(values["id"])}

    async def revoke_feed(self, feed_id: str) -> Record:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    calendar_feed.update()
                    .where(calendar_feed.c.id == _as_uuid(feed_id))
                    .values(revoked_at=datetime.now(UTC), token=tokens.mint())
                    .returning(calendar_feed)
                )
            ).first()
        if row is None:
            raise UnknownFeedError(feed_id)
        return dict(row._mapping)

    async def feed_by_token(self, token: str) -> Record | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(calendar_feed).where(
                        calendar_feed.c.token == token,
                        calendar_feed.c.revoked_at.is_(None),
                    )
                )
            ).first()
        return dict(row._mapping) if row else None

    async def touch_feed(self, feed_id: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                calendar_feed.update()
                .where(calendar_feed.c.id == _as_uuid(feed_id))
                .values(last_rendered_at=datetime.now(UTC))
            )

    async def feed(self, feed_id: str) -> Record | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(calendar_feed).where(calendar_feed.c.id == _as_uuid(feed_id))
                )
            ).first()
        return dict(row._mapping) if row else None

    async def mark_push_owed(self, feed_id: str, since: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                calendar_feed.update()
                .where(
                    calendar_feed.c.id == _as_uuid(feed_id),
                    calendar_feed.c.revoked_at.is_(None),
                    calendar_feed.c.push_dirty_since.is_(None),
                )
                .values(push_dirty_since=since)
            )

    async def record_push(self, feed_id: str, outcome: PushOutcome) -> None:
        """One statement, so a revoke between the push and this write wins."""
        values: dict[str, Any] = {"push_state": outcome.state}
        if outcome.ok_at is None:
            values["push_error"] = outcome.error
        else:
            values["push_last_ok_at"] = outcome.ok_at
            values["push_error"] = None
            values["push_dirty_since"] = case(
                (
                    calendar_feed.c.push_dirty_since <= outcome.started_at,
                    null(),
                ),
                else_=calendar_feed.c.push_dirty_since,
            )
        async with self._engine.begin() as connection:
            await connection.execute(
                calendar_feed.update()
                .where(
                    calendar_feed.c.id == _as_uuid(feed_id),
                    calendar_feed.c.revoked_at.is_(None),
                )
                .values(**values)
            )

    async def members(self) -> list[Record]:
        async with self._engine.connect() as connection:
            return list((await self._members(connection)).values())

    # ------------------------------------------------------------ environment

    async def frost_alerts(self) -> list[Record]:
        """The weather engine serves the live frost report; the rounds show what it has.

        The weather engine's live path is not yet wired to a connection (raised in its own an
        earlier release
        pull request and still open), so this reads the same engine the Almanac
        endpoint does rather than growing a second copy of the frost rules here.
        """
        return env.fixture_frost_alerts()

    async def weather_today(self) -> Record | None:
        return env.fixture_weather_today()


def _same_cycle(rows: Sequence[Any]) -> Any:
    """Every not-yet-finished task of the same plant and the same job."""
    from sqlalchemy import or_ as sql_or
    from sqlalchemy import tuple_ as sql_tuple

    pairs = {(row.specimen_id, row.task_type) for row in rows}
    return sql_or(
        *[
            sql_tuple(task.c.specimen_id, task.c.task_type) == pair
            for pair in sorted(pairs, key=str)
        ]
    )


def _task_values(row: Record) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": _as_uuid(row["id"]),
        "specimen_id": _as_uuid(row["specimen_id"]),
        "care_rule_id": _as_uuid(row.get("care_rule_id")),
        "task_type": row["task_type"],
        "due_at": row["due_at"],
        "all_day": bool(row.get("all_day", True)),
        "status": row["status"],
        "satisfied_by": row.get("satisfied_by"),
        "amount_ml": row.get("amount_ml"),
        "priority": row.get("priority") or "normal",
        "title": row["title"],
        "plain_title": row["plain_title"],
        "detail": row.get("detail"),
        "confidence": row.get("confidence"),
        "degraded": bool(row.get("degraded")),
        "degradations": list(row.get("degradations") or []),
        "completed_at": None,
        "completed_by": None,
        "notes": None,
        "ics_uid": row["ics_uid"],
        "ics_sequence": int(row.get("ics_sequence") or 0),
        "created_at": now,
        "updated_at": now,
    }


def _event_values(
    task_id: Any,
    kind: str,
    *,
    at: datetime | None = None,
    by_member: Any = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "task_id": _as_uuid(task_id),
        "at": at or datetime.now(UTC),
        "kind": kind,
        "by_member": by_member,
        "data": data or {},
    }


def _task_record(row: Any, members: dict[str, Record]) -> Record:
    mapping = dict(row._mapping)
    record = {column.name: mapping[column.name] for column in task.c}
    record["specimen"] = {
        "id": str(record["specimen_id"]),
        "display_name": _display_name(row),
        "is_outdoor": bool(row.is_outdoor),
        "thumb_url": None,
    }
    # Not part of the contract's ``Task``; carried so a feed's ``location_ids``
    # filter has something to read.
    record["location_id"] = str(row.location_id) if row.location_id else None
    record["id"] = str(record["id"])
    record["specimen_id"] = str(record["specimen_id"])
    record["completed_by"] = members.get(str(record.get("completed_by") or ""))
    return record


def _rule_from_row(row: Any) -> Rule:
    return Rule(
        id=str(row.id),
        task_type=str(row.task_type),
        strategy=str(row.strategy or "interval"),
        base_interval_days=row.base_interval_days,
        amount_ml=row.amount_ml,
        modifiers=dict(row.modifiers or {}),
        months=tuple(row.months or ()),
        enabled=bool(row.enabled),
        specimen_id=str(row.specimen_id) if row.specimen_id else None,
        species_id=str(row.species_id) if row.species_id else None,
        # A rule the household wrote is the household's own instruction, and
        # needs no citation from the botany worker to be worth following.
        interval_confidence="medium",
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
