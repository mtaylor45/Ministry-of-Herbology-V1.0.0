"""What the tending endpoints do, between the router and the stores.

Generation runs **on read**. Every call that needs today's schedule materialises
it first, and because every task id is a pure function of its occurrence
(``tending.domain.task_id``), running it twice writes nothing the first run did
not. That is a deliberate shape, not a shortcut: the natural home for a nightly
rule evaluation is an Arq job, and ``workers/`` belongs to another parts of the project.
Reaching in to add one would have broken the ownership rule, so the scheduled job is
escalated in the pull request and the API stays correct without it in the
meantime.

The cost is honest and worth writing down: Morning Rounds does the generation
work on the request, which is fine for one household's dozen plants and is not
fine for a thousand. The seam is :func:`generate_tasks` — a worker calls the
same function on a schedule, and these endpoints become pure reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from tending import frost, ics, schemas
from tending.domain import (
    RELOCATION_TASK_TYPES,
    ROUNDS_HOUR,
    Environment,
    FrostWatch,
    Occurrence,
    Rule,
    Subject,
    generate,
    task_row,
)
from tending.repository import (
    Completion,
    Record,
    SchedulingInputs,
    TaskQuery,
    TendingRepository,
)

#: How far ahead the calendar is filled. Far enough that a subscriber sees next
#: month, short enough that a rule edit is reflected within one refresh.
HORIZON_DAYS = 30

#: What a withdrawn frost task says for itself. A person who was asked to carry a
#: tree indoors after dark and then finds the task gone is owed the reason.
WITHDRAWN_DETAIL = (
    "Withdrawn: the frost guard no longer forecasts a night cold enough to need "
    "this. A forecast that changes is the normal case, not a mistake — nothing "
    "here measures the air where the plant stands, so look at the sky "
    "before you trust it."
)

#: How far back a feed carries completed and cancelled events. A cancellation
#: has to stay in the feed long enough for every subscriber to fetch it, or the
#: event it cancels lives on in their calendar forever.
FEED_LOOKBACK_DAYS = 14


class MisplacedRelocationError(ValueError):
    """A completion sent ``new_location_id`` for a task that moves nothing."""

    def __init__(self, task_type: str) -> None:
        super().__init__(
            f"new_location_id is only meaningful when completing a "
            f"bring_indoors or return_outdoors task, not a {task_type} one. "
            "Nothing was moved and nothing was completed."
        )
        self.task_type = task_type


@dataclass(slots=True)
class Generated:
    """What one generation pass produced besides the stored rows.

    A task's certainty is not here: It is stored on the row, in the
    columns migration 004 gave ``task``, and read back with it. It
    was carried here, recomputed on every read, while ``tending.tables`` did
    not declare those columns — which left a completed task, never regenerated,
    with no record of how sure it had been.
    """

    unscheduled: dict[str, list[str]] = field(default_factory=dict)
    #: The ``SpecimenBrief`` for every plant named in ``unscheduled``, so the
    #: rounds can say *which* plant rather than print a uuid.
    briefs: dict[str, Record] = field(default_factory=dict)
    #: The weather engine's frost alerts with ``task_id`` and ``state`` filled in.
    #: They come back from generation rather than from a second read of the
    #: engine so that the alert and the task it names cannot disagree — the
    #: whole of the earlier first deliverable is that these two agree.
    alerts: list[Record] = field(default_factory=list)


def _day_bounds(on: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def generate_tasks(
    repo: TendingRepository, *, today: date | None = None
) -> Generated:
    """Materialise every occurrence due between each plant's anchor and the horizon.

    Returns the plants that could not be scheduled, and why — never an empty
    silence. A plant that drops off the rounds because nobody cited a watering
    interval looks exactly like a plant that needs nothing, and that is the
    failure mode the design exists to name in the weather engines.
    """
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC)
    inputs = await repo.scheduling_inputs()
    watches = frost.watches(inputs.frost_alerts)
    unreadable = [
        alert for alert in inputs.frost_alerts if frost.watch_from_alert(alert) is None
    ]

    rows: list[Record] = []
    superseded: set[str] = set()
    unscheduled = dict(inputs.unscheduled)
    for alert in unreadable:
        # An alert this package could not read raises no task, and the plant is
        # named for it rather than quietly left out.
        specimen_id = str((alert.get("specimen") or {}).get("id") or "")
        if specimen_id:
            unscheduled.setdefault(specimen_id, []).append(
                frost.unreadable_reason(alert)
            )
    for subject in inputs.subjects:
        frost_occurrences, frost_reasons = _frost_work(
            subject, watches.get(subject.specimen_id), inputs=inputs, today=today
        )
        rows.extend(task_row(occurrence) for occurrence in frost_occurrences)
        if frost_reasons:
            unscheduled.setdefault(subject.specimen_id, []).extend(frost_reasons)

        rules = inputs.rules.get(subject.specimen_id) or []
        if not rules:
            continue
        environment = inputs.environments.get(subject.specimen_id, Environment())
        last_completed = {
            task_type: day
            for (specimen_id, task_type), day in inputs.last_completed.items()
            if specimen_id == subject.specimen_id
        }
        occurrences = generate(
            subject,
            rules,
            today=today,
            horizon_days=HORIZON_DAYS,
            latitude=inputs.latitude,
            environments={"water": environment},
            last_completed=last_completed,
        )
        rows.extend(task_row(occurrence) for occurrence in occurrences)
        superseded.update(
            _counted_from_the_epoch(
                subject,
                rules,
                occurrences,
                today=today,
                latitude=inputs.latitude,
                environment=environment,
                last_completed=last_completed,
            )
        )
        if not occurrences and subject.is_dormant(today):
            months = ", ".join(str(month) for month in sorted(subject.dormancy_months))
            unscheduled.setdefault(subject.specimen_id, []).append(
                f"Dormant this month (months {months}). Its care rule suspends "
                "watering rather than stretching it, so nothing is scheduled "
                "until it wakes."
            )

    await repo.upsert_tasks(rows)
    stored = await _withdraw_stale_frost_tasks(repo, rows, now=now)
    stored = await _cancel_superseded(
        repo, stored, superseded - {r["id"] for r in rows}
    )
    return Generated(
        unscheduled=unscheduled,
        briefs=_briefs(inputs, unscheduled),
        alerts=frost.link_alerts(inputs.frost_alerts, stored),
    )


def _briefs(
    inputs: SchedulingInputs, unscheduled: dict[str, list[str]]
) -> dict[str, Record]:
    """A ``SpecimenBrief`` for each unscheduled plant, from what generation read.

    The same shape, field for field, as the weather engine's ``unassessable`` on
    ``/almanac/frost`` (``almanac.service._brief_from_context``), and built the
    same way: from the inputs that produced the verdict, not a second lookup. A
    plant the scheduler could not schedule must not then go unnamed because a
    lookup for its name missed. The one plant this pass may know only by id is
    one named by a frost alert it could not read; the weather engine's own brief on that alert
    names it, and failing that it is "Unnamed specimen", as the weather engine serves it.
    """
    subjects = {subject.specimen_id: subject for subject in inputs.subjects}
    alerted = {
        str((alert.get("specimen") or {}).get("id") or ""): alert.get("specimen") or {}
        for alert in inputs.frost_alerts
    }
    out: dict[str, Record] = {}
    for specimen_id in unscheduled:
        subject = subjects.get(specimen_id)
        if subject is not None:
            out[specimen_id] = {
                "id": specimen_id,
                "display_name": subject.display_name or "Unnamed specimen",
                "is_outdoor": subject.is_outdoor,
                "thumb_url": subject.thumb_url,
            }
            continue
        known = alerted.get(specimen_id, {})
        out[specimen_id] = {
            "id": specimen_id,
            "display_name": known.get("display_name") or "Unnamed specimen",
            "is_outdoor": bool(known.get("is_outdoor", True)),
            "thumb_url": known.get("thumb_url"),
        }
    return out


def _counted_from_the_epoch(
    subject: Subject,
    rules: list[Rule],
    occurrences: list[Occurrence],
    *,
    today: date,
    latitude: float,
    environment: Environment,
    last_completed: dict[str, date],
) -> set[str]:
    """Ids this plant's schedule carried moved its anchor.

    A plant with no acquired date and no completion was counted from
    ``EPOCH`` (2024-01-01); it is now counted from the day it was registered
    (``tending.domain.anchor_for``). The anchor is part of every task's
    identity, so the plants that change are exactly the plants that would
    otherwise keep the old schedule's open tasks — a watering some 640 days
    overdue, and its futures — beside the new one, in the rounds and in every
    subscribed calendar. These are the ids generation would have produced under
    the old anchor today; the caller cancels the ones actually stored.

    Empty for every other plant, which is every plant whose anchor did not move:
    one with an acquired date, one with a completion for the task type, or one
    with no registration date to anchor on.
    """
    if subject.acquired_on is not None or subject.added_on is None:
        return set()
    before = generate(
        replace(subject, added_on=None),
        rules,
        today=today,
        horizon_days=HORIZON_DAYS,
        latitude=latitude,
        environments={"water": environment},
        last_completed=last_completed,
    )
    now = {occurrence.task_id for occurrence in occurrences}
    return {occurrence.task_id for occurrence in before} - now


async def _cancel_superseded(
    repo: TendingRepository, stored: dict[str, Record], superseded: set[str]
) -> dict[str, Record]:
    """Cancel the open tasks :func:`_counted_from_the_epoch` found stored.

    Filtered against what is stored first, so a pass with nothing to cancel —
    every pass after the first, and every pass on the fixture household —
    writes nothing.
    """
    open_ids = sorted(
        task_id
        for task_id in superseded
        if task_id in stored
        and stored[task_id].get("status") not in {"done", "cancelled", "skipped"}
        and not stored[task_id].get("completed_at")
    )
    if not open_ids:
        return stored
    await repo.cancel_tasks(open_ids)
    for task_id in open_ids:
        stored[task_id] = {
            **stored[task_id],
            "status": "cancelled",
            "ics_sequence": int(stored[task_id].get("ics_sequence") or 0) + 1,
        }
    return stored


def _frost_work(
    subject: Subject,
    watch: FrostWatch | None,
    *,
    inputs: SchedulingInputs,
    today: date,
) -> tuple[list[Occurrence], list[str]]:
    """The frost guard's occurrences for one plant, and the reasons for the gaps.

    Two jobs come out of one alert: get the plant out of the cold, and get it
    back out afterwards. The second only exists for a plant that is actually
    inside, which is what a completed ``bring_indoors`` with no later
    ``return_outdoors`` means — telling somebody to put back a plant they never
    brought in is how a list of tasks stops being read.
    """
    occurrences: list[Occurrence] = []
    reasons: list[str] = []
    sheltered_on = inputs.last_completed.get((subject.specimen_id, "bring_indoors"))
    returned_on = inputs.last_completed.get((subject.specimen_id, "return_outdoors"))
    is_indoors = sheltered_on is not None and (
        returned_on is None or returned_on < sheltered_on
    )

    if watch is None:
        if is_indoors and sheltered_on is not None:
            reasons.append(frost.sheltered_reason(sheltered_on))
        return occurrences, reasons

    guard, reason = frost.guard_task(
        subject, watch, today=today, outlook=inputs.outlook
    )
    if guard is not None:
        occurrences.append(guard)
    if reason:
        reasons.append(reason)

    if is_indoors and sheltered_on is not None:
        back, reason = frost.return_task(
            subject, watch, outlook=inputs.outlook, sheltered_on=sheltered_on
        )
        if back is not None:
            occurrences.append(back)
        if reason:
            reasons.append(reason)
    return occurrences, reasons


async def _withdraw_stale_frost_tasks(
    repo: TendingRepository, rows: list[Record], *, now: datetime
) -> dict[str, Record]:
    """Let go of frost tasks the guard has stopped asking for.

    Returns every stored task by id, with the withdrawn ones' statuses as they
    now are — the alerts are linked against this, so a card cannot say "open"
    over a task this pass has just withdrawn.

    One extra read of the schedule per generation, which is the same bargain the
    module docstring already makes about generation running on read: honest, fine
    for a household, and fixed in one place (:func:`generate_tasks`) the day a
    worker takes generation off the request.
    """
    stored = {str(row["id"]): row for row in await repo.tasks(TaskQuery())}
    generated_ids = {str(row["id"]) for row in rows}
    stale = [
        task_id
        for task_id, row in stored.items()
        if frost.withdrawable(row, generated_ids=generated_ids, now=now)
    ]
    if not stale:
        return stored
    await repo.withdraw_tasks(stale, detail=WITHDRAWN_DETAIL)
    for task_id in stale:
        stored[task_id] = {
            **stored[task_id],
            "status": frost.WITHDRAWN_STATUS,
            "satisfied_by": frost.WITHDRAWN_BY,
            "detail": WITHDRAWN_DETAIL,
            "ics_sequence": int(stored[task_id].get("ics_sequence") or 0) + 1,
        }
    return stored


async def morning_rounds(
    repo: TendingRepository, on: date | None = None
) -> dict[str, Any]:
    """``GET /tending/rounds`` — today, grouped the way the screen reads it."""
    day = on or datetime.now(UTC).date()
    generated = await generate_tasks(repo, today=day)
    start, end = _day_bounds(day)

    rows = [
        row
        for row in await repo.tasks(TaskQuery(due_before=_timed_horizon(day)))
        if _belongs_to_the_rounds(row, end=end)
    ]
    due = [schemas.task_out(row) for row in rows if row["status"] == "due"]
    satisfied = [
        schemas.task_out(row)
        for row in rows
        if row["status"] == "satisfied" and row["due_at"] >= start
    ]

    return {
        "date": day.isoformat(),
        "greeting": greeting(len(due)),
        "due": due,
        "satisfied": satisfied,
        # The weather engine's alerts, with the task each one raised named on it. Not a second
        # read of the engine: the same read generation used, so the alert and the
        # task cannot describe different nights.
        "alerts": generated.alerts,
        "weather": await repo.weather_today(),
        # Additive, and the point of the exercise: the plants this round could
        # not speak for, each with the reason. Requested of the maintainers in the
        # pull request alongside the certainty fields on ``Task``.
        "unscheduled": [
            {
                "specimen_id": specimen_id,
                "specimen": generated.briefs[specimen_id],
                "reason": reason,
            }
            for specimen_id, reasons in sorted(generated.unscheduled.items())
            for reason in reasons
        ],
    }


def _timed_horizon(day: date) -> datetime:
    """How far past midnight the rounds look, for a task due *by* a moment.

    At this site sunset falls after midnight UTC, so the deadline for tonight's
    freeze carries tomorrow's UTC date: filtering the rounds at the end of the
    day would show a bring-indoors task for the first time on the morning after
    the night it existed to prevent. The rounds therefore reach as far as the
    *next* rounds — a timed task nobody will see again before its deadline
    belongs in today's list, and nothing further out does.
    """
    return datetime.combine(day + timedelta(days=1), time(hour=ROUNDS_HOUR), tzinfo=UTC)


def _belongs_to_the_rounds(row: Record, *, end: datetime) -> bool:
    """Everything due by the end of today, plus tonight's timed work."""
    if row["due_at"] < end:
        return True
    return not bool(row.get("all_day", True))


