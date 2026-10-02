"""The water-balance engine, run against the frozen weather scenarios.

written so E builds towards something concrete rather than towards a
description.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workers.weather.tasks import (
    BalanceInputs,
    capacity_mm,
    is_watering_due,
    step_deficit,
)

LEMON_ON_TERRACE = "01890040-0000-7000-8000-000000000004"  # 45 L container, open sky
LEMON_ON_PORCH = "01890040-0000-7000-8000-000000000005"  # 25 L container, covered
LAVENDER_HEDGE = "01890040-0000-7000-8000-000000000006"  # in ground, drought-adapted
ROSE = "01890040-0000-7000-8000-000000000007"  # in ground


def _fixture(repo_root, relative):
    return json.loads((repo_root / "fixtures" / relative).read_text())


def rain_day(scenario) -> int:
    """The index of the scenario's soaking, read from the days themselves.

    Hardcoded here where lengthening the storm's dry spell moved the
    wet day and these tests went red for a reason that had nothing to do with
    the engine. The fixture declares the index too, in ``expect.rain_day_index``,
    and the two are checked against each other below: a fixture whose prose and
    whose weather disagree is worse than one that is merely wrong.
    """
    wet = [index for index, day in enumerate(scenario["days"]) if day["precip_mm"] > 0]
    assert len(wet) == 1, f"the storm is one soaking, not {len(wet)}"
    return wet[0]


@pytest.fixture
def world(repo_root):
    species = {s["id"]: s for s in _fixture(repo_root, "species/species.json")}
    locations = {
        location["id"]: location
        for location in _fixture(repo_root, "locations/locations.json")
    }
    specimens = {s["id"]: s for s in _fixture(repo_root, "specimens/specimens.json")}
    return species, locations, specimens


def run_scenario(scenario, specimen, species, location):
    """Replay a scenario day by day, returning the day index each watering fell due."""
    capacity = capacity_mm(specimen["in_container"], specimen.get("container_litres"))
    k_c = species["water_k_c"]
    cover = 0.0 if location["is_covered"] else 1.0
    deficit = 0.0
    due_on: list[int] = []
    for index, day in enumerate(scenario["days"]):
        deficit = step_deficit(
            deficit,
            BalanceInputs(
                et0_mm=day["et0_mm"], precip_mm=day["precip_mm"], cover_factor=cover
            ),
            k_c,
            capacity,
        )
        if is_watering_due(deficit, capacity):
            due_on.append(index)
    return due_on, deficit, capacity


def test_drought_dries_containers_before_open_ground(repo_root, world):
    species, locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/drought.json")

    first_due = {}
    for specimen_id in (LEMON_ON_TERRACE, ROSE, LAVENDER_HEDGE):
        specimen = specimens[specimen_id]
        due_on, _, _ = run_scenario(
            scenario,
            specimen,
            species[specimen["species_id"]],
            locations[specimen["location_id"]],
        )
        assert due_on, f"{specimen['id']} never came due in the drought"
        first_due[specimen_id] = due_on[0]

    assert first_due[LEMON_ON_TERRACE] < first_due[ROSE] < first_due[LAVENDER_HEDGE], (
        "a 45 L container must dry before open ground, and a drought-adapted "
        f"lavender last of all — got {first_due}"
    )


@pytest.mark.parametrize("specimen_id", [LEMON_ON_TERRACE, ROSE, LAVENDER_HEDGE])
def test_drought_meets_its_stated_deadline(repo_root, world, specimen_id):
    """Each `by_day` in the fixture is a promise the engine has to keep."""
    species, locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/drought.json")
    promised = next(
        a["by_day"]
        for a in scenario["expect"]["assertions"]
        if a.get("specimen") == specimen_id
    )
    specimen = specimens[specimen_id]
    due_on, _, _ = run_scenario(
        scenario,
        specimen,
        species[specimen["species_id"]],
        locations[specimen["location_id"]],
    )
    assert due_on[0] <= promised, (
        f"{specimen['nickname'] or specimen_id} came due on day {due_on[0]}, "
        f"but the scenario promises by day {promised}"
    )


def test_the_storm_fixture_agrees_with_itself(repo_root):
    """`expect.rain_day_index` is prose about the weather; check it against it."""
    scenario = _fixture(repo_root, "scenarios/storm.json")
    wet = rain_day(scenario)
    assert scenario["expect"]["rain_day_index"] == wet
    assert all(
        assertion["on_day"] == wet
        for assertion in scenario["expect"]["assertions"]
        if "on_day" in assertion
    ), "every per-specimen expectation is about the day it rained"


def test_the_storm_runs_on_past_its_downpour(repo_root):
    """And says so, because reading it on the wrong day gives the wrong answer.

    The balance reports the state of its *newest* day. Replayed to the end of
    this recording the deficit has begun to rebuild and the series honestly
    says `ok`, so the satisfied state the scenario exists to show is gone.
    Standing on the day it rained is the weather engine's `MOH_SCENARIO_DAY`, and the fixture's
    `expect` block names it rather than leaving the
    reader to discover it.

    Trimming the trailing days would hide that instead of explaining it — and
    would delete the one case the weather engine's day-setting was built for.
    """
    scenario = _fixture(repo_root, "scenarios/storm.json")
    assert rain_day(scenario) < len(scenario["days"]) - 1
    assert "MOH_SCENARIO_DAY" in scenario["expect"]["read_on_the_rain_day"]


def test_storm_rain_relieves_open_air_plants(repo_root, world):
    species, _locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/storm.json")
    wet = rain_day(scenario)
    specimen = specimens[LEMON_ON_TERRACE]
    capacity = capacity_mm(specimen["in_container"], specimen["container_litres"])
    k_c = species[specimen["species_id"]]["water_k_c"]

    deficit = 0.0
    before = after = None
    for index, day in enumerate(scenario["days"]):
        if index == wet:
            before = deficit
        deficit = step_deficit(
            deficit,
            BalanceInputs(
                et0_mm=day["et0_mm"], precip_mm=day["precip_mm"], cover_factor=1.0
            ),
            k_c,
            capacity,
        )
        if index == wet:
            after = deficit

    assert before is not None and is_watering_due(
        before, capacity
    ), "the dry spell should have left the lemon due for water"
    assert after == 0.0, "38 mm of rain should clear the deficit entirely"
    assert not is_watering_due(after, capacity)


def test_storm_rain_does_not_relieve_a_plant_that_was_never_thirsty(repo_root, world):
    """ "Satisfied" is a watering the sky did for you. This one was never owed.

    The drought-adapted lavender hedge does not cross its threshold in the
    storm's dry spell, so the rain settles nothing it owed. An engine that
    reported it as satisfied would be claiming credit for work nobody needed —
    and would make "satisfied" useless as a signal, because it would no longer
    distinguish a task the weather cleared from a task that never existed.
    """
    species, locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/storm.json")
    specimen = specimens[LAVENDER_HEDGE]
    location = locations[specimen["location_id"]]
    assert not location["is_covered"], "fixture drift: the hedge is under open sky"

    due_on, _, _ = run_scenario(
        scenario, specimen, species[specimen["species_id"]], location
    )
    assert not due_on, (
        "a drought-adapted plant in the ground must not be nagged after ten "
        f"days — it came due on {due_on}"
    )


def test_storm_rain_never_reaches_a_covered_porch(repo_root, world):
    """f_cover = 0 is the whole point of the covered flag."""
    species, locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/storm.json")
    specimen = specimens[LEMON_ON_PORCH]
    location = locations[specimen["location_id"]]
    assert location["is_covered"], "fixture drift: the porch must be covered"

    due_on, deficit, capacity = run_scenario(
        scenario, specimen, species[specimen["species_id"]], location
    )
    assert is_watering_due(
        deficit, capacity
    ), "the porch lemon must still be thirsty after the storm"
    assert rain_day(scenario) in due_on, "it was due on the rain day and stayed due"


def test_watering_is_never_negative_or_beyond_capacity(repo_root, world):
    species, locations, specimens = world
    for name in ("drought", "storm", "frost"):
        scenario = _fixture(repo_root, f"scenarios/{name}.json")
        for specimen in specimens.values():
            sp = species[specimen["species_id"]]
            if sp.get("water_k_c") is None:
                continue
            location = locations[specimen["location_id"]]
            capacity = capacity_mm(
                specimen["in_container"], specimen.get("container_litres")
            )
            deficit = 0.0
            for day in scenario["days"]:
                deficit = step_deficit(
                    deficit,
                    BalanceInputs(
                        et0_mm=day["et0_mm"],
                        precip_mm=day["precip_mm"],
                        cover_factor=0.0 if location["is_covered"] else 1.0,
                    ),
                    sp["water_k_c"],
                    capacity,
                )
                assert 0.0 <= deficit <= capacity, (name, specimen["id"], deficit)


def test_manual_watering_reduces_the_deficit(repo_root):
    """Logged irrigation has to count, or the app nags after you have watered."""
    capacity = capacity_mm(True, 45)
    deficit = step_deficit(
        20.0, BalanceInputs(et0_mm=5.0, precip_mm=0.0), 0.9, capacity
    )
    watered = step_deficit(
        20.0,
        BalanceInputs(et0_mm=5.0, precip_mm=0.0, irrigation_mm=15.0),
        0.9,
        capacity,
    )
    assert watered < deficit


def test_the_engine_is_complete_with_no_sensors_at_all(repo_root, world):
    """there is no soil-moisture hardware, so model-only is the
    shipping path — not a degraded one. Every outdoor specimen must reach a
    definite watering answer from weather alone."""
    species, locations, specimens = world
    scenario = _fixture(repo_root, "scenarios/drought.json")

    answered = 0
    for specimen in specimens.values():
        sp = species[specimen["species_id"]]
        if not specimen["is_outdoor"] or sp.get("water_k_c") is None:
            continue
        _, deficit, capacity = run_scenario(
            scenario, specimen, sp, locations[specimen["location_id"]]
        )
        assert isinstance(deficit, float) and deficit >= 0.0
        assert is_watering_due(deficit, capacity) in (True, False)
        answered += 1
    assert answered >= 5, "the fixtures should exercise several outdoor profiles"


def test_a_sensor_reading_overrides_the_model_when_one_exists(repo_root, world):
    """The override seam the design says to keep. No hardware drives it today,
    so this is the only thing keeping it honest until one appears."""
    _, _, specimens = world
    specimen = specimens[LEMON_ON_TERRACE]
    capacity = capacity_mm(specimen["in_container"], specimen["container_litres"])

    # The model thinks it is bone dry; the probe says the soil is wet.
    modelled = capacity
    assert is_watering_due(modelled, capacity)

    def due_with_sensor(deficit: float, sensor_pct: float | None) -> bool:
        if sensor_pct is not None:
            return sensor_pct < 30.0
        return is_watering_due(deficit, capacity)

    assert due_with_sensor(modelled, 62.0) is False, "a wet probe must win"
    assert due_with_sensor(0.0, 11.0) is True, "a dry probe must win too"
    assert due_with_sensor(modelled, None) is True, "no probe falls back to the model"
