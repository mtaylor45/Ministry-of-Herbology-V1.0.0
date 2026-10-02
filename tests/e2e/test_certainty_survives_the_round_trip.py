"""A degraded input must produce a visibly degraded output, all the way out.

``degradations`` **required** on ``Task``, ``WaterBalance`` and ``FrostAlert``,
and ``unscheduled`` required on ``MorningRounds``. the design and the design say
why: nothing measures the soil, so the water balance is the only
thing deciding whether an outdoor plant gets watered, and a number that arrives
without its caveats is a degraded answer wearing a clean one's clothes.

This module follows one uncertainty from the fixture that causes it, through
the Almanac, through Morning Rounds, into the ICS document a calendar client
downloads — and fails if it is laundered clean at any hop. If the app is ever
more confident than its inputs justify, this is the suite that is supposed to
catch it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from conftest import (  # type: ignore[import-not-found]
    LEMON_ON_THE_TERRACE,
    MANDRAKE_IN_THE_GREENHOUSE,
    confidence_rank,
    ics_events,
    rain_day_of,
    subscribe,
    tasks_by_specimen,
)

#: A plant whose watering interval carries no citation at all. the design is
#: specific that this is ``unknown`` and not ``low``: ``low`` says "we measured
#: badly", ``unknown`` says "nobody has said".
UNCITED_INTERVAL = MANDRAKE_IN_THE_GREENHOUSE


def rounds(client: Any, on: str | None = None) -> dict[str, Any]:
    response = client.get("/api/v1/tending/rounds", params={"on": on} if on else {})
    assert response.status_code == 200, response.text
    return dict(response.json())


def every_task(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload["due"]) + list(payload["satisfied"])


# ------------------------------------------- the contract, on live responses


def test_every_answer_the_app_serves_carries_its_certainty(
    client: Any, contract: Any, weather_last_day: str
) -> None:
    """1.3.0's required fields, checked against what the app actually sends."""
    payload = rounds(client, weather_last_day)
    contract(payload, "MorningRounds")
    assert isinstance(payload["unscheduled"], list)

    tasks = every_task(payload)
    assert tasks, "a round with no tasks proves nothing about tasks"
    for task in tasks:
        contract(task, "Task")
        assert task["confidence"] in {"high", "medium", "low", "unknown"}
        assert isinstance(task["degraded"], bool)
        assert isinstance(task["degradations"], list)
        assert task["degraded"] == bool(task["degradations"]), (
            f"{task['specimen']['display_name']}: `degraded` and "
            "`degradations` disagree, so one of them is decoration"
        )
        for row in task["degradations"]:
            contract(row, "Degradation")
            assert row["detail"].strip(), (
                "a degradation with no sentence in it cannot be shown to "
                "anybody, which makes it an invisible caveat"
            )

    for specimen_id in {task["specimen"]["id"] for task in tasks}:
        contract(
            client.get(f"/api/v1/almanac/water-balance/{specimen_id}").json(),
            "WaterBalance",
        )

    frost = client.get("/api/v1/almanac/frost")
    assert frost.status_code == 200, frost.text
    for alert in frost.json()["alerts"]:
        contract(alert, "FrostAlert")


# ------------------------------------------------- one uncertainty, followed


def test_an_uncited_interval_is_marked_unknown_where_a_reader_will_see_it(
    client: Any, weather_last_day: str
) -> None:
    """The no-invented-plant-facts rule and the design, on the screen rather than in a field nobody
    reads."""
    due = tasks_by_specimen(rounds(client, weather_last_day)["due"])
    task = due[UNCITED_INTERVAL]

    assert task["confidence"] == "unknown", (
        "a watering interval nobody cited must not be presented at the same "
        f"confidence as one that was — got {task['confidence']!r}"
    )
    assert task["degraded"] is True
    codes = {row["code"] for row in task["degradations"]}
    assert "interval_uncited" in codes, codes
    assert task["detail"] and "guess" in task["detail"].lower(), (
        "`detail` is the field every released client already renders; an "
        "uncited value that is only flagged in a new field is not visibly "
        f"marked to anybody — got {task['detail']!r}"
    )


