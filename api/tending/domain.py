"""The scheduling engine: care rules in, dated occurrences out.

Nothing in this module reads a database, a fixture file or the clock. Every
input arrives as an argument, which is what lets the season, dormancy and
weather behaviour be tested against dates that are not today.

Three things here are load-bearing and are the reason the module exists at all.

**Identity is not the due date.** A task's identity is the *occurrence* a rule
generates — the nth cycle since an anchor — and not the day it currently sits
on. Stretch a winter watering by four days and it is the same occurrence, moved;
it must update the calendar event in place and bump ``SEQUENCE``. Deriving the
UID from the due date, as the earlier mock did, turns every reschedule into a second
event in somebody's calendar, and there is no way to take those back once a
feed is subscribed.

**The anchor is the last time the job was actually done.** Completion moves the
anchor, which retires the outstanding occurrence and starts a fresh cycle with
fresh identities. That is why a completed task is never regenerated and why
watering twice in a week does not leave a stale event behind.

**Dormancy suspends; it does not stretch.** A dormant plant is not on a longer
interval, it is off the schedule until it wakes. Stretching would still put a
watering in the calendar, in the month the plant least wants one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tending.titles import TASK_TYPES, titles_for

#: Deterministic task ids. Regenerating the schedule must land on the same
#: uuid for the same occurrence, or every read would mint duplicate rows and
#: every duplicate row would be a duplicate calendar event.
TASK_NAMESPACE = uuid.UUID("2f4d9d8a-1c4c-4f0f-9f39-1a0b0c5e7d31")

#: The ICS UID suffix. It is a constant and must stay one: a UID that changes
#: is a new event to every calendar client alive.
ICS_DOMAIN = "herbology"

#: Occurrences are generated no further than this, whatever the rule says. A
#: misconfigured one-day interval over a long horizon should be dull, not a
#: denial of service.
MAX_OCCURRENCES = 120

#: The anchor for a plant with no completion history and no acquisition date.
#: Fixed, so identities do not move when the code is redeployed.
EPOCH = date(2024, 1, 1)

#: Routine all-day tasks are posted at this hour UTC so that ``due_at`` sorts
#: sensibly and a client rendering a time gets a morning rather than midnight.
ROUNDS_HOUR = 9

#: Task types the plan treats as urgent and timed rather than all-day: they are
#: due *by* a moment (sunset before a cold night), not on a day.
TIMED_TASK_TYPES = frozenset({"bring_indoors", "cover"})

#: Everything the frost guard owns. None of these is a recurrence: each one
#: answers a single night, so none is produced by :func:`generate` — they are
#: built in ``tending.frost`` from the weather engine's alerts and withdrawn when E
#: stops raising them. Grouped here because the withdrawal rule needs to know
#: which stored tasks are the frost guard's to withdraw.
FROST_TASK_TYPES = frozenset({"bring_indoors", "cover", "return_outdoors"})

#: The two frost tasks that *move* a plant, and therefore accept a
#: ``new_location_id`` on completion. ``cover`` protects a plant where it
#: stands, so a cover completion that named a new location would be a client
#: bug rather than a relocation.
RELOCATION_TASK_TYPES = frozenset({"bring_indoors", "return_outdoors"})

#: Index 0 is reserved for the single state-driven occurrence a strategy such as
#: ``water_balance`` produces — "the outstanding one since the anchor". Scheduled
#: cycles are 1, 2, 3… so the two can never collide.
OUTSTANDING_INDEX = 0

SUSPENDED = "suspended"


# --------------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class Subject:
    """One plant, as the scheduler needs it. Built by the stores, never here."""

    specimen_id: str
    display_name: str
    has_nickname: bool
    is_outdoor: bool
    in_container: bool
    location_id: str | None = None
    container_litres: float | None = None
    species_id: str | None = None
    dormancy_months: tuple[int, ...] = ()
    acquired_on: date | None = None
    thumb_url: str | None = None
    #: The day the plant was entered in the Register (``specimen.created_at``),
    #: as a date in the site's timezone. The anchor for a plant nobody gave an
    #: acquired date — see :func:`anchor_for`.
    added_on: date | None = None

    def is_dormant(self, on: date) -> bool:
        return on.month in self.dormancy_months


@dataclass(frozen=True, slots=True)
class Caveat:
    """One reason a task is worth less than it looks.

    The same shape as the weather engine's ``Degradation`` on purpose: a
    task built on a degraded input carries the weather engine's reasons through unchanged and
    adds its own beside them, rather than laundering either into a clean
    instruction.
    """

    code: str
    detail: str
    caps_at: str = "medium"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "caps_at": self.caps_at}


@dataclass(frozen=True, slots=True)
class Rule:
    """A ``care_rule`` row, as the frozen schema declares it."""

    id: str
    task_type: str
    strategy: str = "interval"
    base_interval_days: int | None = None
    amount_ml: int | None = None
    modifiers: dict[str, Any] = field(default_factory=dict)
    months: tuple[int, ...] = ()
    enabled: bool = True
    specimen_id: str | None = None
    species_id: str | None = None

    #: Not columns. What the interval this rule carries is actually worth, and
    #: why — the design travelling with the number instead of behind it. A rule
    #: derived from an uncited care value says ``unknown`` here, and every task
    #: it generates says so where a reader will see it.
    interval_confidence: str = "medium"
    interval_caveats: tuple[Caveat, ...] = ()

    @property
    def scope(self) -> str:
        """Specimen rules beat species rules for the same task type."""
        return "specimen" if self.specimen_id else "species"


#: the design four levels, best to worst.
CONFIDENCE_ORDER = ("high", "medium", "low", "unknown")


def weakest(*confidences: str) -> str:
    """The least confident of several claims, which is what a chain is worth."""
    ranks = [
        (
            CONFIDENCE_ORDER.index(c)
            if c in CONFIDENCE_ORDER
            else len(CONFIDENCE_ORDER) - 1
        )
        for c in confidences
        if c
    ]
    return CONFIDENCE_ORDER[max(ranks)] if ranks else "unknown"


@dataclass(frozen=True, slots=True)
class Environment:
    """What the world says about one plant today, from the weather engine.

    Everything here is *consumed*. This package computes no deficit, no ET₀ and
    no rain total; the design put the confidence on the weather engine's answer and this carries it
    through. ``balance_status`` is the weather engine's word — ``due``, ``satisfied`` or ``ok`` —
    and ``satisfied_by`` is the weather engine's attribution for it.
    """

    applies: bool = False
    balance_status: str | None = None
    satisfied_by: str | None = None
    is_due: bool = False
    confidence: str = "unknown"
    degradations: tuple[Caveat, ...] = ()
    #: Newest day the balance actually covers. A series that stops short of the
    #: day it is being used to schedule is stale, and says so.
    newest_day: date | None = None
    #: Indoor relative humidity, when the hub has a reading for the room.
    #: ``None`` today for every plant, and the modifier simply does not apply.
    humidity_pct: float | None = None


@dataclass(frozen=True, slots=True)
class FrostWatch:
    """One open frost alert, as the scheduler needs it — the weather engine's answer.

    Consumed, never computed. This package holds no species minimum, no frost
    margin and no lookahead: The weather engine's engine states all three, and a second copy of
    them here would be the failure the design names, built on purpose. What G adds
    is the *task* the alert justifies, and the judgement about when the plant may
    go back out.

    Note what this is not. A frost alert is a *forecast*. Every task built from one says so in words
    on ``detail``,
    which is why :attr:`sentence` lives here rather than in a template.
    """

    alert_id: str
    specimen_id: str
    night_of: date
    forecast_low_c: float
    threshold_c: float
    action: str
    advisory: str | None = None
    confidence: str = "unknown"
    degradations: tuple[Caveat, ...] = ()
    state: str = "open"

    @property
    def is_actionable(self) -> bool:
        """``monitor`` is deliberately not a task. See ``tending.frost``."""
        return self.action in TIMED_TASK_TYPES

    @property
    def eve(self) -> date:
        """The day whose evening the plant has to be dealt with by.

        A frost task is due *by sunset before* the cold night, so the day it is
        done on is the day before the night it is about.
        """
        return self.night_of - timedelta(days=1)

    @property
    def sentence(self) -> str:
        """The forecast, in a sentence, for ``task.detail``.

        Stated as a forecast and attributed to the night it names. A reader who
        is being asked to carry a tree indoors after dark is owed the number
        that asked it of them, and owed the fact that it is a prediction.
        """
        advisory = f" {self.advisory}." if self.advisory else ""
        return (
            f"Forecast, not a measurement: the night of "
            f"{self.night_of.isoformat()} is predicted to fall to "
            f"{self.forecast_low_c:g} °C, against this plant's "
            f"{self.threshold_c:g} °C threshold.{advisory} Nothing here measures "
            "the air where the plant stands."
        )


@dataclass(frozen=True, slots=True)
class Outlook:
    """The nights ahead, as the weather engine's forecast states them.

    Two readings of one forecast: the low for each night, and the sunset that
    ends each day. Neither is computed here — a sunset this package worked out
    for itself would be a second, quieter copy of an ephemeris, and a night's low
    is the weather engine's to state.
    """

    lows_c: dict[date, float] = field(default_factory=dict)
    sunsets: dict[date, datetime] = field(default_factory=dict)

    def nights_above(self, threshold_c: float, *, after: date, run: int) -> date | None:
        """The day a run of ``run`` consecutive nights above ``threshold_c`` ends.

        ``None`` when the forecast does not contain one. Consecutive means
        consecutive *days*, so a gap in the forecast breaks the run rather than
        being read through: three mild nights with an unknown one among them are
        not three mild nights.
        """
        streak = 0
        for day in sorted(self.lows_c):
            if day <= after:
                continue
            if streak and (day - timedelta(days=1)) not in self.lows_c:
                streak = 0
            streak = streak + 1 if self.lows_c[day] > threshold_c else 0
            if streak >= run:
                return day
        return None


# -------------------------------------------------------------------- seasons

#: Meteorological seasons, northern hemisphere. Shifted six months south.
_NORTHERN_SEASONS = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}


def season_for(on: date, latitude: float) -> str:
    """The season at the site, which is not the season in the code's timezone.

    A southern-hemisphere deployment watering on a northern winter multiplier
    would dial care back in the exact month the plant needs most.
    """
    month = on.month if latitude >= 0 else (on.month + 6 - 1) % 12 + 1
    return _NORTHERN_SEASONS[month]


# ------------------------------------------------------------------ intervals


def _as_factor(value: Any) -> float | None:
    """A modifier is a multiplier or it is nothing. Never a guess."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    factor = float(value)
    return factor if factor > 0 else None


