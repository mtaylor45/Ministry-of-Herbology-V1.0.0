"""The calendar feed itself — RFC 5545 out of stored tasks.

Rendering runs through the ``icalendar`` package rather than string
concatenation. Folding at 75 *octets*, escaping commas, semicolons and
backslashes in every TEXT value, and CRLF everywhere are the parts a hand-rolled
writer gets subtly wrong, and a feed that parses in one client and not another
is worse than no feed at all.

Three behaviours here come straight from the plan:

* **the UID is the task's, and never the date's.** A reschedule updates the
  event in place and bumps ``SEQUENCE``; see ``tending.domain`` for why;
* **a satisfied or cancelled task is cancelled by UID**, not dropped. Dropping
  it leaves the event sitting in a subscriber's calendar forever, because a
  subscribed feed has no way to say "and this one is gone" except by saying so;
* **routine work is an all-day event; a frost task is timed with a reminder**,
  due by sunset before the cold night.

The feed token appears nowhere in this module. It is in the URL the client
subscribed with and that is the only place it belongs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from icalendar import Alarm, Calendar, Event

from tending.titles import plain_action

PRODID = "-//The Ministry of Herbology//Tending//EN"

#: Google refreshes subscribed feeds on its own schedule and ignores this more
#: often than it honours it. It costs nothing to ask, and the Ministry Office
#: screen says plainly that a subscription lags — pretending otherwise is how
#: somebody waits an afternoon for an event that was never coming (the hub
#: ships push for members who need it sooner).
REFRESH_INTERVAL = "PT12H"

#: How long before a timed task the reminder fires. Enough to fetch a plant
#: trolley, not so much that it is noise.
ALARM_LEAD = timedelta(hours=2)

#: A timed task is a moment to act by, not a meeting. The duration exists only
#: because a zero-length event renders badly in most clients.
TIMED_DURATION = timedelta(minutes=30)

_PRIORITY = {"urgent": 1, "normal": 5, "low": 9}

#: Statuses whose events must vanish from a subscriber's calendar. Satisfied is
#: in here and *not* in the app: the plan is explicit that rain marks a task
#: satisfied on screen rather than hiding it, while the calendar has no way to
#: render "you need not have bothered" except by cancelling the event.
_CANCELLED_STATUSES = frozenset({"satisfied", "cancelled", "skipped"})


def _as_datetime(value: Any) -> datetime:
    """A stored or serialised timestamp, as a timestamp.

    The string case is not decoration. ``tending.schemas.ics_task`` serialises
    ``due_at`` to ISO text on its way here, and falling back to midnight on the
    right *date* is invisible for an all-day event and wrong for every timed one:
    it put the first bring-indoors task in the calendar at midnight UTC instead of
    at the sunset it was due by. The unit tests passed throughout, because they
    build rows with ``datetime`` objects; the running app did not.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def description_for(task: dict[str, Any], *, deep_link: str) -> str:
    """The event body: the plain title, the caveat if there is one, the link.

    The plain title leads because this is what leaves the app. A themed line in
    somebody's work calendar at seven in the morning is a puzzle; "Water the
    Monstera — 500 ml" is an instruction.
    """
    lines = [str(task.get("plain_title") or "")]
    detail = task.get("detail")
    if detail:
        lines.append(str(detail))
    if task.get("status") == "satisfied":
        lines.append(_settled_by(task.get("satisfied_by")))
    lines.append(f"Complete it here: {deep_link}")
    return "\n".join(line for line in lines if line)


#: The contract's ``satisfied_by`` vocabulary, in words. An event body reading
#: "satisfied by forecast_change" is the machine talking to itself in the one
#: place only people look; ``rain`` keeps its own wording because it is the
#: wording the test suite's end-to-end story asserts on the wire.
_SETTLED_BY = {
    "rain": "rain",
    "sensor": "a soil sensor",
    "forecast_change": "a change in the forecast",
    "manual": "somebody already doing it",
}


def _settled_by(satisfied_by: Any) -> str:
    """Why this event is cancelled. Never blank: a withdrawal needs a reason."""
    phrase = _SETTLED_BY.get(str(satisfied_by or ""), "something else")
    return f"Already satisfied by {phrase} — nothing to do."


def event_for(
    task: dict[str, Any],
    *,
    base_url: str,
    now: datetime,
) -> Event:
    """One ``VEVENT``. All-day for routine work, timed for a frost task."""
    event = Event()
    event.add("uid", str(task["ics_uid"]))
    event.add("sequence", int(task.get("ics_sequence") or 0))
    event.add("dtstamp", now)

    due_at = _as_datetime(task["due_at"])
    if task.get("all_day", True):
        day = _as_date(due_at)
        event.add("dtstart", day)
        # DTEND is exclusive for a DATE value: a one-day event ends tomorrow.
        event.add("dtend", day + timedelta(days=1))
    else:
        event.add("dtstart", due_at)
        event.add("dtend", due_at + TIMED_DURATION)

    themed = str(task.get("title") or "")
    plain = str(task.get("plain_title") or "")
    # The original-theme rule on the wire, in the plan's own shape: "Tend the Monstera — water
    # 500 ml". The themed phrase names the plant and the plain half says what to
    # do, so a calendar row read at a glance by somebody who never opened the
    # app is still an instruction. The full plain title leads the DESCRIPTION.
    action = plain_action(str(task.get("task_type") or ""), task.get("amount_ml"))
    event.add("summary", f"{themed} — {action}" if themed else plain)

    deep_link = f"{base_url.rstrip('/')}{task.get('deep_link') or ''}"
    event.add("description", description_for(task, deep_link=deep_link))
    event.add("url", deep_link)
    event.add("categories", ["Ministry of Herbology", str(task.get("task_type") or "")])
    event.add("priority", _PRIORITY.get(str(task.get("priority")), 5))
    event.add(
        "status",
        "CANCELLED" if task.get("status") in _CANCELLED_STATUSES else "CONFIRMED",
    )
    event.add("transp", "TRANSPARENT")
    if task.get("completed_at"):
        event.add("last-modified", _as_datetime(task["completed_at"]))

    # the design travels into the calendar too. A client that renders none of the
    # X- properties still sees the caveat, because DESCRIPTION carries it.
    if task.get("confidence"):
        event.add("x-moh-confidence", str(task["confidence"]))
    if task.get("degraded"):
        event.add("x-moh-degraded", "TRUE")

    if not task.get("all_day", True) and task.get("status") not in _CANCELLED_STATUSES:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", plain)
        alarm.add("trigger", -ALARM_LEAD)
        event.add_component(alarm)

    return event


def render(
    tasks: list[dict[str, Any]],
    *,
    name: str,
    base_url: str,
    now: datetime | None = None,
) -> str:
    """A whole ``VCALENDAR``, ready to serve as ``text/calendar``."""
    now = now or datetime.now(UTC)
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", name)
    calendar.add("x-wr-caldesc", "Plant care from The Ministry of Herbology")
    calendar.add("refresh-interval;value=duration", REFRESH_INTERVAL)
    calendar.add("x-published-ttl", REFRESH_INTERVAL)

    seen: set[str] = set()
    for task in tasks:
        uid = str(task["ics_uid"])
        if uid in seen:
            # Two events with one UID is the duplicate this whole scheme exists
            # to prevent; if it ever happens, serve one rather than both.
            continue
        seen.add(uid)
        calendar.add_component(event_for(task, base_url=base_url, now=now))

    rendered = calendar.to_ical()
    return rendered.decode("utf-8") if isinstance(rendered, bytes) else str(rendered)
