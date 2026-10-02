"""The words a person actually reads. Owner: The hub.

These are the tests that keep the brief's four constraints true, and they are
written against the rendered strings rather than against the builders, because
the constraint is about what somebody reads at seven in the morning and not
about which function assembled it.
"""

from __future__ import annotations

from datetime import date

import pytest

from workers.hub.notify import copy
from workers.hub.notify.model import Certainty, Recipient

TODAY = date(2026, 10, 23)


def task(**overrides):
    """A ``Task`` as the scheduler serves one, with the earlier certainty fields."""
    base = {
        "id": "01890080-0000-7000-8000-000000000001",
        "specimen": {"id": "s-1", "nickname": "Gilderoy", "display_name": "Gilderoy"},
        "task_type": "water",
        "due_at": "2026-10-23T07:00:00Z",
        "status": "due",
        "title": "Tend Gilderoy",
        "plain_title": "Water Gilderoy — 450 ml",
        "detail": None,
        "confidence": "high",
        "degraded": False,
        "degradations": [],
    }
    base.update(overrides)
    return base


def rounds(**overrides):
    base = {"date": TODAY.isoformat(), "due": [task()], "unscheduled": []}
    base.update(overrides)
    return base


# ------------------------------------------------------- the original-theme rule: plain titles


def test_a_notification_carries_the_tasks_plain_title_verbatim(recipient):
    """Not the themed title, and not a rewrite of either.

    The brief is explicit: a phone notification at 7 AM is the least
    appropriate place for the themed half alone. The plain title is a NOT NULL
    column that the scheduler has already written carefully; this package's only
    job is to use it.
    """
    notification = copy.rounds_notification(rounds(), recipient, today=TODAY)
    assert "• Water Gilderoy — 450 ml" in notification.lines()
    assert "Tend Gilderoy" not in notification.body


def test_the_themed_half_travels_beside_the_plain_one_never_instead_of_it(recipient):
    """The original-theme rule pairs them. It does not ban the theme — it bans the theme alone."""
    notification = copy.rounds_notification(rounds(), recipient, today=TODAY)
    assert notification.themed_title
    assert notification.title == "Today's rounds: 1 task"
    assert notification.themed_title != notification.title


def test_a_task_with_no_plain_title_is_described_rather_than_dropped():
    """A field this package did not expect must not cost somebody a task.

    Dropping the line would be the silent failure the design asks this
    parts of the project to design against, one layer up from the readings.
    """
    assert copy.plain_title(
        {"task_type": "repot", "specimen": {"nickname": "Bertram"}}
    ) == ("Repot Bertram")


# ------------------------------------ nothing measures the soil


def test_a_watering_says_the_soil_is_not_measured(recipient):
    """the design. There is no probe, so no sentence may imply there is one."""
    notification = copy.rounds_notification(rounds(), recipient, today=TODAY)
    assert copy.NO_SENSOR_NOTE in notification.body
    assert "the soil is dry" not in notification.body.lower()


def test_the_sensor_wording_exists_and_nothing_today_can_reach_it():
    """The override path is complete and unreachable, which is the design shape.

    The day a probe appears and a task comes back ``satisfied_by: sensor``, the
    caveat drops out on its own — no other change.
    """
    modelled = [task()]
    measured = [task(satisfied_by="sensor")]
    assert copy.basis_note(modelled) == copy.NO_SENSOR_NOTE
    assert copy.basis_note(measured) is None
    assert copy.names_sensor(task()) is False


def test_a_notification_with_no_watering_in_it_carries_no_soil_caveat():
    """A standing caveat on every message is a caveat nobody reads."""
    assert (
        copy.basis_note([task(task_type="prune", plain_title="Prune Gilderoy")]) is None
    )


# --------------------------------------- certainty is carried through


def test_a_degraded_task_does_not_read_like_a_measurement(recipient):
    """The scheduler's own sentence, shown as-is — the contract's own words."""
    degraded = task(
        confidence="low",
        degraded=True,
        degradations=[
            {
                "code": "et0_fallback",
                "detail": "The evaporation estimate fell back to a seasonal average.",
                "caps_at": "low",
            }
        ],
    )
    notification = copy.rounds_notification(
        rounds(due=[degraded]), recipient, today=TODAY
    )
    assert (
        "The evaporation estimate fell back to a seasonal average." in notification.body
    )
    assert notification.certainty.degraded is True
    assert notification.certainty.confidence == "low"


def test_an_api_that_says_nothing_about_certainty_is_not_read_as_confident(recipient):
    """The live case today: ``Task.confidence`` is the scheduler's escalation 1, not 1.2.0.

    A deployment running a 1.2.0 API serves a task with no certainty fields at
    all. Absence is not confidence, and the one API version that cannot tell us
    anything must not be the one we sound surest about.
    """
    bare = {
        "id": "t-1",
        "specimen": {"nickname": "Gilderoy"},
        "task_type": "water",
        "plain_title": "Water Gilderoy",
    }
    notification = copy.rounds_notification(rounds(due=[bare]), recipient, today=TODAY)
    assert notification.certainty.stated is False
    assert notification.certainty.is_sure is False
    assert "estimate" in notification.body.lower()


