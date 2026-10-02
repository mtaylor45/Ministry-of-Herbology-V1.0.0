"""The frost guard, from the weather engine's alert to somebody carrying a tree inside.

Nothing here hard-codes a number out of ``fixtures/``. That directory is
The test suite's and L re-cuts it; four pull requests in one night once fixed the
same red ``main`` because tests held stale copies of somebody else's data. So the
unit tests below state their own weather, and the end-to-end ones read the
numbers back out of the running app — the alert's own threshold, the forecast's
own lows — and assert the *relationship* between them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from workers.weather.settings import get_settings as weather_settings

from tending import frost
from tending.domain import ROUNDS_HOUR, Caveat, FrostWatch, Outlook, Subject, task_row

NIGHT = date(2026, 10, 23)
SUNSET = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)


def subject(**kwargs) -> Subject:
    return Subject(
        specimen_id="01890040-0000-7000-8000-0000000000aa",
        display_name="Sour Bertram",
        has_nickname=True,
        is_outdoor=kwargs.pop("is_outdoor", True),
        in_container=kwargs.pop("in_container", True),
        container_litres=45.0,
        **kwargs,
    )


def watch(**kwargs) -> FrostWatch:
    defaults = dict(
        alert_id="6a558ef3-0057-5070-aa0c-56bc538b6f0a",
        specimen_id=subject().specimen_id,
        night_of=NIGHT,
        forecast_low_c=-2.0,
        threshold_c=3.67,
        action="bring_indoors",
        advisory="Freeze Warning in effect from 2 AM to 9 AM",
        confidence="high",
    )
    return FrostWatch(**{**defaults, **kwargs})


def outlook(lows: dict[date, float] | None = None, *, sunset: bool = True) -> Outlook:
    return Outlook(
        lows_c=lows or {},
        sunsets={NIGHT - timedelta(days=1): SUNSET} if sunset else {},
    )


# ----------------------------------------------------------- an alert is a task


def test_an_open_alert_becomes_a_task_due_by_sunset_before_the_cold_night():
    occurrence, reason = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=outlook()
    )
    assert reason is None
    assert occurrence is not None
    row = task_row(occurrence)
    assert row["task_type"] == "bring_indoors"
    # Timed, not all-day, and due *by* the sunset E states — not at midnight and
    # not on the night itself, which would be one sunset too late.
    assert row["all_day"] is False
    assert row["due_at"] == SUNSET
    assert row["priority"] == "urgent"
    assert row["title"] and row["plain_title"]
    assert row["title"] != row["plain_title"]


def test_the_task_id_the_alert_carries_is_the_task_that_was_written():
    """Both directions of the link, and nothing stored to keep them in step."""
    occurrence, _ = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=outlook()
    )
    assert occurrence is not None
    assert frost.task_id_for(watch()) == task_row(occurrence)["id"]


def test_a_monitor_alert_raises_no_task_at_all():
    """Deliberate: a task nobody can perform teaches people to tick blindly."""
    occurrence, reason = frost.guard_task(
        subject(), watch(action="monitor"), today=date(2026, 10, 20), outlook=outlook()
    )
    assert occurrence is None
    assert reason is None


def test_a_cover_alert_becomes_a_cover_task_for_a_plant_in_the_ground():
    occurrence, _ = frost.guard_task(
        subject(in_container=False),
        watch(action="cover"),
        today=date(2026, 10, 20),
        outlook=outlook(),
    )
    assert occurrence is not None
    row = task_row(occurrence)
    assert row["task_type"] == "cover"
    assert row["all_day"] is False and row["priority"] == "urgent"


def test_a_frost_task_says_it_rests_on_a_forecast_rather_than_a_measurement():
    """nothing measures the air where the plant stands, so say so."""
    occurrence, _ = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=outlook()
    )
    assert occurrence is not None
    detail = task_row(occurrence)["detail"]
    assert "Forecast, not a measurement" in detail
    assert "-2 °C" in detail and "3.67 °C" in detail
    assert "Freeze Warning" in detail


def test_workstream_es_certainty_reaches_the_instruction():
    """a task built on a doubted alert must not look like a clean one."""
    doubted = watch(
        confidence="low",
        degradations=(
            Caveat(
                code="min_temp_uncited", detail="No reliable citation.", caps_at="low"
            ),
        ),
    )
    occurrence, _ = frost.guard_task(
        subject(), doubted, today=date(2026, 10, 20), outlook=outlook()
    )
    assert occurrence is not None
    row = task_row(occurrence)
    assert row["confidence"] == "low"
    assert row["degraded"] is True
    assert [d["code"] for d in row["degradations"]] == ["min_temp_uncited"]
    assert "No reliable citation." in row["detail"]


def test_an_unknown_sunset_falls_back_to_the_rounds_hour_and_admits_it():
    occurrence, _ = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=outlook(sunset=False)
    )
    assert occurrence is not None
    row = task_row(occurrence)
    assert row["due_at"] == datetime.combine(
        NIGHT - timedelta(days=1), time(hour=ROUNDS_HOUR), tzinfo=UTC
    )
    assert "no sunset time is available" in row["detail"]
    assert "before dark" in row["detail"]


def test_a_night_that_has_already_passed_names_the_plant_instead_of_asking():
    occurrence, reason = frost.guard_task(
        subject(), watch(), today=NIGHT + timedelta(days=1), outlook=outlook()
    )
    assert occurrence is None
    assert reason is not None and "already passed" in reason


# ----------------------------------------------------------------- the identity


def test_a_moved_sunset_is_the_same_job_but_another_night_is_a_new_one():
    """Identity is the night, never the deadline. The calendar depends on it."""
    early = outlook()
    late = Outlook(
        lows_c={},
        sunsets={NIGHT - timedelta(days=1): SUNSET + timedelta(minutes=40)},
    )
    first, _ = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=early
    )
    moved, _ = frost.guard_task(
        subject(), watch(), today=date(2026, 10, 20), outlook=late
    )
    other_night, _ = frost.guard_task(
        subject(),
        watch(night_of=NIGHT + timedelta(days=1)),
        today=date(2026, 10, 20),
        outlook=Outlook(lows_c={}, sunsets={NIGHT: SUNSET + timedelta(days=1)}),
    )
    assert first is not None and moved is not None and other_night is not None
    assert task_row(first)["id"] == task_row(moved)["id"]
    assert task_row(first)["ics_uid"] == task_row(moved)["ics_uid"]
    assert task_row(first)["due_at"] != task_row(moved)["due_at"]
    assert task_row(other_night)["id"] != task_row(first)["id"]


# ------------------------------------------------------------------- going back


def mild(days: list[tuple[date, float]]) -> Outlook:
    return Outlook(lows_c=dict(days), sunsets={})


def test_the_return_waits_for_three_consecutive_nights_above_the_threshold():
    """The plan's rule, and the frost scenario's: not the night after the frost."""
    nights = mild(
        [
            (NIGHT, -2.0),
            (NIGHT + timedelta(days=1), -1.0),  # still freezing — no return
            (NIGHT + timedelta(days=2), 6.0),
            (NIGHT + timedelta(days=3), 9.0),
            (NIGHT + timedelta(days=4), 10.0),  # the third mild night
        ]
    )
    occurrence, reason = frost.return_task(
        subject(), watch(), outlook=nights, sheltered_on=NIGHT - timedelta(days=1)
    )
    assert reason is None
    assert occurrence is not None
    row = task_row(occurrence)
    assert row["task_type"] == "return_outdoors"
    assert row["due_at"].date() == NIGHT + timedelta(days=4)
    # A suggestion about a forecast, and all-day: there is no deadline hour on
    # carrying a plant back out.
    assert row["all_day"] is True
    assert row["priority"] == "normal"
    assert "forecast, not a measurement" in row["detail"]


def test_the_nights_counted_are_the_ones_after_the_freeze_not_after_the_move():
    """Counting from the move would send the plant out into the freeze itself."""
    nights = mild(
        [
            (NIGHT - timedelta(days=3), 14.0),  # mild evenings *before* the frost
            (NIGHT - timedelta(days=2), 12.0),
            (NIGHT - timedelta(days=1), 11.0),
            (NIGHT, -2.0),
        ]
    )
    occurrence, reason = frost.return_task(
        subject(), watch(), outlook=nights, sheltered_on=NIGHT - timedelta(days=4)
    )
    assert occurrence is None
    assert reason is not None


def test_a_forecast_that_never_warms_gives_no_date_but_names_the_plant():
    """an unanswerable question must not read as a reassuring answer."""
    nights = mild([(NIGHT + timedelta(days=n), 2.0) for n in range(1, 6)])
    occurrence, reason = frost.return_task(
        subject(), watch(), outlook=nights, sheltered_on=NIGHT
    )
    assert occurrence is None
    assert reason is not None
    assert "3 consecutive nights" in reason and "3.67 °C" in reason


def test_two_mild_nights_and_a_gap_are_not_three_mild_nights():
    nights = mild(
        [
            (NIGHT + timedelta(days=1), 9.0),
            (NIGHT + timedelta(days=2), 9.0),
            # day 3 missing from the forecast entirely
            (NIGHT + timedelta(days=4), 9.0),
        ]
    )
    assert nights.nights_above(3.67, after=NIGHT, run=3) is None


# ----------------------------------------------------------------- withdrawal


def row_for(status: str = "due", due_at: datetime | None = None, **kwargs) -> dict:
    return {
        "id": "task-1",
        "task_type": "bring_indoors",
        "status": status,
        "due_at": due_at or datetime(2026, 10, 23, 1, tzinfo=UTC),
        **kwargs,
    }


def test_a_frost_task_the_guard_no_longer_asks_for_is_withdrawn():
    assert frost.withdrawable(
        row_for(), generated_ids=set(), now=datetime(2026, 10, 20, tzinfo=UTC)
    )


def test_a_frost_task_the_guard_still_asks_for_is_left_alone():
    assert not frost.withdrawable(
        row_for(), generated_ids={"task-1"}, now=datetime(2026, 10, 20, tzinfo=UTC)
    )


def test_a_task_for_a_night_that_has_already_happened_is_not_withdrawn():
    """It was missed, not withdrawn. Calling that "satisfied" would be a lie."""
    assert not frost.withdrawable(
        row_for(), generated_ids=set(), now=datetime(2026, 10, 24, tzinfo=UTC)
    )


def test_nothing_but_the_frost_guards_own_tasks_is_withdrawn():
    assert not frost.withdrawable(
        row_for(task_type="water"),
        generated_ids=set(),
        now=datetime(2026, 10, 20, tzinfo=UTC),
    )


# --------------------------------------------------------------- linking the two


def alert_payload(**overrides) -> dict:
    payload = {
        "id": watch().alert_id,
        "specimen": {"id": subject().specimen_id, "display_name": "Sour Bertram"},
        "night_of": NIGHT.isoformat(),
        "forecast_low_c": -2.0,
        "threshold_c": 3.67,
        "action": "bring_indoors",
        "task_id": None,
        "state": "open",
        "confidence": "high",
        "degraded": False,
        "degradations": [],
    }
    payload.update(overrides)
    return payload


def test_an_alert_with_no_task_yet_carries_no_task_id():
    """Computed, not stored — but only claimed once the task is really there."""
    (linked,) = frost.link_alerts([alert_payload()], {})
    assert linked["task_id"] is None
    assert linked["state"] == "open"


def test_an_alert_whose_task_is_done_reads_resolved():
    identity = frost.task_id_for(watch())
    (linked,) = frost.link_alerts(
        [alert_payload()], {identity: {"id": identity, "status": "done"}}
    )
    assert linked["task_id"] == identity
    assert linked["state"] == "resolved"


def test_an_alert_whose_task_was_withdrawn_reads_expired():
    identity = frost.task_id_for(watch())
    (linked,) = frost.link_alerts(
        [alert_payload()],
        {identity: {"id": identity, "status": frost.WITHDRAWN_STATUS}},
    )
    assert linked["state"] == "expired"


def test_a_monitor_alert_is_passed_through_untouched():
    payload = alert_payload(action="monitor")
    (linked,) = frost.link_alerts([payload], {})
    assert linked == payload


# --------------------------------------------------- the whole thing, on the wire

LEMON = "01890040-0000-7000-8000-000000000004"
INDOOR_SHELF = "01890010-0000-7000-8000-000000000002"


@pytest.fixture
def under_frost(monkeypatch: pytest.MonkeyPatch):
    """The app as an operator running the frost demo would have it.

    The inventory API's mock Register is reset too: a relocation is a write into it,
    and one test's moved lemon must not be the next test's starting position.
    """
    from app.main import app
    from inventory.fixture_repository import reset_fixture_repository as reset_register
    from tending.fixture_repository import reset_fixture_repository as reset_schedule

    monkeypatch.setenv("MOH_SCENARIO", "frost")
    monkeypatch.delenv("MOH_SCENARIO_DAY", raising=False)
    weather_settings.cache_clear()
    reset_schedule()
    reset_register()
    with TestClient(app) as client:
        yield client
    weather_settings.cache_clear()
    reset_schedule()
    reset_register()


def daily_forecast(client: TestClient) -> list[dict]:
    """The weather engine's ten-day forecast, which is where the sunsets and the lows come from."""
    # The site is read off a location rather than typed in: the fixtures are
    # The test suite's and L re-cuts them.
    locations = client.get("/api/v1/locations").json()
    response = client.get(
        "/api/v1/almanac/forecast",
        params={"site_id": locations[0]["site_id"], "horizon": "daily"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def alerts(client: TestClient) -> list[dict]:
    response = client.get("/api/v1/tending/rounds")
    assert response.status_code == 200
    return response.json()["alerts"]


def tasks(client: TestClient, specimen_id: str) -> list[dict]:
    response = client.get("/api/v1/tending/tasks", params={"specimen_id": specimen_id})
    assert response.status_code == 200
    return response.json()


def frost_alert_for(client: TestClient, specimen_id: str) -> dict:
    found = [a for a in alerts(client) if a["specimen"]["id"] == specimen_id]
    assert found, "the frost scenario no longer alerts this plant"
    return found[0]


def test_every_actionable_alert_in_the_rounds_names_its_task(under_frost):
    """``task_id: null`` was the whole releases. Nothing actionable may carry it."""
    raised = [
        a for a in alerts(under_frost) if a["action"] in {"bring_indoors", "cover"}
    ]
    assert raised
    for alert in raised:
        assert alert["task_id"], alert
        named = [
            t
            for t in tasks(under_frost, alert["specimen"]["id"])
            if t["id"] == alert["task_id"]
        ]
        assert len(named) == 1
        assert named[0]["task_type"] == alert["action"]
        assert named[0]["all_day"] is False
        assert named[0]["priority"] == "urgent"


def test_the_task_is_due_by_the_sunset_the_almanac_states(under_frost):
    """Read out of the weather engine's own forecast, not copied out of the fixture."""
    alert = frost_alert_for(under_frost, LEMON)
    eve = (date.fromisoformat(alert["night_of"]) - timedelta(days=1)).isoformat()
    days = daily_forecast(under_frost)
    sunset = next(d["sunset"] for d in days if str(d["time"]).startswith(eve))
    task = next(t for t in tasks(under_frost, LEMON) if t["id"] == alert["task_id"])
    assert task["due_at"] == sunset


def test_the_frost_task_reaches_the_rounds_on_the_day_it_has_to_be_done(under_frost):
    """A deadline after midnight UTC still belongs to the evening before it."""
    alert = frost_alert_for(under_frost, LEMON)
    eve = (date.fromisoformat(alert["night_of"]) - timedelta(days=1)).isoformat()
    rounds = under_frost.get("/api/v1/tending/rounds", params={"on": eve}).json()
    assert alert["task_id"] in [t["id"] for t in rounds["due"]]


def test_completing_a_bring_indoors_moves_the_specimen(under_frost):
    """The earlier exit criterion's last clause, through the inventory API's own endpoint."""
    alert = frost_alert_for(under_frost, LEMON)
    before = under_frost.get(f"/api/v1/specimens/{LEMON}").json()
    assert before["is_outdoor"] is True

    completed = under_frost.post(
        f"/api/v1/tending/tasks/{alert['task_id']}/complete",
        json={"new_location_id": INDOOR_SHELF},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"

    after = under_frost.get(f"/api/v1/specimens/{LEMON}").json()
    assert after["location"]["id"] == INDOOR_SHELF
    assert after["is_outdoor"] is False
    # And the schedule agrees with the Register, rather than going on calling it
    # an outdoor plant.
    moved = [t for t in tasks(under_frost, LEMON)]
    assert all(t["specimen"]["is_outdoor"] is False for t in moved)


def test_a_completed_frost_task_shows_its_alert_as_resolved(under_frost):
    alert = frost_alert_for(under_frost, LEMON)
    under_frost.post(
        f"/api/v1/tending/tasks/{alert['task_id']}/complete",
        json={"new_location_id": INDOOR_SHELF},
    )
    assert frost_alert_for(under_frost, LEMON)["state"] == "resolved"


def test_the_return_suggestion_appears_once_the_plant_is_inside(under_frost):
    """And it lands on the third of three forecast nights above its threshold."""
    alert = frost_alert_for(under_frost, LEMON)
    assert not [
        t for t in tasks(under_frost, LEMON) if t["task_type"] == "return_outdoors"
    ]

    under_frost.post(
        f"/api/v1/tending/tasks/{alert['task_id']}/complete",
        json={"new_location_id": INDOOR_SHELF},
    )
    back = [t for t in tasks(under_frost, LEMON) if t["task_type"] == "return_outdoors"]
    assert len(back) == 1

    # Checked against the Almanac's forecast and the alert's own threshold, so
    # this survives L re-cutting the recording.
    due = date.fromisoformat(back[0]["due_at"][:10])
    threshold = alert["threshold_c"]
    lows = {
        date.fromisoformat(str(d["time"])[:10]): d["temp_min_c"]
        for d in daily_forecast(under_frost)
    }
    run = [due - timedelta(days=n) for n in (2, 1, 0)]
    assert all(lows[day] > threshold for day in run)
    assert all(day > date.fromisoformat(alert["night_of"]) for day in run)
    # ...and it is the *first* such run: the night before the run is not mild.
    assert lows.get(run[0] - timedelta(days=1), -99.0) <= threshold


def test_a_water_completion_that_names_a_location_is_refused(under_frost):
    """The contract sets ``new_location_id`` on a bring_indoors completion."""
    watering = next(
        t
        for t in under_frost.get("/api/v1/tending/rounds").json()["due"]
        if t["task_type"] == "water"
    )
    response = under_frost.post(
        f"/api/v1/tending/tasks/{watering['id']}/complete",
        json={"new_location_id": INDOOR_SHELF},
    )
    assert response.status_code == 422
    assert "bring_indoors" in response.json()["detail"]
    # And nothing was ticked off on the way to refusing it.
    assert under_frost.get(
        "/api/v1/tending/tasks", params={"specimen_id": watering["specimen"]["id"]}
    ).json()


def test_a_completion_naming_a_location_nobody_has_is_refused(under_frost):
    alert = frost_alert_for(under_frost, LEMON)
    response = under_frost.post(
        f"/api/v1/tending/tasks/{alert['task_id']}/complete",
        json={"new_location_id": "01890010-0000-7000-8000-00000000dead"},
    )
    assert response.status_code == 422
    assert under_frost.get(f"/api/v1/specimens/{LEMON}").json()["is_outdoor"] is True
    assert (
        next(t for t in tasks(under_frost, LEMON) if t["id"] == alert["task_id"])[
            "status"
        ]
        == "due"
    )


# ------------------------------------------------------- and in somebody's calendar


def feed_document(client: TestClient) -> str:
    """A fresh subscription, fetched the way a calendar client fetches it."""
    members = client.get("/api/v1/members").json()
    created = client.post(
        "/api/v1/tending/feeds",
        json={"member_id": members[0]["id"], "name": "Frost watch"},
    )
    assert created.status_code == 201, created.text
    url = created.json()["https_url"]
    response = client.get(url[url.index("/api/v1") :])
    assert response.status_code == 200
    return response.text


def vevents(document: str) -> dict[str, list[str]]:
    """``{uid: the event's unfolded lines}``, which is all these tests need."""
    unfolded = document.replace("\r\n ", "").replace("\r\n\t", "").split("\r\n")
    events: dict[str, list[str]] = {}
    current: list[str] = []
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            current = []
        elif line == "END:VEVENT":
            uid = next(
                (ln.split(":", 1)[1] for ln in current if ln.startswith("UID:")), ""
            )
            events[uid] = current
        else:
            current.append(line)
    return events


def uid_for(task_id: str) -> str:
    return f"task-{task_id}@herbology"


def test_the_frost_task_is_a_timed_event_with_a_reminder(under_frost):
    """The plan: frost tasks are timed events with a reminder, routine work is not."""
    alert = frost_alert_for(under_frost, LEMON)
    event = vevents(feed_document(under_frost))[uid_for(alert["task_id"])]
    body = "\r\n".join(event)
    assert "DTSTART;VALUE=DATE:" not in body, "a frost task is not an all-day event"
    assert "DTSTART:" in body
    assert "PRIORITY:1" in event
    assert "BEGIN:VALARM" in body and "TRIGGER:-PT2H" in body
    assert "STATUS:CONFIRMED" in event
    # And the reason it exists travels with it, for a reader who never opens the
    # app. Commas are escaped in an ICS TEXT value, hence
    # the fragment.
    assert "not a measurement" in body
    assert f"{alert['threshold_c']:g} " in body


def test_a_withdrawn_frost_task_is_cancelled_by_uid_rather_than_dropped(
    under_frost, monkeypatch: pytest.MonkeyPatch
):
    """A forecast that changes is the normal case, not the exception.

    The alert source is what warms here: with the guard raising nothing, the task
    it justified has to leave the subscriber's calendar — and the only way a
    subscribed feed can say "this one is gone" is to say so, by UID, with a later
    ``SEQUENCE`` than the event they already hold.
    """
    from tending import environment as env

    alert = frost_alert_for(under_frost, LEMON)
    uid = uid_for(alert["task_id"])
    before = vevents(feed_document(under_frost))[uid]
    assert "STATUS:CONFIRMED" in before

    monkeypatch.setattr(env, "fixture_frost_alerts", lambda: [])
    event = vevents(feed_document(under_frost))[uid]
    assert "STATUS:CANCELLED" in event, "the event must be withdrawn, not dropped"
    assert "BEGIN:VALARM" not in "\r\n".join(event), "no reminder for a dead event"
    assert _sequence(event) > _sequence(before)
    body = "\r\n".join(event)
    assert "a change in the forecast" in body
    assert "no longer forecasts a night cold enough" in body

    # On the screen it is *satisfied*, not vanished: the household was asked to
    # carry a tree indoors and is owed the news that it is off.
    task = next(t for t in tasks(under_frost, LEMON) if t["id"] == alert["task_id"])
    assert task["status"] == "satisfied"
    assert task["satisfied_by"] == "forecast_change"
    # The alert itself is gone, because the weather engine is no longer raising it. That is the
    # weather engine's
    # half of the withdrawal and it is why the task had to carry the news.
    assert not [a for a in alerts(under_frost) if a["specimen"]["id"] == LEMON]


def _sequence(event: list[str]) -> int:
    return int(
        next(line.split(":", 1)[1] for line in event if line.startswith("SEQUENCE:"))
    )


def test_a_frost_task_that_was_done_is_not_withdrawn_behind_the_household(
    under_frost, monkeypatch: pytest.MonkeyPatch
):
    """Withdrawal may not rewrite a task somebody has already acted on."""
    from tending import environment as env

    alert = frost_alert_for(under_frost, LEMON)
    under_frost.post(
        f"/api/v1/tending/tasks/{alert['task_id']}/complete",
        json={"new_location_id": INDOOR_SHELF},
    )
    monkeypatch.setattr(env, "fixture_frost_alerts", lambda: [])
    task = next(t for t in tasks(under_frost, LEMON) if t["id"] == alert["task_id"])
    assert task["status"] == "done"


def test_a_withdrawn_task_moves_to_the_satisfied_half_of_the_rounds(
    under_frost, monkeypatch: pytest.MonkeyPatch
):
    """Beside the rain-satisfied waterings, not off the screen.

    The plan is explicit that rain marks a watering satisfied on screen rather
    than hiding it, while the calendar cancels the event. A frost task the
    forecast has withdrawn is the same shape of news and gets the same treatment.
    """
    from tending import environment as env

    alert = frost_alert_for(under_frost, LEMON)
    eve = (date.fromisoformat(alert["night_of"]) - timedelta(days=1)).isoformat()
    monkeypatch.setattr(env, "fixture_frost_alerts", lambda: [])

    rounds = under_frost.get("/api/v1/tending/rounds", params={"on": eve}).json()
    assert alert["task_id"] in [t["id"] for t in rounds["satisfied"]]
    assert alert["task_id"] not in [t["id"] for t in rounds["due"]]
