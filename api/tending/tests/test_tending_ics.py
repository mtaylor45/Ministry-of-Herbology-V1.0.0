"""The calendar feed, as a calendar client would read it.

Parsed back with ``icalendar`` rather than string-matched, because a feed that
reads correctly to a regular expression and not to Google is the failure this
whole module is trying to avoid.
"""

from __future__ import annotations

from datetime import UTC, datetime

from icalendar import Calendar

from tending import ics

BASE = "https://herbology.example.net"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def task(**overrides: object) -> dict:
    base: dict = {
        "id": "t1",
        "ics_uid": "task-t1@herbology",
        "ics_sequence": 0,
        "specimen": {"id": "p1", "display_name": "Gilderoy", "is_outdoor": False},
        "task_type": "water",
        "due_at": datetime(2026, 9, 25, 9, tzinfo=UTC),
        "all_day": True,
        "status": "due",
        "satisfied_by": None,
        "amount_ml": 450,
        "priority": "normal",
        "title": "Tend Gilderoy",
        "plain_title": "Water Gilderoy — 450 ml",
        "detail": None,
        "completed_at": None,
        "deep_link": "/specimen/p1/tending",
        "confidence": "medium",
        "degraded": False,
    }
    base.update(overrides)
    return base


def parse(tasks: list[dict], **kwargs: object) -> Calendar:
    document = ics.render(tasks, name="All rounds", base_url=BASE, now=NOW, **kwargs)
    assert "\r\n" in document, "RFC 5545 is CRLF"
    return Calendar.from_ical(document)


def events(calendar: Calendar) -> list:
    return [c for c in calendar.walk() if c.name == "VEVENT"]


def test_a_routine_task_is_an_all_day_event():
    event = events(parse([task()]))[0]
    assert event["DTSTART"].params["VALUE"] == "DATE"
    # DTEND is exclusive for a DATE value: a one-day event ends tomorrow.
    assert (event.decoded("DTEND") - event.decoded("DTSTART")).days == 1


def test_a_frost_task_is_timed_and_carries_a_reminder():
    """Due by sunset before the cold night, and no use without a nudge."""
    event = events(
        parse([task(task_type="bring_indoors", all_day=False, amount_ml=None)])
    )[0]
    assert isinstance(event.decoded("DTSTART"), datetime)
    assert [c for c in event.walk() if c.name == "VALARM"]


def test_a_timed_event_keeps_its_time_when_the_row_arrives_serialised():
    """The shape the feed is actually rendered from, which is not a ``datetime``.

    ``tending.schemas.ics_task`` serialises ``due_at`` to ISO text on the way in.
    This test exists because the module read that string as a bare date and put
    the first bring-indoors task at midnight UTC rather than at the sunset it was
    due by — green in every unit test above, wrong in the running app.
    """
    sunset = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)
    event = events(
        parse(
            [
                task(
                    task_type="bring_indoors",
                    all_day=False,
                    amount_ml=None,
                    due_at=sunset.isoformat().replace("+00:00", "Z"),
                )
            ]
        )
    )[0]
    assert event.decoded("DTSTART") == sunset
    assert event.decoded("DTEND") == sunset + ics.TIMED_DURATION


def test_the_summary_pairs_the_themed_phrase_with_the_plain_action():
    """The plan's own shape: "Tend the Monstera — water 500 ml"."""
    summary = str(events(parse([task()]))[0]["SUMMARY"])
    assert summary == "Tend Gilderoy — water 450 ml"


def test_the_body_carries_the_plain_title_the_note_and_the_deep_link():
    event = events(parse([task(detail="This is a guess, not a measurement.")]))[0]
    body = str(event["DESCRIPTION"])
    assert "Water Gilderoy — 450 ml" in body
    assert "This is a guess" in body
    assert f"{BASE}/specimen/p1/tending" in body
    assert str(event["URL"]) == f"{BASE}/specimen/p1/tending"


def test_a_satisfied_task_is_cancelled_by_uid_rather_than_dropped():
    """Dropping it leaves the event in a subscriber's calendar forever."""
    event = events(parse([task(status="satisfied", satisfied_by="rain")]))[0]
    assert str(event["STATUS"]) == "CANCELLED"
    assert str(event["UID"]) == "task-t1@herbology"
    assert "satisfied by rain" in str(event["DESCRIPTION"])


def test_a_completed_task_stays_in_the_calendar_as_history():
    event = events(parse([task(status="done", completed_at=NOW)]))[0]
    assert str(event["STATUS"]) == "CONFIRMED"


def test_a_reschedule_shows_as_a_sequence_bump_on_the_same_uid():
    first = events(parse([task()]))[0]
    later = events(
        parse([task(due_at=datetime(2026, 9, 29, 9, tzinfo=UTC), ics_sequence=1)])
    )[0]
    assert str(first["UID"]) == str(later["UID"])
    assert int(later["SEQUENCE"]) == int(first["SEQUENCE"]) + 1


def test_uids_are_unique_within_one_document():
    uids = [str(event["UID"]) for event in events(parse([task(), task()]))]
    assert len(uids) == len(set(uids)) == 1


def test_special_characters_survive_the_round_trip():
    """Commas and semicolons in a nickname must not split a property."""
    awkward = task(
        title="Tend Bert, the Second; sort of",
        plain_title="Water Bert, the Second; sort of — 450 ml",
    )
    body = str(events(parse([awkward]))[0]["DESCRIPTION"])
    assert "Bert, the Second; sort of" in body


def test_the_calendar_names_itself_and_asks_to_be_refreshed():
    calendar = parse([task()])
    assert "All rounds" in str(calendar["X-WR-CALNAME"])
    assert str(calendar["X-PUBLISHED-TTL"]) == ics.REFRESH_INTERVAL


def test_degraded_confidence_reaches_the_calendar():
    """the design does not stop at the app's edge."""
    event = events(parse([task(confidence="unknown", degraded=True)]))[0]
    assert str(event["X-MOH-CONFIDENCE"]) == "unknown"
    assert str(event["X-MOH-DEGRADED"]) == "TRUE"