def test_a_list_is_only_as_certain_as_its_least_certain_task():
    """A reader cannot tell which line a caveat belongs to, so it covers all."""
    merged = copy.rounds_certainty(
        [
            task(confidence="high"),
            task(
                confidence="low",
                degraded=True,
                degradations=[
                    {"code": "x", "detail": "Stale forecast.", "caps_at": "low"}
                ],
            ),
        ]
    )
    assert merged.confidence == "low"
    assert merged.degraded is True


def test_caps_at_is_a_ceiling_and_never_raises_the_stated_confidence():
    """the design own rule, stated on the ``Degradation`` schema."""
    certainty = Certainty.from_payload(
        {
            "confidence": "high",
            "degraded": True,
            "degradations": [{"code": "x", "detail": "d", "caps_at": "low"}],
        }
    )
    assert certainty.confidence == "low"


def test_a_confident_undegraded_task_is_not_hedged():
    """The caveat has to mean something, which means not always being there."""
    assert copy.certainty_note(Certainty(confidence="high", stated=True)) is None


# ---------------------------------------- do not claim what you could not judge


def test_a_day_with_nothing_due_sends_nothing_at_all(recipient):
    """There is no all-clear in this application, by design.

    ``unscheduled[]`` means the app cannot always tell "nothing needs doing"
    from "I could not work out what these plants need". Of those two, only
    silence is honest about both.
    """
    assert copy.rounds_notification(rounds(due=[]), recipient, today=TODAY) is None


def test_plants_the_scheduler_could_not_judge_are_counted_in_the_message(recipient):
    payload = rounds(unscheduled=[{"specimen_id": "a", "reason": "no interval"}])
    notification = copy.rounds_notification(payload, recipient, today=TODAY)
    assert "1 plant could not be scheduled at all" in notification.body


def test_an_api_that_cannot_answer_unscheduled_does_not_imply_the_list_is_complete(
    recipient,
):
    """``unscheduled`` is the scheduler's escalation 3 and is not in the frozen 1.2.0 spec.

    A missing key has not told us there are none. It has told us nothing, and
    the difference is the whole of the brief's "claiming all is well is not".
    """
    payload = rounds()
    payload.pop("unscheduled")
    notification = copy.rounds_notification(payload, recipient, today=TODAY)
    assert "may not be everything" in notification.body


def test_an_empty_unscheduled_list_adds_no_noise(recipient):
    notification = copy.rounds_notification(rounds(), recipient, today=TODAY)
    assert "could not be scheduled" not in notification.body
    assert "may not be everything" not in notification.body


def test_a_long_list_is_truncated_and_says_that_it_was(recipient):
    payload = rounds(
        due=[task(id=f"t-{i}", plain_title=f"Water plant {i}") for i in range(9)]
    )
    notification = copy.rounds_notification(payload, recipient, today=TODAY)
    assert "…and 3 more." in notification.body
    assert notification.title == "Today's rounds: 9 tasks"


# ------------------------------------------------------------------- frost


def alert(**overrides):
    base = {
        "id": "01890090-0000-7000-8000-000000000001",
        "specimen": {"id": "s-9", "nickname": "The Lemon Tree"},
        "night_of": "2026-10-23",
        "forecast_low_c": -2.0,
        "threshold_c": 1.7,
        "action": "bring_indoors",
        "advisory": "Freeze Warning in effect from 2 AM to 9 AM",
        "state": "open",
        "confidence": "high",
        "degraded": False,
        "degradations": [],
    }
    base.update(overrides)
    return base


def test_a_frost_notification_names_the_plant_the_action_and_the_low(recipient):
    notification = copy.frost_notification(
        {"alerts": [alert()], "unassessable": []}, recipient
    )
    assert notification.title == "Frost tonight: 1 plant at risk"
    assert "• Bring indoors The Lemon Tree." in notification.body
    assert "Forecast low -2.0 °C." in notification.body
    assert notification.urgent is True


def test_the_nws_headline_is_carried_through(recipient):
    """It is the most authoritative sentence available and it is already plain."""
    notification = copy.frost_notification(
        {"alerts": [alert()], "unassessable": []}, recipient
    )
    assert "Freeze Warning in effect from 2 AM to 9 AM" in notification.body


def test_a_resolved_alert_is_not_news(recipient):
    payload = {"alerts": [alert(state="resolved")], "unassessable": []}
    assert copy.frost_notification(payload, recipient) is None


def test_a_worse_forecast_for_the_same_night_is_new_news(recipient):
    """The failure this guards: a dedupe on the date alone swallows an escalation."""
    mild = copy.frost_notification(
        {"alerts": [alert(forecast_low_c=-1.0)], "unassessable": []}, recipient
    )
    severe = copy.frost_notification(
        {"alerts": [alert(forecast_low_c=-6.0)], "unassessable": []}, recipient
    )
    assert mild.dedupe_key != severe.dedupe_key