def test_stale_weather_makes_the_answer_less_certain_and_says_so(
    storm: Any,
) -> None:
    """The same plant, the same recording, a balance that no longer reaches today.

    Nothing has advanced the deficit since the weather ran out, so the plant is
    drier than the number says. The app has to lose confidence over that and
    name the reason; an answer that stayed at ``medium`` would be claiming a
    currency it has not got.
    """
    fresh_day = rain_day_of("storm")
    stale_day = (date.fromisoformat(fresh_day) + timedelta(days=49)).isoformat()

    current = tasks_by_specimen(rounds(storm, fresh_day)["satisfied"])[
        LEMON_ON_THE_TERRACE
    ]
    stale = tasks_by_specimen(rounds(storm, stale_day)["satisfied"])[
        LEMON_ON_THE_TERRACE
    ]

    assert current["degraded"] is False and current["degradations"] == []
    assert current["confidence"] == "medium", (
        "a modelled deficit is never better than medium — it is a calculation "
        "about soil nobody has measured"
    )

    assert stale["degraded"] is True
    assert confidence_rank(stale["confidence"]) > confidence_rank(
        current["confidence"]
    ), (
        f"the same balance read {stale['confidence']!r} against weather that "
        f"stops seven weeks short and {current['confidence']!r} against "
        "weather that reaches the day — staleness has to cost something"
    )
    codes = {row["code"] for row in stale["degradations"]}
    assert "balance_not_current" in codes, codes
    assert stale["detail"] and stale["detail"].strip()


def test_no_task_is_more_certain_than_the_balance_it_was_built_from(
    client: Any, weather_last_day: str
) -> None:
    """Certainty may be lost along a chain. It may never be gained."""
    payload = rounds(client, weather_last_day)
    for task in every_task(payload):
        specimen_id = task["specimen"]["id"]
        modelled = client.get(f"/api/v1/almanac/water-balance/{specimen_id}").json()
        if not modelled["applies"]:
            continue
        assert confidence_rank(task["confidence"]) >= confidence_rank(
            modelled["confidence"]
        ), (
            f"{task['specimen']['display_name']}: the task claims "
            f"{task['confidence']!r} from a balance worth "
            f"{modelled['confidence']!r}"
        )
        balance_codes = {row["code"] for row in modelled["degradations"]}
        task_codes = {row["code"] for row in task["degradations"]}
        assert balance_codes <= task_codes, (
            "the balance's own reasons were dropped on the way to the task: "
            f"{sorted(balance_codes - task_codes)}"
        )


def test_the_caveat_reaches_the_calendar_too(client: Any) -> None:
    """A subscriber who never opens the app still has to be told.

    The structured fields ride as ``X-`` properties, but a client that renders
    none of them still sees ``DESCRIPTION`` — so the plain sentence has to be
    in there, not only in a header no calendar shows.

    The round is asked for without a date here, because the feed renders
    against the same clock: an occurrence's identity is anchored to real days,
    so comparing a round pinned to the fixture's last day against a feed
    rendered today would compare two different occurrences of the same rule.
    """
    response = client.get("/api/v1/tending/rounds")
    assert response.status_code == 200, response.text
    task = tasks_by_specimen(response.json()["due"])[UNCITED_INTERVAL]

    events = ics_events(client.get(subscribe(client)).text)
    event = events[f"task-{task['id']}@herbology"]

    assert event["X-MOH-CONFIDENCE"] == "unknown", event
    assert event["X-MOH-DEGRADED"] == "TRUE", event
    assert "guess" in event["DESCRIPTION"].lower(), (
        "the caveat is in an X- property only, so every calendar client alive "
        f"shows this task as an unqualified instruction: {event['DESCRIPTION']}"
    )
