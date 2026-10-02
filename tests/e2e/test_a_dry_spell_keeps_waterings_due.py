"""The drought half of the exit criterion, end to end.

the site — so the two plants on the Covered Porch are living through a drought
inside the shipped fixtures, and the app's answer for them is the drought
answer: the deficit only grows, the watering comes due, and it *stays* due
until somebody does it.

The second half of the brief matters as much as the first: the app must not
quietly invent certainty it has not got. Under the design nothing measures the
soil in v1.0 and nothing is expected to, so every watering this app asks for is
a model's opinion about the weather. The last two tests here are what fails if
that ever stops being said out loud.
"""

from __future__ import annotations

from typing import Any

from conftest import (  # type: ignore[import-not-found]
    KEEPER_ID,
    LAVENDER_ON_THE_PORCH,
    LEMON_ON_THE_PORCH,
    MANDRAKE_IN_THE_GREENHOUSE,
    confidence_rank,
    tasks_by_specimen,
)

#: Outdoor, but roofed: `f_cover = 0`, so these two are in a drought of their
#: own however wet the site gets.
IN_A_DRY_SPELL = (LEMON_ON_THE_PORCH, LAVENDER_ON_THE_PORCH)


def rounds(client: Any, on: str) -> dict[str, Any]:
    response = client.get("/api/v1/tending/rounds", params={"on": on})
    assert response.status_code == 200, response.text
    return dict(response.json())