def greeting(due_count: int) -> str:
    """Themed, and plain in the same breath — the original-theme rule applies to prose too."""
    if due_count == 0:
        return "Good morning. The greenhouse is settled — nothing is due today."
    plants = "1 task is" if due_count == 1 else f"{due_count} tasks are"
    return f"Good morning. The greenhouse is stirring — {plants} due today."


async def list_tasks(repo: TendingRepository, query: TaskQuery) -> list[dict[str, Any]]:
    await generate_tasks(repo)
    return [schemas.task_out(row) for row in await repo.tasks(query)]


async def complete(
    repo: TendingRepository, task_ids: list[str], completion: Completion
) -> list[dict[str, Any]]:
    """One tap or a whole batch — the same path, so they cannot diverge.

    Morning Rounds sends a batch; the Tending facet sends one. A batch that took
    a different route would eventually log its events differently, and the
    history is the feature.

    **The move happens before the completion, and that order is the point.** A
    completion that reported success while leaving the plant outdoors in a freeze
    is the failure an earlier release exists to close, so a relocation that cannot be performed —
    an unknown location — refuses the whole request and ticks nothing off.
    """
    await generate_tasks(repo)
    if completion.new_location_id:
        await _relocate(repo, task_ids, completion.new_location_id)
    rows = await repo.complete(task_ids, completion)
    return [schemas.task_out(row) for row in rows]


