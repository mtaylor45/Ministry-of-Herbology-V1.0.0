"""The words — the hub.

Everything this package sends is built here, so the four rules that govern the
wording are in one file rather than scattered across three jobs.

## 1. The plain title, always

The original-theme rule pairs themed copy with a plain equivalent. A phone notification is the
least appropriate place for the themed half alone, so every task line in a
notification body is the task's ``plain_title`` **verbatim** — not a rewrite of
it, not a summary of it, and not the themed ``title``. The scheduler puts both
through ``api/tending/titles.py`` and both are ``NOT NULL`` in the schema; this
package's only job is to pick the right one and not get clever.

The Ministry's voice is carried on :attr:`Notification.themed_title`, beside
the plain title rather than instead of it.

## 2. Nothing measures the soil

there is no soil-moisture hardware and none is expected in v1.0.
Every watering the app produces is therefore a *model's* opinion — parts of the project
The weather engine's water balance, or an interval somebody configured. So no sentence in this
file says the soil is dry, and :func:`basis_note` states the modelled basis
outright on a watering. The sensor phrasing exists, and is reachable only by a
task that actually names a sensor in ``satisfied_by`` — which nothing produces
today, and which is the point: the day a probe appears the copy is already
right.

## 3. Brevity is not a licence to sound certain

A degraded input never becomes an imperative. :func:`certainty_note` turns a
:class:`~workers.hub.notify.model.Certainty` into a sentence, using
``Degradation.detail`` as written — the contract specifies it as "a plain
sentence, written to be shown to the reader as-is".

## 4. A dedupe key names the destination, not the member

Two members can point ``notify_prefs`` at the same Home Assistant service — a
kitchen tablet, a shared speaker, a household Telegram chat. That is one place,
and it should be told a thing once. Keying on the member id instead would make
the tablet chime twice for the same frost, which is how a household learns to
ignore it.

Where their preferences differ — one wants Fahrenheit, one wants Celsius —
whichever is built first wins the single message. One tablet cannot show two
temperatures, and buzzing twice to resolve the disagreement helps nobody.

## 5. Do not claim all is well

``MorningRounds.unscheduled[]`` lists the plants the scheduler could not give a
task to. A push that said "nothing to do today" while three plants were
unjudgeable would be a lie told briefly. Two rules follow, and
:func:`rounds_notification` enforces both: **no all-clear notification is ever
sent** — silence is the message when there is nothing due — and when something
*is* sent, the plants that could not be judged are counted in it.

The same rule applies one level up. ``unscheduled`` is the scheduler's
escalation 3 and is **not** in the frozen 1.2.0 contract, so an API that omits
the key has not told us there are none; it has told us nothing.
:func:`unjudged_note` distinguishes the two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from .model import Certainty, Notification, Recipient

#: What a task says when the app is guessing. Deliberately about the *app*
#: rather than about the plant: "Gilderoy may need water" sounds like a fact
#: about Gilderoy, and this is a fact about how much we know.
HEDGE = "This is an estimate, not a measurement."

#: the design, in one sentence a person can act on. Appended to every watering
#: notification whose task does not name a sensor — which today is all of them.
NO_SENSOR_NOTE = (
    "Nothing measures the soil; waterings are worked out from the weather and "
    "your settings."
)

#: The frost actions, in the plain imperative. The themed halves live in
#: The scheduler's ``titles.py`` and are not repeated here.
FROST_ACTIONS: dict[str, str] = {
    "bring_indoors": "Bring indoors",
    "cover": "Cover",
    "monitor": "Keep an eye on",
}

#: How a status reads to somebody who has not been reading logs.
HEALTH_WORDS: dict[str, str] = {
    "down": "is not answering",
    "stale": "has not reported in a while",
    "degraded": "reported an error but has recovered since",
    "unconfigured": "is not set up yet",
    "disabled": "is switched off",
    "ok": "is answering",
}


def temperature(value: float | None, units: str = "metric") -> str:
    """A temperature for a person to read, in the units they asked for.

    SI internally, display units are a user preference (`the project conventions`). A frost
    warning is the one notification where getting this wrong is not cosmetic:
    "28 degrees" is a hard freeze in one system and a warm afternoon in the
    other.
    """
    if value is None:
        return "unknown"
    if units == "imperial":
        return f"{value * 9 / 5 + 32:.0f} °F"
    return f"{value:.1f} °C"


def plain_title(task: Mapping[str, Any]) -> str:
    """The task's own plain title, verbatim — see the contract-first rule in the module note.

    Falls back through the themed title to a last-resort description rather
    than raising. A task with no ``plain_title`` violates a ``NOT NULL``
    column, so it cannot come from this application's database; it can come
    from a hand-edited mock, and a notification that drops a task because one
    field was odd is the silent failure this parts of the project exists to avoid.
    """
    for key in ("plain_title", "title"):
        value = str(task.get(key) or "").strip()
        if value:
            return value
    name = _specimen_name(task)
    kind = str(task.get("task_type") or "tend").replace("_", " ")
    return f"{kind.capitalize()} {name}".strip()


def _specimen_name(task: Mapping[str, Any]) -> str:
    specimen = task.get("specimen")
    if isinstance(specimen, Mapping):
        for key in ("nickname", "display_name", "name"):
            value = specimen.get(key)
            if value:
                return str(value)
    return "a plant"


def names_sensor(task: Mapping[str, Any]) -> bool:
    """Did this task come from something that actually measured the soil?

    Only ``satisfied_by: sensor`` says so, and nothing produces
    it. Kept as the single place that decides, so the day a probe appears the
    copy changes here and nowhere else.
    """
    return str(task.get("satisfied_by") or "").lower() == "sensor"


def basis_note(tasks: Sequence[Mapping[str, Any]]) -> str | None:
    """The standing caveat for waterings, or ``None`` if none are watering."""
    waterings = [task for task in tasks if str(task.get("task_type")) == "water"]
    if not waterings:
        return None
    if all(names_sensor(task) for task in waterings):
        return None
    return NO_SENSOR_NOTE


def certainty_note(certainty: Certainty) -> str | None:
    """One sentence about how much this is worth, or ``None`` when it is sure.

    The scheduler's own reasons lead, because they are specific and this
    module's are generic. At most two: a notification that spends four lines
    apologising for itself is one nobody finishes reading, and the app has a
    screen for the rest.
    """
    if certainty.is_sure:
        return None
    if certainty.reasons:
        return " ".join(certainty.reasons[:2])
    if not certainty.stated:
        return (
            "The scheduler did not say how certain this is, so treat it as an "
            "estimate."
        )
    return HEDGE


def unjudged_note(rounds: Mapping[str, Any]) -> str | None:
    """What to say about the plants the scheduler could not give a task.

    Three answers, and the third is the one that matters:

    * the key is there and empty — nothing to say, and we may say so;
    * the key is there with entries — say how many, so the list is not read as
      the whole garden;
    * **the key is absent** — the API is a contract version that cannot answer
      the question, so the message must not imply the list is complete.
    """
    if "unscheduled" not in rounds:
        return "This list may not be everything: the app could not check for plants it has no schedule for."
    raw = rounds.get("unscheduled")
    entries = raw if isinstance(raw, Sequence) and not isinstance(raw, str) else ()
    count = len(entries)
    if not count:
        return None
    plant = "plant" if count == 1 else "plants"
    return (
        f"{count} {plant} could not be scheduled at all — see Morning Rounds for why."
    )


def rounds_certainty(tasks: Sequence[Mapping[str, Any]]) -> Certainty:
    """The certainty of a list of tasks: the worst one in it.

    A list is only as trustworthy as its least trustworthy member, and a reader
    cannot tell which line the caveat belongs to — so the caveat covers the
    message.
    """
    merged: Certainty | None = None
    for task in tasks:
        current = Certainty.from_payload(task)
        merged = current if merged is None else merged.merge(current)
    return merged or Certainty()


def rounds_notification(
    rounds: Mapping[str, Any],
    recipient: Recipient,
    *,
    today: date,
) -> Notification | None:
    """Today's rounds, or ``None`` when there is nothing worth interrupting for.

    ``None`` is the common answer and it is deliberate. See the one-change-one-review rule: there is
    no
    all-clear notification in this application, because an all-clear the app is
    not entitled to give is worse than saying nothing at all.
    """
    raw = rounds.get("due")
    due = [item for item in (raw or ()) if isinstance(item, Mapping)]
    if not due:
        return None

    count = len(due)
    noun = "task" if count == 1 else "tasks"
    lines = [f"• {plain_title(task)}" for task in due[:6]]
    if count > len(lines):
        lines.append(f"• …and {count - len(lines)} more.")

    certainty = rounds_certainty(due)
    for note in (certainty_note(certainty), basis_note(due), unjudged_note(rounds)):
        if note:
            lines.append(note)

    on = str(rounds.get("date") or today.isoformat())
    return Notification(
        kind="rounds",
        title=f"Today's rounds: {count} {noun}",
        themed_title="The morning rounds await",
        body="\n".join(lines),
        dedupe_key=f"rounds:{recipient.service}:{on}",
        deep_link="/rounds",
        certainty=certainty,
    )


def frost_notification(
    report: Mapping[str, Any],
    recipient: Recipient,
    *,
    now_local_hour: int | None = None,
) -> Notification | None:
    """The frost alert. The one message that may arrive at any hour.

    Keyed on the *content* rather than on the night, so a warning that gets
    worse gets through: a forecast that drops from −1 °C to −5 °C, or an action
    that escalates from *cover* to *bring indoors*, is new news about the same
    night and a dedupe on the date alone would swallow it.
    """
    raw = report.get("alerts")
    alerts = [item for item in (raw or ()) if isinstance(item, Mapping)]
    open_alerts = [
        alert for alert in alerts if str(alert.get("state") or "open") == "open"
    ]
    if not open_alerts:
        return None

    nights = sorted(
        {
            str(alert.get("night_of") or "")
            for alert in open_alerts
            if alert.get("night_of")
        }
    )
    low = min(
        (
            float(alert["forecast_low_c"])
            for alert in open_alerts
            if isinstance(alert.get("forecast_low_c"), (int, float))
        ),
        default=None,
    )
    count = len(open_alerts)
    plant = "plant" if count == 1 else "plants"
    when = "tonight" if len(nights) == 1 else f"{len(nights)} nights"
    title = f"Frost {when}: {count} {plant} at risk"

    lines: list[str] = []
    if low is not None:
        lines.append(f"Forecast low {temperature(low, recipient.units)}.")
    for alert in open_alerts[:6]:
        action = FROST_ACTIONS.get(str(alert.get("action") or ""), "Protect")
        lines.append(f"• {action} {_alert_specimen(alert)}.")
    if count > 6:
        lines.append(f"• …and {count - 6} more.")

    for alert in open_alerts:
        advisory = str(alert.get("advisory") or "").strip()
        if advisory:
            lines.append(advisory)
            break

    certainty = _merged_certainty(open_alerts)
    note = certainty_note(certainty)
    if note:
        lines.append(note)

    unassessable = report.get("unassessable")
    entries = (
        unassessable
        if isinstance(unassessable, Sequence) and not isinstance(unassessable, str)
        else ()
    )
    if entries:
        others = "plant" if len(entries) == 1 else "plants"
        lines.append(
            f"{len(entries)} {others} could not be assessed for frost — "
            "the Almanac says why."
        )
    elif "unassessable" not in report:
        lines.append(
            "This list may not be everything: the app could not check for "
            "plants it was unable to assess."
        )

    return Notification(
        kind="frost",
        title=title,
        themed_title="A hard frost is forecast for the grounds",
        body="\n".join(lines),
        dedupe_key=f"frost:{recipient.service}:{_frost_digest(open_alerts)}",
        deep_link="/almanac/frost",
        urgent=True,
        certainty=certainty,
    )


def health_notification(
    report: Mapping[str, Any],
    recipient: Recipient,
    *,
    recovered: Sequence[str] = (),
) -> Notification | None:
    """An adapter that has stopped answering, said where a person will see it.

    an earlier release put every failure on ``integration.last_error`` so the Ministry Office
    could show it without anyone reading logs. That was the right place and it
    is still a screen somebody has to open. Under the design Home Assistant is
    the only route to indoor conditions, so an adapter that quietly stopped is
    a month of missing readings nobody noticed — which is this parts of the project's
    own worst failure, and worth one notification.

    ``unconfigured`` and ``disabled`` are never notified. One is a setup step
    and the other is a decision somebody made; a health alert that fires on a
    fresh install is a health alert nobody reads on the day it means something.
    """
    raw = report.get("integrations")
    rows = [item for item in (raw or ()) if isinstance(item, Mapping)]
    broken = [row for row in rows if str(row.get("status")) in {"down", "stale"}]

    if not broken and not recovered:
        return None
    if not broken:
        names = ", ".join(sorted(recovered))
        return Notification(
            kind="health",
            title=f"{names} is answering again",
            themed_title="The instruments are reporting once more",
            body="Readings have resumed.",
            dedupe_key=f"health:{recipient.service}:recovered:{names}",
            deep_link="/office/integrations",
            certainty=Certainty(confidence="high", stated=True),
        )

    lead = broken[0]
    name = str(lead.get("name") or lead.get("kind") or "An integration")
    status = str(lead.get("status") or "down")
    title = f"{name} {HEALTH_WORDS.get(status, 'has a problem')}"
    lines: list[str] = []
    for row in broken:
        row_name = str(row.get("name") or row.get("kind") or "integration")
        row_status = str(row.get("status") or "down")
        line = f"• {row_name} {HEALTH_WORDS.get(row_status, 'has a problem')}"
        detail = str(row.get("last_error") or "").strip()
        if detail:
            line += f" — {detail}"
        lines.append(line)
    lines.append(
        "Indoor readings stop while this is broken, and the Almanac will show "
        "gaps rather than a flat line."
    )
    return Notification(
        kind="health",
        title=title,
        themed_title="The instruments have fallen silent",
        body="\n".join(lines),
        dedupe_key=f"health:{recipient.service}:{_health_digest(broken)}",
        deep_link="/office/integrations",
        certainty=Certainty(confidence="high", stated=True),
    )


# ------------------------------------------------------------------- helpers


def _alert_specimen(alert: Mapping[str, Any]) -> str:
    specimen = alert.get("specimen")
    if isinstance(specimen, Mapping):
        for key in ("nickname", "display_name", "name"):
            value = specimen.get(key)
            if value:
                return str(value)
    return "a plant"


def _merged_certainty(items: Sequence[Mapping[str, Any]]) -> Certainty:
    merged: Certainty | None = None
    for item in items:
        current = Certainty.from_payload(item)
        merged = current if merged is None else merged.merge(current)
    return merged or Certainty()


def _frost_digest(alerts: Sequence[Mapping[str, Any]]) -> str:
    """A stable name for *this* forecast, so a worse one is not a duplicate."""
    parts = sorted(
        "{night}|{specimen}|{action}|{low}".format(
            night=alert.get("night_of"),
            specimen=alert.get("id") or _alert_specimen(alert),
            action=alert.get("action"),
            # Rounded: a tenth of a degree is noise, and re-alerting on noise
            # is how somebody turns frost notifications off in November.
            low=(
                round(float(alert["forecast_low_c"]))
                if isinstance(alert.get("forecast_low_c"), (int, float))
                else "?"
            ),
        )
        for alert in alerts
    )
    return _digest(parts)


def _health_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    parts = sorted(f"{row.get('kind')}|{row.get('status')}" for row in rows)
    return _digest(parts)


def _digest(parts: Sequence[str]) -> str:
    from hashlib import sha256

    return sha256("\n".join(parts).encode()).hexdigest()[:16]
