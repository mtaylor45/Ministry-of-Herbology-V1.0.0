"""The frost guard's scheduling half: an alert becomes a task, and lets go again.

The weather engine raises the alert. This module answers four questions about it, and
every one of them is a *scheduling* question — none of them is a question about
weather or about a plant, because this package may not answer those.

**1. Which alerts become tasks?** ``bring_indoors`` and ``cover`` do.
``monitor`` deliberately does not: it is the weather engine's word for "watching, nothing to do",
and a task nobody can perform is worse than no task at all — it is the thing
that teaches a household to tick items off without reading them. The alert is
still shown in Morning Rounds, which is where a thing to watch belongs.

**2. What is the task's identity?** The night, not the due date. A frost task's
occurrence *is* the cold night it answers, so the night is its anchor and
:data:`tending.domain.OUTSTANDING_INDEX` its index: one outstanding job per
plant per night. Sunset moves, the forecast low moves, the advisory arrives late
— none of that changes the identity, so the subscriber's calendar moves the
event it already has instead of gaining a second one. A different *night* is a
different job and gets a different id, which is correct, and the one it replaces
is withdrawn rather than dropped.

**3. When may the plant go back out?** The plan says after three consecutive
forecast nights above the plant's threshold, and
``fixtures/scenarios/frost.json`` says the same. Both numbers are read, never
invented: the threshold is the one E states on the alert, the nights are the
ones E states in the forecast, and the count is the plan's. Where G cannot get a
threshold from the weather engine it says so and schedules nothing — see :func:`return_task`.

**4. When is a task withdrawn?** When E stops asking for it and its deadline is
still ahead of us. A forecast that changes is the normal case, not the
exception, and a task that simply vanished from a subscribed calendar is
indistinguishable from one that never existed — so it is marked
``satisfied``/``forecast_change`` (the vocabulary the frozen contract already
carries for exactly this) and the feed cancels the event by UID.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tending.defaults import derived_rule_id
from tending.domain import (
    FROST_TASK_TYPES,
    OUTSTANDING_INDEX,
    Caveat,
    FrostWatch,
    Occurrence,
    Outlook,
    Rule,
    Subject,
    task_id,
)

#: Consecutive forecast nights above the plant's own threshold before a plant
#: that came inside is suggested back out. The plan's number
#: ("A matching 'return outdoors' suggestion appears after 3 consecutive
#: forecast nights above threshold") and the frost scenario's, not this
#: package's: a shorter run would be this code inventing a horticultural
#: judgement, which the no-invented-plant-facts rule forbids.
RETURN_RUN_NIGHTS = 3

#: Why a withdrawn frost task is withdrawn, in the contract's own vocabulary.
#: ``satisfied`` rather than ``cancelled`` on purpose: the household was asked
#: to do something and is owed the news that it is off, on the screen as well as
#: in the calendar. The calendar has no way to say "you need not have bothered"
#: except by cancelling the event, and ``tending.ics`` does that.
WITHDRAWN_STATUS = "satisfied"
WITHDRAWN_BY = "forecast_change"


def watch_from_alert(alert: dict[str, Any]) -> FrostWatch | None:
    """One of the weather engine's ``FrostAlert`` payloads, as a scheduling input.

    ``None`` for an alert this package cannot read rather than a task built on
    guesses: a malformed alert must not become a confident instruction. The
    plant is named by the caller in that case (:func:`unreadable_reason`), so a
    dropped alert is never silent.
    """
    specimen = alert.get("specimen") or {}
    specimen_id = str(alert.get("specimen_id") or specimen.get("id") or "")
    try:
        night_of = date.fromisoformat(str(alert["night_of"]))
        low = float(alert["forecast_low_c"])
        threshold = float(alert["threshold_c"])
    except (KeyError, TypeError, ValueError):
        return None
    if not specimen_id or not alert.get("action"):
        return None
    return FrostWatch(
        alert_id=str(alert.get("id") or ""),
        specimen_id=specimen_id,
        night_of=night_of,
        forecast_low_c=low,
        threshold_c=threshold,
        action=str(alert["action"]),
        advisory=alert.get("advisory"),
        confidence=str(alert.get("confidence") or "unknown"),
        degradations=tuple(
            Caveat(
                code=str(row.get("code") or "unknown"),
                detail=str(row.get("detail") or ""),
                caps_at=str(row.get("caps_at") or "medium"),
            )
            for row in alert.get("degradations") or []
        ),
        state=str(alert.get("state") or "open"),
    )


def watches(alerts: list[dict[str, Any]]) -> dict[str, FrostWatch]:
    """The weather engine's open alerts by specimen, keeping the earliest night for each plant.

    E raises one alert per plant today, but the rule is stated here rather than
    relied upon: two alerts for one plant would otherwise make the task that
    gets generated depend on list order, and the plant is owed the *first* cold
    night, not whichever one arrived last.
    """
    out: dict[str, FrostWatch] = {}
    for alert in alerts:
        watch = watch_from_alert(alert)
        if watch is None or watch.state != "open":
            continue
        current = out.get(watch.specimen_id)
        if current is None or watch.night_of < current.night_of:
            out[watch.specimen_id] = watch
    return out


def unreadable_reason(alert: dict[str, Any]) -> str:
    """What to say about an alert this package could not read."""
    return (
        "A frost alert for this plant could not be read well enough to raise a "
        f"task from it (night {alert.get('night_of')!r}, action "
        f"{alert.get('action')!r}). It is shown as an alert, but nobody has been "
        "asked to do anything about it."
    )


def guard_rule(watch: FrostWatch) -> Rule:
    """The ``frost_guard`` care rule an open alert justifies.

    Derived, deterministic and unstored, exactly as the watering rules in
    ``tending.defaults`` are: the id is a pure function of the plant and the job,
    so the rule — and therefore every task anchored to it — keeps its identity
    across restarts and redeployments.

    It carries no interval, because a frost task is not a recurrence. What it
    carries is the weather engine's confidence and the weather engine's degradations, passed through
    unchanged:
    the design put them on the alert so that a consumer could pass them on, and
    the design requires them to reach the instruction.
    """
    return Rule(
        id=derived_rule_id(watch.specimen_id, watch.action),
        task_type=watch.action,
        strategy="frost_guard",
        base_interval_days=None,
        enabled=True,
        specimen_id=watch.specimen_id,
        interval_confidence=watch.confidence,
        interval_caveats=watch.degradations,
    )


def return_rule(watch: FrostWatch) -> Rule:
    """The rule behind the matching ``return_outdoors`` suggestion."""
    return Rule(
        id=derived_rule_id(watch.specimen_id, "return_outdoors"),
        task_type="return_outdoors",
        strategy="frost_guard",
        base_interval_days=None,
        enabled=True,
        specimen_id=watch.specimen_id,
        interval_confidence=watch.confidence,
        interval_caveats=watch.degradations,
    )


def task_id_for(watch: FrostWatch) -> str:
    """The id of the task an alert raises, computed rather than looked up.

    Both directions of the link run through this one function: the task is
    written with this id and the alert is served with it, so the two cannot
    drift apart and neither has to be stored beside the other. ``/almanac/frost``
    can fill its own ``task_id`` by calling it (raised for the maintainers and the weather engine in
    the pull
    request — that endpoint is the weather engine's file).
    """
    return str(
        task_id(
            watch.specimen_id,
            guard_rule(watch),
            anchor=watch.night_of,
            index=OUTSTANDING_INDEX,
        )
    )


def guard_task(
    subject: Subject, watch: FrostWatch, *, today: date, outlook: Outlook
) -> tuple[Occurrence | None, str | None]:
    """The bring-indoors or cover task for one open alert, or why there is none.

    Due *by sunset before* the cold night, from the weather engine's own forecast. With no sunset
    for that day the deadline falls back to the rounds hour and the task says so
    in words rather than inventing a time: a made-up sunset is a fact about the
    sky this package has no business asserting.
    """
    if not watch.is_actionable:
        # ``monitor``: the alert is the whole output. Deliberate, and stated in
        # the module docstring rather than left as an empty branch.
        return None, None
    if watch.night_of < today:
        return None, (
            f"The frost guard's alert for this plant names the night of "
            f"{watch.night_of.isoformat()}, which has already passed. No task "
            "was raised for a night nobody can act on any more."
        )

    sunset = outlook.sunsets.get(watch.eve)
    deadline = (
        f"Due by sunset on {watch.eve.isoformat()}."
        if sunset is not None
        else (
            f"Due on {watch.eve.isoformat()}: no sunset time is available for "
            "that day, so this is timed at the morning rounds hour instead. Do "
            "it before dark."
        )
    )
    return (
        Occurrence(
            rule=guard_rule(watch),
            subject=subject,
            index=OUTSTANDING_INDEX,
            anchor=watch.night_of,
            due_on=watch.eve,
            status="due",
            confidence=watch.confidence,
            caveats=watch.degradations,
            detail=f"{watch.sentence} {deadline}",
            deadline=sunset,
        ),
        None,
    )


def return_task(
    subject: Subject,
    watch: FrostWatch,
    *,
    outlook: Outlook,
    sheltered_on: date,
) -> tuple[Occurrence | None, str | None]:
    """When this plant may go back out, or why that cannot be said yet.

    The judgement, written down because it is the one worth reviewing:

    * **the night after the frost is not enough.** The weather engine's lookahead is 72 hours and
      shows more than one night, and the frost scenario's own three nights of
      cold are why: a plant carried back out on the 24th, after the 23rd's
      freeze, meets the 24th's freeze. The plan's rule — three consecutive
      forecast nights above the plant's threshold — is the conservative reading
      of the same forecast, and it is the plan's and the fixture's rule, not
      this package's invention;
    * **the threshold is the weather engine's.** Not recomputed here from a species minimum and a
      margin: that arithmetic is ``workers/weather/tasks.frost_threshold_c`` and
      a second copy of it in this package is precisely what the README forbids;
    * **the nights counted are the ones after the cold night the plant came in
      for.** Counting from the day it was carried inside would count the mild
      evenings *before* the freeze and send it back out into it;
    * **and it is a suggestion about a forecast.** Three predicted mild nights
      are not three mild nights. The task says so.

    Returns ``(None, reason)`` — a named plant, never silence — when
    the forecast does not yet contain such a run.
    """
    due_on = outlook.nights_above(
        watch.threshold_c, after=watch.night_of, run=RETURN_RUN_NIGHTS
    )
    if due_on is None:
        return None, (
            f"This plant was sheltered on {sheltered_on.isoformat()} and is "
            f"still indoors. The forecast does not yet show "
            f"{RETURN_RUN_NIGHTS} consecutive nights above its "
            f"{watch.threshold_c:g} °C threshold, so no return date can be "
            "given. It stays indoors until one appears."
        )
    return (
        Occurrence(
            rule=return_rule(watch),
            subject=subject,
            index=OUTSTANDING_INDEX,
            anchor=watch.night_of,
            due_on=due_on,
            status="due",
            confidence=watch.confidence,
            caveats=watch.degradations,
            detail=(
                f"Sheltered on {sheltered_on.isoformat()} against the night of "
                f"{watch.night_of.isoformat()}. The forecast is for "
                f"{RETURN_RUN_NIGHTS} consecutive nights above this plant's "
                f"{watch.threshold_c:g} °C threshold, ending "
                f"{due_on.isoformat()} — a forecast, not a measurement, so look "
                "at the sky before you carry it out."
            ),
        ),
        None,
    )


def sheltered_reason(sheltered_on: date) -> str:
    """A plant that is indoors and has no alert to reason about any more.

    The conservative answer, and an honestly uncomfortable one. Once a plant is
    actually moved indoors it leaves the weather engine's frost guard — an indoor plant is never
    frost-alerted — so the threshold that put it there is no longer stated
    anywhere this package may read. Guessing a return date from a species
    minimum and a margin of this package's own would be inventing the care value
    the whole project refuses to invent, and "the next three nights look mild"
    in January would carry a citrus out to die.

    So it schedules nothing, and names the plant instead: silence with a reason
    on it. The fix is a contract one and is asked of A in the pull request.
    """
    return (
        f"This plant was sheltered from frost on {sheltered_on.isoformat()} and "
        "is indoors, where the frost guard no longer assesses it — so nothing "
        "states a threshold to judge a return against, and this package will "
        "not invent one. Put it back out when your own frost risk has passed, "
        "and complete the task from the Tending facet."
    )


def withdrawable(row: dict[str, Any], *, generated_ids: set[str], now: Any) -> bool:
    """Whether a stored frost task should be withdrawn on this pass.

    Three conditions, and the third is the one that keeps the record honest:

    * it is one of the frost guard's own tasks. Nothing else in this package
      stops producing an occurrence for a reason a withdrawal could explain;
    * this generation did not produce it, so the weather engine is no longer asking for it;
    * **its deadline is still ahead of us.** A bring-indoors task for a night
      that has already happened was missed, not withdrawn, and marking it
      "satisfied by a change in the forecast" would be a lie told about a plant
      that froze. It is left exactly as it is, and ages out of the calendar feed
      on its own.
    """
    if row.get("task_type") not in FROST_TASK_TYPES:
        return False
    if str(row.get("id")) in generated_ids:
        return False
    if row.get("status") != "due":
        return False
    due_at = row.get("due_at")
    return bool(due_at is not None and due_at > now)


def link_alerts(
    alerts: list[dict[str, Any]], tasks_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """The weather engine's alerts with ``task_id`` and ``state`` filled in — the releases's point.

    ``task_id`` has been in the contract since 1.0.0 and nothing had ever
    filled it: the app said a plant would be at −2 °C and asked nobody to do
    anything about it. It is computed, not stored, so the alert and its task
    cannot disagree.

    ``state`` follows the task rather than staying ``open`` forever: an alert
    whose task has been done is ``resolved``, and one whose task was withdrawn
    when the forecast warmed is ``expired``. A card that still says "open" over
    a plant already on the kitchen table is the same species of untruth as a
    missing task, one screen further on.
    """
    out: list[dict[str, Any]] = []
    for alert in alerts:
        watch = watch_from_alert(alert)
        if watch is None or not watch.is_actionable:
            out.append(dict(alert))
            continue
        identity = task_id_for(watch)
        row = tasks_by_id.get(identity)
        linked = dict(alert)
        linked["task_id"] = identity if row is not None else None
        if row is not None:
            linked["state"] = _state_for(str(row.get("status") or "due"))
        out.append(linked)
    return out


def _state_for(status: str) -> str:
    if status == "done":
        return "resolved"
    if status in {WITHDRAWN_STATUS, "cancelled", "skipped"}:
        return "expired"
    return "open"
