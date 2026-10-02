"""Today's rounds, rendered small, for the Lunette e-ink panel — the hub.

An e-ink panel is small, monochrome and slow: it refreshes every few minutes
at best, and whatever it last drew stays on the glass whether or not anything
is still feeding it. Four rules follow, and this module is the whole of them.

1. **Frost first.** A plant left out on a frost night is the one mistake the
   panel exists to prevent, so the frost lines lead and ``frost_warning``
   carries the soonest night on its own.
2. **Certainty travels to the line**. A frost line says it is a
   forecast, every time. A task whose confidence is ``unknown`` says it is a
   guess; ``low``, or a degraded one, says it is an estimate. A line on a
   kitchen wall cannot be tapped for the detail, so the hedge is on the line.
3. **A stale panel says it is stale.** The last line is the clock time the
   feed was built, in the site's zone, and the headline carries the round's
   date. A panel that stopped refreshing on Tuesday says "Tue" on Thursday.
4. **No invented fields.** ``LunetteFeed`` is ``generated_at``, ``headline``,
   ``due_count``, ``lines`` and three nullable numbers. What the panel needs
   beyond that goes into ``lines`` as text, and what the contract cannot
   carry is escalated rather than added.

This module reads a ``MorningRounds`` payload — the same one Morning Rounds
reads, from ``GET /tending/rounds`` — and decides nothing about plants. Every
line is built from what the scheduler and the weather engine already said.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .health import redact

#: How many due tasks the panel lists before "and N more". A 7.5" panel holds
#: about fourteen lines of legible type; frost, rain and the clock need the rest.
MAX_TASK_LINES = 8

#: ``FrostAlert.action`` as an instruction, with the plants in the middle.
_ACTION = {
    "bring_indoors": "bring {names} indoors",
    "cover": "cover {names}",
    "monitor": "keep an eye on {names}",
}

_SATISFIED = {
    "rain": "Rain covered",
    "sensor": "Soil sensor says moist",
    "forecast_change": "Forecast rain covers",
    "manual": "Already done",
}

#: Task types a frost alert is the reason for. Such a task is a forecast too.
_FORECAST_TASKS = frozenset({"bring_indoors", "cover", "return_outdoors"})


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _day(value: Any) -> str:
    """``2026-10-22`` as ``Thu 22 Oct``: short, and unambiguous on a wall."""
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{parsed:%a} {parsed.day} {parsed:%b}"


def _temp(value: Any) -> str:
    try:
        return f"{round(float(value))}°C"
    except (TypeError, ValueError):
        return "low unknown"


def _name(item: Mapping[str, Any]) -> str:
    specimen = item.get("specimen")
    if isinstance(specimen, Mapping):
        return str(
            specimen.get("display_name") or specimen.get("nickname") or "a plant"
        )
    return "a plant"


def certainty(task: Mapping[str, Any]) -> str:
    """The hedge a task's line carries, or ``""`` when it has none to carry."""
    if (
        task.get("task_type") in _FORECAST_TASKS
        or task.get("satisfied_by") == "forecast_change"
    ):
        return "forecast"
    confidence = str(task.get("confidence") or "unknown")
    if confidence == "unknown":
        return "a guess"
    if confidence == "low" or task.get("degraded"):
        return "estimate"
    return ""


def _lowest(alerts: Iterable[Mapping[str, Any]]) -> float | None:
    """The coldest forecast low among ``alerts``, or ``None`` if none says."""
    lows = [
        float(a["forecast_low_c"])
        for a in alerts
        if isinstance(a.get("forecast_low_c"), (int, float))
    ]
    return min(lows) if lows else None


def _label(low: Any) -> str:
    """``FROST`` at or below freezing, ``COLD`` above it.

    The frost guard alerts on a margin above 0 °C for tender plants, so a 4 °C night can raise an
    alert. Calling that night a frost
    would be the panel overstating the forecast; calling it cold is true.
    """
    try:
        return "FROST" if float(low) <= 0.0 else "COLD"
    except (TypeError, ValueError):
        return "FROST"


def _hedged(text: str, hedge: str) -> str:
    return f"{text} ({hedge})" if hedge else text