def effective_interval(
    rule: Rule,
    *,
    season: str,
    dormant: bool,
    humidity_pct: float | None = None,
) -> int | str | None:
    """The rule's interval with its own modifiers applied.

    Returns the number of days, :data:`SUSPENDED` while a dormancy rule holds,
    or ``None`` when the rule declares no interval at all.

    Only modifiers the rule itself carries are applied. There is no ambient
    table of "what plants like in winter" here and there must not be one: The
    no-invented-plant-facts rule
    forbids inventing a plant fact, and a multiplier nobody configured is
    exactly that, wearing arithmetic.
    """
    base = rule.base_interval_days
    if base is None or base <= 0:
        return None

    modifiers = rule.modifiers or {}

    if dormant:
        dormancy = modifiers.get("dormancy")
        if dormancy == "suspend":
            return SUSPENDED
        factor = _as_factor(dormancy)
        if factor is not None:
            base = max(1, round(base * factor))

    seasonal = modifiers.get("season")
    if isinstance(seasonal, dict):
        factor = _as_factor(seasonal.get(season))
        if factor is not None:
            base = max(1, round(base * factor))

    if humidity_pct is not None:
        low = modifiers.get("humidity_low")
        threshold = _as_factor(modifiers.get("humidity_low_below_pct")) or 40.0
        factor = _as_factor(low)
        if factor is not None and humidity_pct < threshold:
            base = max(1, round(base * factor))

    return max(1, int(base))