def test_an_escalated_action_for_the_same_night_is_new_news(recipient):
    cover = copy.frost_notification(
        {"alerts": [alert(action="cover")], "unassessable": []}, recipient
    )
    indoors = copy.frost_notification(
        {"alerts": [alert()], "unassessable": []}, recipient
    )
    assert cover.dedupe_key != indoors.dedupe_key


def test_a_tenth_of_a_degree_is_not_new_news(recipient):
    """Re-alerting on noise is how somebody turns frost notifications off."""
    a = copy.frost_notification(
        {"alerts": [alert(forecast_low_c=-2.0)], "unassessable": []}, recipient
    )
    b = copy.frost_notification(
        {"alerts": [alert(forecast_low_c=-2.1)], "unassessable": []}, recipient
    )
    assert a.dedupe_key == b.dedupe_key


def test_plants_that_could_not_be_assessed_are_counted(recipient):
    payload = {
        "alerts": [alert()],
        "unassessable": [{"specimen_id": "x", "reason": "no hardiness data"}],
    }
    notification = copy.frost_notification(payload, recipient)
    assert "1 plant could not be assessed for frost" in notification.body


def test_a_frost_report_with_no_unassessable_key_does_not_imply_completeness(recipient):
    notification = copy.frost_notification({"alerts": [alert()]}, recipient)
    assert "may not be everything" in notification.body


# -------------------------------------------------------------------- units


@pytest.mark.parametrize(
    ("units", "expected"),
    [("metric", "-2.0 °C"), ("imperial", "28 °F")],
)
def test_a_temperature_is_rendered_in_the_units_the_member_asked_for(units, expected):
    """The one notification where this is not cosmetic.

    "28 degrees" is a hard freeze in one system and a warm afternoon in the
    other. SI internally, display units are a user preference (the project conventions).
    """
    assert copy.temperature(-2.0, units) == expected


def test_an_unknown_temperature_is_unknown_and_not_a_zero():
    assert copy.temperature(None) == "unknown"


def test_a_members_unit_preference_reaches_the_frost_message():
    imperial = Recipient.from_member_row(
        {
            "id": "m-2",
            "name": "Keeper",
            "notify_prefs": {
                "home_assistant": {"service": "notify.x", "units": "imperial"}
            },
        }
    )
    notification = copy.frost_notification(
        {"alerts": [alert()], "unassessable": []}, imperial
    )
    assert "28 °F" in notification.body


# ------------------------------------------------------------------- health


def integration(**overrides):
    base = {
        "kind": "home_assistant",
        "name": "Home Assistant",
        "status": "down",
        "last_error": "home_assistant: connection refused",
    }
    base.update(overrides)
    return base


def test_a_broken_adapter_is_described_in_words_somebody_can_act_on(recipient):
    notification = copy.health_notification(
        {"integrations": [integration()]}, recipient
    )
    assert notification.title == "Home Assistant is not answering"
    assert "connection refused" in notification.body
    assert "Indoor readings stop" in notification.body


def test_a_setup_step_is_never_reported_as_a_fault(recipient):
    """the earlier distinction, kept. A health alert on a fresh install is one nobody
    reads on the day it means something."""
    for status in ("unconfigured", "disabled", "ok"):
        payload = {"integrations": [integration(status=status)]}
        assert copy.health_notification(payload, recipient) is None


def test_a_recovery_is_said_once_and_plainly(recipient):
    notification = copy.health_notification(
        {"integrations": []}, recipient, recovered=["Home Assistant"]
    )
    assert notification.title == "Home Assistant is answering again"


def test_a_health_notification_changes_when_the_fault_changes(recipient):
    down = copy.health_notification({"integrations": [integration()]}, recipient)
    stale = copy.health_notification(
        {"integrations": [integration(status="stale")]}, recipient
    )
    assert down.dedupe_key != stale.dedupe_key


# ----------------------------------- the irrigation path, modelled not faked


def test_a_watering_the_rain_already_covered_is_never_notified(recipient):
    """``MorningRounds`` puts those in ``satisfied[]``, and only ``due`` is read.

    This is also where an irrigation controller's waterings will arrive the day
    one exists. Nothing here needs to change for that —
    a task the app did not ask a person to do is simply not in ``due``.
    """
    payload = rounds(due=[], satisfied=[task(status="satisfied", satisfied_by="rain")])
    assert copy.rounds_notification(payload, recipient, today=TODAY) is None


def test_a_partly_satisfied_day_notifies_only_about_what_is_left(recipient):
    payload = rounds(
        due=[task(plain_title="Water Bertram")],
        satisfied=[task(id="t-2", plain_title="Water Gilderoy", status="satisfied")],
    )
    notification = copy.rounds_notification(payload, recipient, today=TODAY)
    assert notification.title == "Today's rounds: 1 task"
    assert "Water Gilderoy" not in notification.body
