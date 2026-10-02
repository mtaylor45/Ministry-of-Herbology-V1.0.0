"""The fixtures' own ``expect`` blocks, asserted against the running app.

``expect`` block is the contract: ``tests/`` asserts each one". Until parts of the project
The weather engine's scenario selector landed nothing could: the running app only ever saw
``weather/baseline_30d.json``, so an expectation could be checked against the
engine's arithmetic — which ``tests/engines/`` does — but never against a
screen. This file is the promise kept.

The seam is ``MOH_SCENARIO`` and ``MOH_SCENARIO_DAY``, set
through the environment because that is the only route a deployment has. It is not a test hook: an
operator who wants to watch 38 mm of rain
clear a due watering before trusting the app with their garden takes exactly
this path, and a suite that reached past it into a settings object would prove
only that the private route works.

Each scenario is read on the day its own ``expect`` block names. That matters
for ``storm``: the balance reports the state of its newest day, and the
recording runs three days past the downpour, so a round read at the end
honestly says ``ok`` and the satisfied state is gone.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import (  # type: ignore[import-not-found]
    expectations,
    ics_events,
    rain_day_of,
    scenario_day,
    subscribe,
    tasks_by_specimen,
)


def rounds(client: Any, on: str) -> dict[str, Any]:
    response = client.get("/api/v1/tending/rounds", params={"on": on})
    assert response.status_code == 200, response.text
    return dict(response.json())


def balance(client: Any, specimen_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/almanac/water-balance/{specimen_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def assert_expectation(client: Any, row: dict[str, Any], on: str, *, name: str) -> None:
    """One ``expect.assertions`` row, checked on the app rather than the engine."""
    specimen_id = row["specimen"]
    expected = row["water_task_status"]
    note = row.get("note", "")
    where = f"{name}: {specimen_id} ({note})"

    payload = rounds(client, on)
    due = tasks_by_specimen(payload["due"])
    satisfied = tasks_by_specimen(payload["satisfied"])

    if expected == "satisfied":
        assert specimen_id in satisfied, where
        task = satisfied[specimen_id]
        assert task["status"] == "satisfied", where
        assert task["satisfied_by"] == row.get("satisfied_by", "rain"), where
        assert specimen_id not in due, where
    elif expected == "due":
        assert specimen_id in due, where
        assert due[specimen_id]["status"] == "due", where
        assert due[specimen_id]["satisfied_by"] is None, where
        assert specimen_id not in satisfied, where
    elif expected == "ok":
        # Never owed, so never settled. "ok" is not "satisfied", and keeping
        # them apart is what makes the satisfied section mean anything.
        modelled = balance(client, specimen_id)
        assert modelled["status"] == "ok", where
        assert modelled["satisfied_by"] is None, where
        assert modelled["is_due"] is False, where
        assert specimen_id not in satisfied, where
        assert specimen_id not in due, where
    else:  # pragma: no cover — a fixture that says something new
        raise AssertionError(f"unknown expectation {expected!r}: {row}")


# ------------------------------------------------------------------- storm


@pytest.mark.parametrize(
    "row", expectations("storm"), ids=lambda row: str(row["specimen"])[-3:]
)
def test_the_storm_expectations_hold_on_the_running_app(
    storm: Any, row: dict[str, Any]
) -> None:
    assert_expectation(storm, row, rain_day_of("storm"), name="storm")


def test_the_storm_settles_something_and_leaves_something_owed(storm: Any) -> None:
    """A scenario where everything cleared, or nothing did, tests one branch."""
    payload = rounds(storm, rain_day_of("storm"))
    assert payload["satisfied"], "38 mm of rain settled nothing, so it is not a storm"
    assert payload["due"], "everything settled, so nothing exercises the other half"


def test_the_storm_cancels_its_settled_waterings_in_the_calendar(storm: Any) -> None:
    settled = rounds(storm, rain_day_of("storm"))["satisfied"]
    events = ics_events(storm.get(subscribe(storm)).text)
    for task in settled:
        uid = f"task-{task['id']}@herbology"
        assert uid in events, "a settled watering was dropped, not cancelled"
        assert events[uid]["STATUS"] == "CANCELLED", events[uid]


# ----------------------------------------------------------------- drought


#: Expectations the running app cannot currently meet, with the diagnosis.
#:
#: `api/almanac/service.py` replays `BALANCE_DAYS = 14` days from a zero
#: deficit. That caps how *slowly* a plant may dry and still be noticed: the
#: drought-adapted lavender hedge needs 15 days of this weather to cross its
#: 36 mm threshold (`tests/engines/` confirms the engine reaches it on day 15
#: over the full recording, and the fixture has promised `by_day: 15` since
#: an earlier release), so the endpoint stops one day short and reports `ok` however long the
#: drought runs. Under the design this endpoint is the only thing that decides
#: whether an outdoor plant is watered, so a plant that dries slowly is a plant
#: the app never asks anybody to water.
#:
#: The live path stores the deficit per day and carries it forward, so it does
#: not reset — but the mock path is what every demo, every screen J builds and
#: this suite run on. `api/almanac/` is the weather engine's, so this is escalated
#: rather than worked around. Strict, so it fails the day it starts passing.
#: Empty, and kept empty deliberately.
#:
#: The lavender hedge lived here: the Almanac replayed only `BALANCE_DAYS = 14`
#: days from a zero deficit, so an in-ground plant on a deep profile needed 15
#: days to cross its threshold and could never be reported due through the API
#: — it read `ok` however long the drought ran. The weather engine fixed it in #34:
#: the replay now covers the whole recording and only the per-day array is
#: trimmed for the screen. The entry's own instruction was "delete this entry
#: when the window carries a starting deficit", and it now does.
#:
#: The machinery stays because the escalation worked: a fixture promise the API
#: cannot keep is recorded here, strictly, so it fails the day it starts
#: passing. That is exactly how this one was found and closed.
CANNOT_YET_BE_MET: dict[str, str] = {}


def drought_rows() -> list[Any]:
    return [
        (
            pytest.param(
                row,
                id=str(row["specimen"])[-3:],
                marks=pytest.mark.xfail(
                    strict=True, reason=CANNOT_YET_BE_MET[row["specimen"]]
                ),
            )
            if row["specimen"] in CANNOT_YET_BE_MET
            else pytest.param(row, id=str(row["specimen"])[-3:])
        )
        for row in expectations("drought")
    ]


@pytest.mark.parametrize("row", drought_rows())
def test_the_drought_expectations_hold_on_the_running_app(
    drought: Any, row: dict[str, Any]
) -> None:
    """Each `by_day` promise, read on the last day of three rainless weeks."""
    assert row["water_task_status"] == "due", row
    assert_expectation(drought, row, scenario_day("drought", -1), name="drought")


def test_a_drought_never_reports_a_watering_the_sky_did(drought: Any) -> None:
    """``satisfied_by_rain_count: 0`` — the fixture's own last assertion."""
    payload = rounds(drought, scenario_day("drought", -1))
    assert payload["satisfied"] == [], (
        "no rain fell in three weeks, so nothing may be reported as settled "
        f"by the weather: {payload['satisfied']}"
    )
    for task in payload["due"]:
        assert task["satisfied_by"] is None