# ------------------------------------------------------------------ occurrences


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One dated instance of a rule, before it becomes a stored task."""

    rule: Rule
    subject: Subject
    index: int
    anchor: date
    due_on: date
    status: str = "due"
    satisfied_by: str | None = None
    amount_ml: int | None = None
    confidence: str = "high"
    caveats: tuple[Caveat, ...] = ()
    #: What this occurrence has to say for itself beyond its caveats, and the
    #: first thing on ``task.detail``. A frost task states the forecast it rests
    #: on here: it is not a doubt about the answer (that is a ``Caveat``), it is
    #: the reason the answer exists, and the reader is owed both.
    detail: str | None = None
    #: The exact moment a timed task is due by, when something knows it. A frost
    #: task is due by the sunset the weather engine states, which is a fact about the
    #: sky that this package reads rather than computes — so it arrives here
    #: already resolved instead of being re-derived at serialisation time.
    deadline: datetime | None = None

    @property
    def priority(self) -> str:
        """Derived, not passed. A frost task is urgent wherever it was built."""
        return "urgent" if self.rule.task_type in TIMED_TASK_TYPES else "normal"

    @property
    def task_id(self) -> str:
        return str(
            task_id(self.subject.specimen_id, self.rule, self.anchor, self.index)
        )

    @property
    def all_day(self) -> bool:
        return self.rule.task_type not in TIMED_TASK_TYPES


def task_id(specimen_id: str, rule: Rule, anchor: date, index: int) -> uuid.UUID:
    """The stable identity of one occurrence.

    Deliberately free of the due date: a rescheduled occurrence keeps this id,
    keeps its ``ics_uid``, and updates the calendar event instead of adding one.
    """
    key = f"{specimen_id}|{rule.task_type}|{rule.id}|{anchor.isoformat()}|{index}"
    return uuid.uuid5(TASK_NAMESPACE, key)


def ics_uid(task_id_value: str) -> str:
    """The calendar identity of a task. Never derived from the due date.

    ``task-`` prefixed so that other event kinds this feed may carry later
    (a frost window, a site-wide note) cannot collide with a task's UID.
    """
    return f"task-{task_id_value}@{ICS_DOMAIN}"


def anchor_for(subject: Subject, last_completed_on: date | None) -> date:
    """Where this plant's cycle starts counting.

    The last time the job was actually done, else the day the plant arrived,
    else the day it was entered in the Register, else a fixed epoch — never
    "today", which would make every regeneration mint new identities and every
    regeneration a fresh pile of calendar events.

    ``added_on`` is the maintainer's call of 2 Oct: a plant added today
    with no acquired date anchored on :data:`EPOCH` and arrived some 640 days
    overdue, its first task telling a person to water a plant they watered
    that morning. The day it was registered is the truest arrival date the
    Ministry has, and it never moves, so the identities stay stable. ``EPOCH``
    is left only for a row that has neither — one the API did not create.
    """
    return last_completed_on or subject.acquired_on or subject.added_on or EPOCH


def registered_on(created_at: datetime | None, timezone: str | None) -> date | None:
    """``specimen.created_at`` as the calendar day it was at the site.

    Stored UTC; a plant entered at 9 pm in Indianapolis was entered that day,
    not the next one. An unknown or missing zone falls back to UTC rather than
    refusing — the anchor is a starting count, and a day either way is not
    worth leaving the plant unscheduled for.
    """
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    try:
        zone: tzinfo = ZoneInfo(timezone) if timezone else UTC
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return created_at.astimezone(zone).date()


def occurrence_dates(
    anchor: date,
    interval_days: int,
    *,
    today: date,
    until: date,
    months: tuple[int, ...] = (),
    limit: int = MAX_OCCURRENCES,
) -> list[tuple[int, date]]:
    """``(index, date)`` for the cycles worth materialising, anchor-numbered.

    Two rules, and the second one is easy to get wrong.

    An occurrence whose month the rule excludes is skipped *without* renumbering
    the ones after it. Renumbering would shift every later identity the moment a
    rule gained a month restriction, which is the same duplicate-event failure
    by a different route.

    And **only the most recent missed occurrence is emitted**, not every one
    since the plant arrived. A lemon acquired in 2022 on a three-week interval
    has had eighty waterings fall due; it is not eighty jobs behind, it is one.
    Numbering still counts from the anchor, so the identity of the outstanding
    occurrence is the same whether it is a day late or a fortnight.

    **The walk starts near today, not at the first cycle ever**, and that is a
    fix rather than an optimisation. Counting up from index 1 spent the limit
    before it arrived: a plant acquired in 2022 on a two-day interval had its
    120th cycle in August 2022, so the loop stopped there and the plant was
    served one watering dated four years ago and *no future ones at all*. It went
    unseen because every plant that reaches this path in the fixtures has a
    recent anchor — until a plant moves indoors and swaps the water balance for
    an interval, which is what an earlier release made possible. The backlog slack below keeps
    a month-restricted rule finding the same overdue occurrence it always did.
    """
    if interval_days <= 0:
        return []
    overdue: tuple[int, date] | None = None
    future: list[tuple[int, date]] = []
    elapsed = max(0, (today - anchor).days // interval_days)
    index = max(1, elapsed - limit)
    while len(future) < limit:
        day = anchor + timedelta(days=interval_days * index)
        if day > until:
            break
        if not (months and day.month not in months):
            if day <= today:
                overdue = (index, day)
            else:
                future.append((index, day))
        index += 1
    return ([overdue] if overdue else []) + future


def due_at_for(
    due_on: date, *, all_day: bool, sunset: datetime | None = None
) -> datetime:
    """When the task is due, as a timestamp.

    Routine work is an all-day event and is posted at the rounds hour. A timed
    task (bring indoors, cover) is due *by* sunset before the cold night, and
    falls back to the rounds hour when no sunset is known rather than inventing
    one.
    """
    if all_day or sunset is None:
        return datetime.combine(due_on, time(hour=ROUNDS_HOUR), tzinfo=UTC)
    return sunset


# ------------------------------------------------------------------ generation


def _balance_caveats(environment: Environment, on: date) -> tuple[list[Caveat], str]:
    """The weather engine's reasons, plus this package's own, plus the confidence they cap at."""
    caveats = list(environment.degradations)
    confidence = environment.confidence or "unknown"

    newest = environment.newest_day
    if newest is not None and newest < on:
        stale_days = (on - newest).days
        if stale_days > 1:
            caveats.append(
                Caveat(
                    code="balance_not_current",
                    detail=(
                        f"The water balance this task was built from ends "
                        f"{stale_days} days before it is due. Nothing has advanced "
                        "the deficit since, so the plant is drier than this says."
                    ),
                    caps_at="low",
                )
            )
            confidence = weakest(confidence, "low")
    return caveats, confidence


def generate(
    subject: Subject,
    rules: list[Rule],
    *,
    today: date,
    horizon_days: int,
    latitude: float,
    environments: dict[str, Environment] | None = None,
    last_completed: dict[str, date] | None = None,
) -> list[Occurrence]:
    """Every *recurring* occurrence one plant owes between its anchor and the horizon.

    Idempotent: the same arguments produce the same occurrences with the same
    ids, which is what lets generation run on every read without a worker (see
    the README — the scheduled job belongs to ``workers/`` and is escalated, not
    reached into).

    The frost guard is not here. A frost task answers one night rather than
    recurring, is dated from the weather engine's alert rather than from an anchor, and
    is *withdrawn* when E stops raising the alert — so it is built in
    ``tending.frost`` and merged in by ``tending.service``. A ``frost_guard``
    rule reaching this function is skipped rather than run as an interval.
    """
    environments = environments or {}
    last_completed = last_completed or {}
    until = today + timedelta(days=horizon_days)
    out: list[Occurrence] = []

    for rule in resolve_rules(rules):
        if rule.strategy == "frost_guard":
            continue
        anchor = anchor_for(subject, last_completed.get(rule.task_type))
        environment = environments.get(rule.task_type, Environment())

        if rule.strategy == "water_balance" and environment.applies:
            # The model is the authority here, and it is the *only* one: under
            # the design nothing measures the soil. Running the interval as well
            # would put a second, unattested watering in the calendar beside a
            # deficit that says the plant is comfortable.
            occurrence = _balance_occurrence(
                subject,
                rule,
                anchor=anchor,
                today=today,
                environment=environment,
                last_completed_on=last_completed.get(rule.task_type),
            )
            if occurrence is not None:
                out.append(occurrence)
            continue
        # No model answer for this plant — an indoor pot, or an outdoor one the
        # engine declined to judge. Fall through to the rule's interval if it
        # declares one, and otherwise generate nothing at all rather than a task
        # nobody can justify.

        interval = effective_interval(
            rule,
            season=season_for(today, latitude),
            dormant=subject.is_dormant(today),
            humidity_pct=environment.humidity_pct,
        )
        if interval is None or interval == SUSPENDED:
            continue

        for index, due_on in occurrence_dates(
            anchor, int(interval), today=today, until=until, months=rule.months
        ):
            out.append(
                Occurrence(
                    rule=rule,
                    subject=subject,
                    index=index,
                    anchor=anchor,
                    due_on=due_on,
                    amount_ml=rule.amount_ml
                    or (
                        water_amount_ml(subject) if rule.task_type == "water" else None
                    ),
                    # An interval rule is a schedule, not a measurement. It is
                    # only ever as good as the interval it was configured with,
                    # and that came from a cited care value or it did not.
                    confidence=rule.interval_confidence,
                    caveats=rule.interval_caveats,
                )
            )

    out.sort(key=lambda occurrence: (occurrence.due_on, occurrence.rule.task_type))
    return out


def _balance_occurrence(
    subject: Subject,
    rule: Rule,
    *,
    anchor: date,
    today: date,
    environment: Environment,
    last_completed_on: date | None = None,
) -> Occurrence | None:
    """The single outstanding watering the water balance currently justifies.

    One occurrence, at index 0, held at the same identity for as long as it goes
    undone — so a deficit that crosses on Tuesday and is still unmet on Friday
    moves one calendar event rather than leaving three.

    **A watering somebody has already done today settles this task, and the
    model does not get a second vote**. "Somebody watered this
    plant" is a fact with an actor and a timestamp in it; how much deficit that
    relieved is a model's opinion, and waiting for the opinion before honouring
    the fact is what put a freshly watered plant straight back on the round
    under a new id — completion moves the anchor, the anchor is part of the
    identity, so the plant was asked for again under a task nobody had ever
    seen, and a second VEVENT went into every subscribed calendar.

    The relief the watering bought is still modelled, and separately: it reaches
    the deficit through ``water_balance(irrigation=...)`` (``tending.
    environment``) and is degraded where it is guessed at. That is the design,
    and this line does not depend on it — a completed watering is done whether
    or not the conversion to millimetres can be made honestly.

    Future waterings are deliberately *not* projected here. Working out which
    day a deficit will next cross a threshold is the weather engine's engine and
    an earlier release's job; guessing at it in this package would be a plant fact nobody
    attested, which is exactly what the no-invented-plant-facts rule forbids.
    """
    if last_completed_on is not None and last_completed_on >= today:
        return None

    status = environment.balance_status
    if status not in {"due", "satisfied"} and not environment.is_due:
        return None

    caveats, confidence = _balance_caveats(environment, today)
    satisfied_by = None
    if status == "satisfied":
        # E attributes it to rain or to logged irrigation; the contract's
        # vocabulary calls a person with a watering can "manual".
        satisfied_by = "rain" if environment.satisfied_by == "rain" else "manual"

    return Occurrence(
        rule=rule,
        subject=subject,
        index=OUTSTANDING_INDEX,
        anchor=anchor,
        due_on=today,
        status="satisfied" if status == "satisfied" else "due",
        satisfied_by=satisfied_by,
        amount_ml=rule.amount_ml or water_amount_ml(subject),
        confidence=confidence,
        caveats=tuple(caveats),
    )


def resolve_rules(rules: list[Rule]) -> list[Rule]:
    """One rule per task type: the specimen's own beats the species default."""
    chosen: dict[str, Rule] = {}
    for rule in rules:
        if not rule.enabled or rule.task_type not in TASK_TYPES:
            continue
        existing = chosen.get(rule.task_type)
        if existing is None or (
            existing.scope == "species" and rule.scope == "specimen"
        ):
            chosen[rule.task_type] = rule
    return [chosen[key] for key in sorted(chosen)]


