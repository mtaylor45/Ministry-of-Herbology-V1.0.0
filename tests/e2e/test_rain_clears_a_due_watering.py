"""the earlier exit criterion, end to end: rain visibly clears a due watering.

under ``MOH_SCENARIO=storm``, standing on the day it rained — the
Almanac's water balance, Morning Rounds, and the ICS feed a subscriber actually
fetches. Nothing calls an engine: that arithmetic has unit tests in
``tests/engines/`` and in the weather engine's own suite, and a suite that called
``run_balance`` directly could be green while every screen was wrong.

The scenario is the right place for this, and the baseline was not. An earlier
version of this file made the baseline recording end on a downpour so that the
default deployment would show a settled watering. The weather engine's selector does that job
properly, and ``api/almanac/tests/`` pins the baseline as the "a deployment that
sets nothing sees no change" case — which is the better principle. The baseline
is thirty days of ordinary weather again.

The distinction the whole releases turns on, and the one these assertions exist
to protect: **a watering the sky settled must stay on the screen, marked, and
attributed.** A task that disappears because it rained is indistinguishable from
a task that was never scheduled, and a person who cannot tell those apart cannot
trust the round. So it is not enough that the plant is absent from ``due``; it
has to be *present* in ``satisfied``, still carrying its plant, its title and
its amount, and saying ``rain``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from conftest import (  # type: ignore[import-not-found]
    BASIL_ON_THE_TERRACE,
    HOSTAS_IN_THE_SHADE_BED,
    LAVENDER_HEDGE,
    LAVENDER_ON_THE_PORCH,
    LEMON_ON_THE_PORCH,
    LEMON_ON_THE_TERRACE,
    MONSTERA_IN_THE_STUDY,
    ROSE_IN_THE_BORDER,
    ics_events,
    rain_day_of,
    subscribe,
    tasks_by_specimen,
)

#: Outdoor, under open sky, and over threshold when the rain arrived.
SETTLED_BY_THE_RAIN = (LEMON_ON_THE_TERRACE, BASIL_ON_THE_TERRACE)

#: Outdoor, but under a roof. ``f_cover = 0``: the rain never reaches them, so
#: their waterings stay owed. These are the falsifiers — an engine that applied
#: rainfall to every outdoor plant would pass every assertion above and fail
#: these.
STILL_OWED_UNDER_COVER = (LEMON_ON_THE_PORCH, LAVENDER_ON_THE_PORCH)

#: Outdoor, under open sky, and **never due**: deep soil profiles, or a
#: drought-adapted species, that six days of this heat does not exhaust. The
#: rain settled nothing they owed, so they are ``ok`` and not ``satisfied``.
NEVER_THIRSTY = (ROSE_IN_THE_BORDER, LAVENDER_HEDGE, HOSTAS_IN_THE_SHADE_BED)


def rounds(client: Any, on: str | None = None) -> dict[str, Any]:
    response = client.get("/api/v1/tending/rounds", params={"on": on} if on else {})
    assert response.status_code == 200, response.text
    return dict(response.json())


def balance(client: Any, specimen_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/almanac/water-balance/{specimen_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


# ------------------------------------------------------------- the almanac


def test_the_almanac_reports_the_rain_as_having_settled_the_deficit(
    storm: Any, contract: Any
) -> None:
    """The water balance is where the claim starts. It must make it plainly."""
    for specimen_id in SETTLED_BY_THE_RAIN:
        payload = balance(storm, specimen_id)
        contract(payload, "WaterBalance")

        assert payload["applies"] is True, specimen_id
        assert payload["status"] == "satisfied", (
            f"{specimen_id}: the balance must say 'satisfied' and not merely "
            f"'ok' — got {payload['status']!r}"
        )
        assert payload["satisfied_by"] == "rain", specimen_id
        assert payload["is_due"] is False, specimen_id
        assert payload["deficit_mm"] < payload["threshold_mm"], specimen_id

        newest = payload["days"][-1]
        assert newest["day"] == rain_day_of("storm")
        assert newest["precip_mm"] > 0, "we are standing on the day it rained"
        assert newest["status"] == "satisfied"


def test_the_almanac_does_not_credit_rain_to_a_plant_it_never_reached(
    storm: Any, contract: Any
) -> None:
    """``f_cover = 0`` is the whole point of the covered flag."""
    for specimen_id in STILL_OWED_UNDER_COVER:
        payload = balance(storm, specimen_id)
        contract(payload, "WaterBalance")

        assert payload["cover_factor"] == 0.0, specimen_id
        assert payload["is_due"] is True, specimen_id
        assert payload["status"] == "due", specimen_id
        assert payload["satisfied_by"] is None, specimen_id
        assert all(day["precip_mm"] == 0 for day in payload["days"]), (
            f"{specimen_id} is under a roof; no rain may be applied to it, "
            "however much fell on the site"
        )
        assert any(
            day["gross_precip_mm"] > 0 for day in payload["days"]
        ), "the site's rain is still reported, it is just not applied"


# -------------------------------------------------------------- the rounds


def test_the_settled_watering_is_on_the_round_and_not_merely_absent(
    storm: Any, contract: Any
) -> None:
    """The assertion the releases exists for.

    It would be easy to write a suite that only checked the plant was gone from
    ``due``. That suite would stay green if somebody deleted the satisfied
    section entirely. So: present, marked, attributed, and still a whole task.
    """
    payload = rounds(storm)
    contract(payload, "MorningRounds")

    satisfied = tasks_by_specimen(payload["satisfied"])
    due = tasks_by_specimen(payload["due"])
    unscheduled = {row["specimen_id"] for row in payload["unscheduled"]}

    for specimen_id in SETTLED_BY_THE_RAIN:
        assert specimen_id in satisfied, (
            f"{specimen_id} vanished from the round instead of being shown as "
            "settled by the rain — which is the failure this release is about"
        )
        task = satisfied[specimen_id]
        contract(task, "Task")

        assert task["status"] == "satisfied"
        assert task["satisfied_by"] == "rain", (
            "a satisfied task must say what satisfied it; 'satisfied' with no "
            "attribution is a task that silently disappeared with extra steps"
        )
        assert task["task_type"] == "water"
        # Still a whole task: a person reading the round can see which plant,
        # what the job was and how much water it would have taken.
        assert task["specimen"]["display_name"].strip()
        assert task["title"].strip() and task["plain_title"].strip()
        assert task["amount_ml"] and task["amount_ml"] > 0
        assert task["deep_link"].endswith("/tending")

        assert specimen_id not in due, "a settled watering is not also owed"
        assert specimen_id not in unscheduled, (
            "a settled watering is a task that was scheduled and then settled, "
            "not a plant the scheduler could not speak for"
        )


def test_every_settled_watering_names_what_settled_it(storm: Any) -> None:
    """No unattributed entry may sit in the satisfied section at all."""
    payload = rounds(storm)
    assert payload["satisfied"], (
        "38 mm of rain settled nothing the round shows, so the 'settled "
        "without you' section cannot be demonstrated — this is the gap "
        "The app's screens raised at the end of an earlier release"
    )
    unattributed = [
        task["specimen"]["display_name"]
        for task in payload["satisfied"]
        if not task["satisfied_by"]
    ]
    assert not unattributed, unattributed


def test_a_plant_under_cover_is_still_asked_for_water(storm: Any) -> None:
    payload = rounds(storm)
    due = tasks_by_specimen(payload["due"])
    satisfied = tasks_by_specimen(payload["satisfied"])

    for specimen_id in STILL_OWED_UNDER_COVER:
        assert specimen_id in due, (
            f"{specimen_id} is under a roof; the rain settled nothing for it "
            "and its watering must still be owed"
        )
        assert specimen_id not in satisfied
        assert due[specimen_id]["status"] == "due"
        assert due[specimen_id]["satisfied_by"] is None


def test_an_indoor_plant_is_untouched_by_the_weather(storm: Any, contract: Any) -> None:
    """Indoor plants run on interval rules; no rain falls in a study."""
    payload = balance(storm, MONSTERA_IN_THE_STUDY)
    contract(payload, "WaterBalance")
    assert payload["applies"] is False
    assert payload["note"], "an inapplicable balance must say why it is shown"

    due = tasks_by_specimen(rounds(storm)["due"])
    assert MONSTERA_IN_THE_STUDY in due
    assert due[MONSTERA_IN_THE_STUDY]["satisfied_by"] is None


def test_a_plant_that_was_never_thirsty_is_not_reported_as_settled(
    storm: Any, contract: Any
) -> None:
    """ "Satisfied" means the sky did a job you owed. These were never owed.

    A deep soil profile, and a drought-adapted species, that six days of this
    heat does not exhaust. Reporting them as satisfied would claim credit for
    work nobody needed — and would destroy the distinction the satisfied
    section exists to draw, because it would no longer separate a task the
    weather cleared from a task that never existed.

    This is also the assertion that was wrong in the fixture to an earlier release:
    ``storm.json`` claimed the in-ground rose was satisfied by rain, which the
    engine's own arithmetic has always refused.
    """
    round_today = rounds(storm)
    satisfied = tasks_by_specimen(round_today["satisfied"])
    due = tasks_by_specimen(round_today["due"])

    for specimen_id in NEVER_THIRSTY:
        payload = balance(storm, specimen_id)
        contract(payload, "WaterBalance")
        assert payload["applies"] is True, specimen_id
        assert payload["is_due"] is False, specimen_id
        assert (
            payload["status"] == "ok"
        ), f"{specimen_id}: 'ok' is not 'satisfied' — got {payload['status']!r}"
        assert payload["satisfied_by"] is None, specimen_id
        assert specimen_id not in satisfied, specimen_id
        assert specimen_id not in due, specimen_id


# ------------------------------------------------------------ the calendar


def test_the_calendar_cancels_the_settled_watering_by_the_uid_it_already_had(
    storm: Any,
) -> None:
    """A subscribed feed has no way to say "this one is gone" but to say so.

    Dropping the event leaves it sitting in somebody's calendar forever. So the
    satisfied watering must appear in the feed, once, under the UID it was
    published with, as ``STATUS:CANCELLED``.
    """
    path = subscribe(storm)
    response = storm.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    events = ics_events(response.text)

    payload = rounds(storm)
    satisfied = tasks_by_specimen(payload["satisfied"])
    due = tasks_by_specimen(payload["due"])

    for specimen_id in SETTLED_BY_THE_RAIN:
        uid = f"task-{satisfied[specimen_id]['id']}@herbology"
        assert uid in events, (
            "the settled watering was dropped from the feed instead of being "
            "cancelled in it; every subscriber would keep the stale event"
        )
        assert events[uid]["STATUS"] == "CANCELLED", events[uid]
        assert "satisfied by rain" in events[uid]["DESCRIPTION"].lower(), (
            "the event body must say why it was cancelled, or a subscriber "
            "sees a task withdrawn with no explanation"
        )

    for specimen_id in STILL_OWED_UNDER_COVER:
        uid = f"task-{due[specimen_id]['id']}@herbology"
        assert (
            uid in events and events[uid]["STATUS"] == "CONFIRMED"
        ), "a watering the rain never reached must stay a live calendar event"


def test_the_settled_watering_keeps_the_identity_it_had_while_it_was_due(
    storm: Any,
) -> None:
    """The UID is the occurrence's, never the date's and never the status's.

    Rebuilt here from the scheduling primitives rather than read back out of
    the same response that produced it, so this fails if anybody ever makes an
    event's identity depend on what happened to it. An identity that moved when
    a task was satisfied would put a *second* event in every subscriber's
    calendar and leave the first one standing.
    """
    from tending.defaults import derived_rule_id
    from tending.domain import EPOCH, OUTSTANDING_INDEX, Rule, ics_uid, task_id

    specimens = {
        row["id"]: row for row in storm.get("/api/v1/specimens").json()["items"]
    }
    satisfied = tasks_by_specimen(rounds(storm)["satisfied"])

    for specimen_id in SETTLED_BY_THE_RAIN:
        acquired = specimens[specimen_id]["acquired_on"]
        anchor = date.fromisoformat(acquired) if acquired else EPOCH
        rule = Rule(
            id=derived_rule_id(specimen_id, "water"),
            task_type="water",
            strategy="water_balance",
        )
        expected = str(task_id(specimen_id, rule, anchor, OUTSTANDING_INDEX))

        assert satisfied[specimen_id]["id"] == expected, (
            "a satisfied watering must keep the id it had while it was due — "
            "the water balance decides its status, never its identity"
        )
        assert ics_uid(expected) == f"task-{expected}@herbology"

    # And the identity does not move with the day the round is read on. This is
    # what makes the cancellation above a cancellation rather than a second
    # event: the outstanding watering is one occurrence held at one id for as
    # long as it goes undone, however many mornings it is looked at.
    later = (date.fromisoformat(rain_day_of("storm")) + timedelta(days=2)).isoformat()
    for specimen_id, task in tasks_by_specimen(
        rounds(storm, later)["satisfied"]
    ).items():
        if specimen_id in SETTLED_BY_THE_RAIN:
            assert task["id"] == satisfied[specimen_id]["id"], (
                "the outstanding watering changed identity between two "
                "readings, which would put a second event in every "
                "subscribed calendar"
            )