def frost_lines(alerts: Sequence[Mapping[str, Any]]) -> list[str]:
    """One line per night and action, soonest night first, always "forecast"."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for alert in alerts:
        if alert.get("state") not in (None, "open"):
            continue
        key = (str(alert.get("night_of") or ""), str(alert.get("action") or "monitor"))
        groups.setdefault(key, []).append(alert)
    lines: list[str] = []
    for (night, action), group in sorted(groups.items()):
        low = _lowest(group)
        names = ", ".join(_name(a) for a in group)
        degraded = any(a.get("degraded") for a in group)
        hedge = "forecast, estimate" if degraded else "forecast"
        instruction = _ACTION.get(action, action + " {names}").format(names=names)
        lines.append(
            f"{_label(low)} {_day(night)}, low {_temp(low)}: {instruction} ({hedge})"
        )
    return lines


def frost_warning(alerts: Sequence[Mapping[str, Any]]) -> str | None:
    """The soonest frost night in one sentence, or ``None`` when there is none."""
    open_alerts = [a for a in alerts if a.get("state") in (None, "open")]
    if not open_alerts:
        return None
    night = min(str(a.get("night_of") or "") for a in open_alerts)
    tonight = [a for a in open_alerts if str(a.get("night_of") or "") == night]
    low = _lowest(tonight)
    count = len(tonight)
    plants = "1 plant" if count == 1 else f"{count} plants"
    kind = "Frost" if _label(low) == "FROST" else "Cold night"
    sentence = (
        f"{kind} forecast for {_day(night)}: low {_temp(low)}, " f"{plants} to protect."
    )
    advisory = next((str(a["advisory"]) for a in tonight if a.get("advisory")), None)
    return f"{sentence} {advisory}." if advisory else sentence


def task_lines(due: Sequence[Mapping[str, Any]], skip: Iterable[str] = ()) -> list[str]:
    """Due tasks in plain words, the hedge on each line, capped for the glass."""
    skipped = set(skip)
    tasks = [task for task in due if str(task.get("id")) not in skipped]
    lines = [
        _hedged(
            str(task.get("plain_title") or task.get("title") or "A task"),
            certainty(task),
        )
        for task in tasks[:MAX_TASK_LINES]
    ]
    if len(tasks) > MAX_TASK_LINES:
        lines.append(f"…and {len(tasks) - MAX_TASK_LINES} more in the app")
    return lines


def satisfied_lines(satisfied: Sequence[Mapping[str, Any]]) -> list[str]:
    """Settled waterings, briefly: one line per cause, names only."""
    by_cause: dict[str, list[str]] = {}
    for task in satisfied:
        by_cause.setdefault(str(task.get("satisfied_by") or "manual"), []).append(
            _name(task)
        )
    return [
        f"{_SATISFIED.get(cause, 'Settled')}: {', '.join(names)}"
        for cause, names in sorted(by_cause.items())
    ]


def build_feed(
    rounds: Mapping[str, Any] | None,
    *,
    now: datetime,
    tz: str = "UTC",
    secrets: Iterable[str] = (),
    temp_indoor_c: float | None = None,
) -> dict[str, Any]:
    """A ``LunetteFeed`` from a ``MorningRounds``, or from the reason there is none.

    With no round, ``due_count`` is **omitted** rather than served as ``0``:
    zero is a claim that nothing is due, and a panel that cannot reach the
    Ministry knows no such thing. The contract makes every field optional, so
    leaving it out is the honest reading of the schema rather than a gap in it.
    """
    zone = _zone(tz)
    local = now.astimezone(zone)
    stamp = f"Updated {local:%a} {local.day} {local:%b} {local:%H:%M} {local.tzname()}"
    feed: dict[str, Any] = {"generated_at": now.isoformat()}

    if rounds is None:
        feed.update(
            headline="Rounds unavailable",
            lines=[
                "Could not read today's rounds from the Ministry.",
                "Check the Ministry Office screen.",
                stamp,
            ],
            temp_outdoor_c=None,
            temp_indoor_c=temp_indoor_c,
            frost_warning=None,
        )
        return _scrub(feed, secrets)

    due = [t for t in rounds.get("due") or () if isinstance(t, Mapping)]
    satisfied = [t for t in rounds.get("satisfied") or () if isinstance(t, Mapping)]
    alerts = [a for a in rounds.get("alerts") or () if isinstance(a, Mapping)]
    unscheduled = [u for u in rounds.get("unscheduled") or () if isinstance(u, Mapping)]
    weather = (
        rounds.get("weather") if isinstance(rounds.get("weather"), Mapping) else None
    )

    # A frost task already said on its frost line is not said twice.
    alert_tasks = [str(a["task_id"]) for a in alerts if a.get("task_id")]

    lines = frost_lines(alerts)
    tasks = task_lines(due, skip=alert_tasks)
    lines += tasks or ["Nothing due today."]
    lines += satisfied_lines(satisfied)
    if unscheduled:
        count = len(unscheduled)
        plants = "1 plant has" if count == 1 else f"{count} plants have"
        lines.append(f"{plants} no schedule — see the app")
    lines.append(stamp)

    headline = f"{_day(rounds.get('date') or local.date().isoformat())}: {len(due)} due"
    if any(a.get("state") in (None, "open") for a in alerts):
        headline += ", frost forecast"

    outdoor = weather.get("temperature_c") if weather else None
    feed.update(
        headline=headline,
        due_count=len(due),
        lines=lines,
        temp_outdoor_c=float(outdoor) if isinstance(outdoor, (int, float)) else None,
        temp_indoor_c=temp_indoor_c,
        frost_warning=frost_warning(alerts),
    )
    return _scrub(feed, secrets)


def _scrub(feed: dict[str, Any], secrets: Iterable[str]) -> dict[str, Any]:
    """Every string through :func:`redact`, last, so no line can carry a token.

    A plant's nickname and an NWS headline are both text somebody else wrote,
    and this panel hangs in a hallway.
    """
    held = tuple(secrets)
    for key in ("headline", "frost_warning"):
        if isinstance(feed.get(key), str):
            feed[key] = redact(feed[key], held)
    feed["lines"] = [redact(line, held) or "" for line in feed.get("lines") or ()]
    return feed