async def _relocate(
    repo: TendingRepository, task_ids: list[str], location_id: str
) -> None:
    """Move the plants whose tasks are about moving plants.

    ``new_location_id`` is contracted as "set when completing a bring_indoors
    task", so a completion of anything else that carries one is a client bug and
    is refused rather than obeyed or silently dropped: obeying it would move a
    plant on the strength of a watering, and dropping it would lose a move
    somebody thought they had made.
    """
    for task_id in task_ids:
        row = await repo.task(task_id)
        if row is None:
            continue
        if row["task_type"] not in RELOCATION_TASK_TYPES:
            raise MisplacedRelocationError(str(row["task_type"]))
        if row.get("status") in {"done", "cancelled", "skipped"}:
            continue
        await repo.relocate_specimen(str(row["specimen_id"]), location_id)


# ----------------------------------------------------------------- feed


def matches_filters(row: Record, filters: dict[str, Any]) -> bool:
    """A feed's filter set, applied to one stored task.

    An absent filter means "everything"; an empty list means the same, because a
    feed whose ``task_types: []`` rendered nothing would look broken rather than
    unfiltered.

    Applied to the stored row rather than the serialised one: the contract's
    ``SpecimenBrief`` carries no location, and inventing a field on the response
    so that a filter could read it would be a contract change by the back door.
    """
    outdoor = filters.get("outdoor")
    specimen = row.get("specimen") or {}
    if outdoor is not None and bool(specimen.get("is_outdoor")) is not bool(outdoor):
        return False
    task_types = filters.get("task_types") or []
    if task_types and row["task_type"] not in task_types:
        return False
    location_ids = filters.get("location_ids") or []
    return not (location_ids and row.get("location_id") not in location_ids)