def balance(client: Any, specimen_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/almanac/water-balance/{specimen_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_the_deficit_only_accumulates_while_no_water_arrives(
    client: Any, contract: Any
) -> None:
    """Nothing reduces a deficit but rain that lands or water somebody pours."""
    for specimen_id in IN_A_DRY_SPELL:
        payload = balance(client, specimen_id)
        contract(payload, "WaterBalance")

        deficits = [day["deficit_mm"] for day in payload["days"]]
        assert deficits == sorted(deficits), (
            f"{specimen_id} is under a roof and nobody watered it, so its "
            f"deficit cannot fall: {deficits}"
        )
        assert all(day["irrigation_mm"] == 0 for day in payload["days"])
        assert not [
            day for day in payload["days"] if day["status"] == "satisfied"
        ], "no day of a dry spell may be reported as settled by the weather"
        assert payload["deficit_mm"] >= payload["threshold_mm"]
        assert payload["is_due"] is True


def test_a_watering_that_is_due_stays_due(client: Any, weather_last_day: str) -> None:
    """Asking twice must not change the answer, or mint a second task.

    Generation runs on every read. If it were not idempotent, every refresh of Morning
    Rounds would add another watering to the round and another event to every
    subscribed calendar.
    """
    first = tasks_by_specimen(rounds(client, weather_last_day)["due"])
    second = tasks_by_specimen(rounds(client, weather_last_day)["due"])

    for specimen_id in IN_A_DRY_SPELL:
        assert specimen_id in first and specimen_id in second
        assert (
            first[specimen_id]["id"] == second[specimen_id]["id"]
        ), "the outstanding watering was reissued under a new identity"
        assert second[specimen_id]["status"] == "due"

    listed = client.get(
        "/api/v1/tending/tasks",
        params={"status": "due", "specimen_id": LEMON_ON_THE_PORCH},
    )
    assert listed.status_code == 200, listed.text
    open_waterings = [task for task in listed.json() if task["task_type"] == "water"]
    assert len(open_waterings) == 1, (
        "one plant owes one outstanding watering, not one per day it has been "
        f"owed: {open_waterings}"
    )


def test_completing_the_watering_is_logged_and_attributed(
    client: Any, weather_last_day: str
) -> None:
    """The other way a due watering leaves the round — and who did it."""
    due = tasks_by_specimen(rounds(client, weather_last_day)["due"])
    task = due[LEMON_ON_THE_PORCH]

    response = client.post(
        f"/api/v1/tending/tasks/{task['id']}/complete",
        json={"completed_by": KEEPER_ID, "amount_ml": 500},
    )
    assert response.status_code == 200, response.text
    completed = response.json()
    assert completed["status"] == "done"
    assert completed["completed_by"]["id"] == KEEPER_ID
    assert completed["satisfied_by"] is None, (
        "a person with a watering can is not the weather; only rain that fell "
        "may be attributed to rain"
    )
    assert completed["id"] == task["id"], "completion must not reissue the task"


def test_completing_the_watering_takes_it_off_the_round(
    client: Any, weather_last_day: str
) -> None:
    """Watering a plant must settle it, not merely log that somebody tried."""
    due = tasks_by_specimen(rounds(client, weather_last_day)["due"])
    response = client.post(
        f"/api/v1/tending/tasks/{due[LEMON_ON_THE_PORCH]['id']}/complete",
        json={"completed_by": KEEPER_ID, "amount_ml": 500},
    )
    assert response.status_code == 200, response.text

    after = rounds(client, weather_last_day)
    assert LEMON_ON_THE_PORCH not in tasks_by_specimen(
        after["due"]
    ), "the plant was watered and the app immediately asked again"
    assert LEMON_ON_THE_PORCH not in tasks_by_specimen(after["satisfied"])


def test_a_plant_the_round_cannot_speak_for_is_named_rather_than_dropped(
    client: Any, contract: Any, a_day_the_mandrake_is_dormant: str
) -> None:
    """Silence has two meanings, and ``unscheduled`` is what separates them.

    A dormant plant is off the schedule, not on a longer one. Without this list
    it would simply be missing from the round, and missing is what a thriving
    plant that needs nothing also looks like.
    """
    payload = rounds(client, a_day_the_mandrake_is_dormant)
    contract(payload, "MorningRounds")

    unscheduled = {row["specimen_id"]: row["reason"] for row in payload["unscheduled"]}
    assert (
        MANDRAKE_IN_THE_GREENHOUSE in unscheduled
    ), "a dormant plant dropped out of the round without a word"
    assert unscheduled[MANDRAKE_IN_THE_GREENHOUSE].strip(), "a reason with no words"
    assert MANDRAKE_IN_THE_GREENHOUSE not in tasks_by_specimen(payload["due"])
    assert MANDRAKE_IN_THE_GREENHOUSE not in tasks_by_specimen(payload["satisfied"])


def test_no_watering_the_model_asked_for_claims_to_be_measured(
    client: Any, weather_last_day: str
) -> None:
    """nothing measures the soil, so nothing may say it did.

    ``high`` is the level reserved for a figure something actually observed.
    Every watering this app asks for is arithmetic over weather, and the day
    one of them arrives claiming ``high`` is the day somebody has quietly
    started treating a model as a measurement.
    """
    payload = rounds(client, weather_last_day)
    overconfident = []
    for task in payload["due"] + payload["satisfied"]:
        specimen_id = task["specimen"]["id"]
        modelled = balance(client, specimen_id)
        if not modelled["applies"]:
            continue  # an indoor pot on an interval rule; no soil model at all
        assert modelled["confidence"] != "high", specimen_id
        if task["confidence"] == "high":
            overconfident.append(specimen_id)
        assert confidence_rank(task["confidence"]) >= confidence_rank(
            modelled["confidence"]
        ), (
            f"{specimen_id}: the task is more certain ({task['confidence']}) "
            f"than the balance it was built from ({modelled['confidence']})"
        )
    assert not overconfident, overconfident


def test_the_app_says_the_soil_has_not_been_measured(client: Any) -> None:
    """The sensor-override seam the design says to keep, reported as empty.

    No moisture hardware exists in v1.0. The field is in the response because
    the day one appears the override has to already work — and until then it
    must read ``null``, not a plausible percentage.
    """
    for specimen_id in IN_A_DRY_SPELL:
        assert balance(client, specimen_id)["sensor_override_pct"] is None