def water_amount_ml(subject: Subject) -> int | None:
    """A watering volume for a container, from the container's own size.

    Roughly a quarter of the pot's volume, which is the usual "until it runs
    from the base" quantity, clamped to something a person can carry. It is a
    fact about the *pot*, not about the plant, so it needs no citation — and a
    plant in the ground gets no figure at all rather than a made-up one.
    """
    if not subject.in_container or not subject.container_litres:
        return None
    return int(min(2000, max(100, round(subject.container_litres * 25))))


def caveat_note(caveats: tuple[Caveat, ...], confidence: str) -> str | None:
    """The plain-language warning that rides on ``task.detail``.

    ``detail`` is in the frozen contract, so this reaches a client that knows
    nothing about the structured fields beside it. the design requires an uncited
    value to be *visibly* marked, and a field no released client reads would not
    be visible to anybody.
    """
    if not caveats:
        return None
    lead = (
        "This is a guess, not a measurement."
        if confidence == "unknown"
        else f"Confidence: {confidence}."
    )
    return " ".join([lead, *(caveat.detail for caveat in caveats)])


def detail_for(occurrence: Occurrence) -> str | None:
    """Everything the reader is owed in prose: the reason, then the doubts.

    ``detail`` is in the frozen contract and is the one field a client on any
    version of it renders, so it carries both halves — what this instruction
    rests on, and what is wrong with it.
    """
    note = caveat_note(occurrence.caveats, occurrence.confidence)
    return " ".join(part for part in (occurrence.detail, note) if part) or None