async def render_feed(
    repo: TendingRepository, token: str, *, base_url: str, now: datetime | None = None
) -> str | None:
    """The ICS document for one token, or ``None`` if the token is not a feed.

    ``None`` covers both "no such feed" and "revoked", and the router answers
    404 to both without distinguishing them: telling an unauthenticated caller
    that a token *used* to work is telling them the token was real.
    """
    feed = await repo.feed_by_token(token)
    if feed is None:
        return None

    now = now or datetime.now(UTC)
    await generate_tasks(repo, today=now.date())
    events = feed_events(await window_tasks(repo, now), feed)
    document = ics.render(
        events,
        name=f"The Ministry of Herbology — {feed['name']}",
        base_url=base_url,
        now=now,
    )
    await repo.touch_feed(str(feed["id"]))
    return document


async def window_tasks(repo: TendingRepository, now: datetime) -> list[Record]:
    """Every stored task a feed could carry at ``now``, before its filters.

    One read shared by every feed, and the one place the window is decided, so
    a subscribed calendar (:func:`render_feed`) and a pushed one
    (``tending.push``) are cut from the same rows.
    """
    horizon = now + timedelta(days=HORIZON_DAYS + 1)
    since = now - timedelta(days=FEED_LOOKBACK_DAYS)
    return await repo.tasks(TaskQuery(due_after=since, due_before=horizon))


def feed_events(rows: list[Record], feed: Record) -> list[dict[str, Any]]:
    """One feed's tasks, shaped for :mod:`tending.ics`, one per UID.

    The first row for a UID wins, as it does in :func:`tending.ics.render`:
    two events with one UID is the duplicate the whole scheme exists to
    prevent, and both routes into a calendar must keep the same one.
    """
    filters = feed.get("filters") or {}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not matches_filters(row, filters):
            continue
        event = schemas.ics_task(row)
        uid = str(event["ics_uid"])
        if uid in seen:
            continue
        seen.add(uid)
        out.append(event)
    return out