def test_a_drought_does_not_grow_more_certain_as_it_goes_on(drought: Any) -> None:
    """Three weeks of arithmetic about unmeasured soil is still arithmetic."""
    payload = rounds(drought, scenario_day("drought", -1))
    for task in payload["due"]:
        assert task["confidence"] != "high", (
            f"{task['specimen']['display_name']} claims a measured certainty "
            "for a modelled deficit"
        )


def test_a_drought_leaves_the_deficit_climbing(drought: Any) -> None:
    """Nothing reduces a deficit but rain that lands or water somebody pours.

    True of every plant the drought names, including the one the 14-day window
    stops short of calling due: its deficit still only climbs.
    """
    for row in expectations("drought"):
        payload = balance(drought, row["specimen"])
        deficits = [day["deficit_mm"] for day in payload["days"]]
        assert deficits == sorted(deficits), (row["specimen"], deficits)
        assert not [
            day for day in payload["days"] if day["status"] == "satisfied"
        ], "no day of a rainless fortnight may be reported as settled"


# ------------------------------------------------- the switch is opt-in


def test_a_scenario_does_not_outlive_the_request_that_asked_for_it(
    client: Any,
) -> None:
    """The default deployment sees the baseline, whatever a previous test set.

    The weather engine's suite pins this from its own side; it is asserted here too
    because this file is the one that sets the environment variable, and a
    leaked scenario would quietly make every other test in `tests/e2e/` a test
    of the storm.
    """
    payload = client.get("/api/v1/tending/rounds").json()
    assert payload["satisfied"] == [], (
        "a scenario leaked out of its fixture: the baseline recording settles "
        "no waterings, which is what makes the selector opt-in"
    )