def task_row(occurrence: Occurrence) -> dict[str, Any]:
    """An occurrence as a ``task`` row, titles and ICS identity included."""
    themed, plain = titles_for(
        occurrence.rule.task_type,
        occurrence.subject.display_name,
        has_nickname=occurrence.subject.has_nickname,
        amount_ml=occurrence.amount_ml,
    )
    identity = occurrence.task_id
    return {
        "id": identity,
        "specimen_id": occurrence.subject.specimen_id,
        "care_rule_id": occurrence.rule.id,
        "task_type": occurrence.rule.task_type,
        "due_at": due_at_for(
            occurrence.due_on,
            all_day=occurrence.all_day,
            sunset=occurrence.deadline,
        ),
        "all_day": occurrence.all_day,
        "status": occurrence.status,
        "satisfied_by": occurrence.satisfied_by,
        "amount_ml": occurrence.amount_ml,
        "priority": occurrence.priority,
        "title": themed,
        "plain_title": plain,
        "detail": detail_for(occurrence),
        "completed_at": None,
        "completed_by": None,
        "notes": None,
        "ics_uid": ics_uid(identity),
        "ics_sequence": 0,
        # Additive beyond contract 1.2.0, and escalated to the maintainers in the
        # pull request: the design put these on the weather engine's answers for exactly this
        # reason, and a task built from a degraded input must not arrive
        # looking like a clean one.
        "confidence": occurrence.confidence,
        "degraded": bool(occurrence.caveats),
        "degradations": [caveat.to_dict() for caveat in occurrence.caveats],
    }
