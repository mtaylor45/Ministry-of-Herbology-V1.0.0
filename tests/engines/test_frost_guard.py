"""The frost engine, run against the frozen frost scenario."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workers.weather.tasks import (
    FROST_MARGIN_C,
    frost_action,
    frost_threshold_c,
    needs_frost_action,
)

LEMON_ON_TERRACE = "01890040-0000-7000-8000-000000000004"
LAVENDER_HEDGE = "01890040-0000-7000-8000-000000000006"
ROSE = "01890040-0000-7000-8000-000000000007"
BASIL_OUTDOORS = "01890040-0000-7000-8000-000000000010"
MONSTERA_INDOORS = "01890040-0000-7000-8000-000000000001"


def _fixture(repo_root, relative):
    return json.loads((repo_root / "fixtures" / relative).read_text())


@pytest.fixture
def world(repo_root):
    species = {s["id"]: s for s in _fixture(repo_root, "species/species.json")}
    specimens = {s["id"]: s for s in _fixture(repo_root, "specimens/specimens.json")}
    return species, specimens


def first_alert_day(scenario, specimen, species):
    for index, day in enumerate(scenario["days"]):
        if needs_frost_action(
            day["tmin_c"], species["min_temp_c"], is_outdoor=specimen["is_outdoor"]
        ):
            return index
    return None


def test_margin_is_three_fahrenheit(repo_root):
    assert FROST_MARGIN_C == pytest.approx(1.6667, abs=1e-3)
    assert frost_threshold_c(2.0) == pytest.approx(3.6667, abs=1e-3)


def test_tender_plants_alert_and_hardy_ones_do_not(repo_root, world):
    species, specimens = world
    scenario = _fixture(repo_root, "scenarios/frost.json")

    for specimen_id in (LEMON_ON_TERRACE, BASIL_OUTDOORS):
        specimen = specimens[specimen_id]
        assert (
            first_alert_day(scenario, specimen, species[specimen["species_id"]])
            is not None
        ), f"{specimen['nickname']} is tender and must be warned"

    for specimen_id in (LAVENDER_HEDGE, ROSE):
        specimen = specimens[specimen_id]
        assert (
            first_alert_day(scenario, specimen, species[specimen["species_id"]]) is None
        ), "a plant hardy well below freezing must not be dragged indoors"


def test_the_tenderest_plant_is_warned_first(repo_root, world):
    """Basil gives up at 10 °C; the lemon holds on to 2 °C."""
    species, specimens = world
    scenario = _fixture(repo_root, "scenarios/frost.json")
    basil = first_alert_day(
        scenario,
        specimens[BASIL_OUTDOORS],
        species[specimens[BASIL_OUTDOORS]["species_id"]],
    )
    lemon = first_alert_day(
        scenario,
        specimens[LEMON_ON_TERRACE],
        species[specimens[LEMON_ON_TERRACE]["species_id"]],
    )
    assert basil < lemon


def test_indoor_plants_are_never_frost_alerted(repo_root, world):
    species, specimens = world
    scenario = _fixture(repo_root, "scenarios/frost.json")
    monstera = specimens[MONSTERA_INDOORS]
    assert monstera["is_outdoor"] is False
    assert first_alert_day(scenario, monstera, species[monstera["species_id"]]) is None


def test_containers_come_indoors_and_the_ground_gets_covered(repo_root, world):
    """You cannot carry a hedge inside; the plan says cover it instead."""
    _, specimens = world
    assert (
        frost_action(in_container=specimens[LEMON_ON_TERRACE]["in_container"])
        == "bring_indoors"
    )
    assert frost_action(in_container=specimens[ROSE]["in_container"]) == "cover"


def test_the_scenario_alerts_match_what_the_fixture_promises(repo_root, world):
    species, specimens = world
    scenario = _fixture(repo_root, "scenarios/frost.json")
    for assertion in scenario["expect"]["assertions"]:
        if "specimen" not in assertion or "alert" not in assertion:
            continue
        specimen = specimens[assertion["specimen"]]
        day = first_alert_day(scenario, specimen, species[specimen["species_id"]])
        if assertion["alert"]:
            assert day is not None, assertion
            expected = scenario["days"][day]["date"]
            if "night_of" in assertion:
                assert expected == assertion["night_of"], (
                    f"{specimen['id']} first alerts on {expected}, "
                    f"but the fixture promises {assertion['night_of']}"
                )
            assert (
                frost_action(in_container=specimen["in_container"])
                == assertion["action"]
            )
        else:
            assert day is None, assertion


def test_return_outdoors_needs_three_consecutive_mild_nights(repo_root, world):
    """The plan's rule, checked against the tail of the frost scenario."""
    species, specimens = world
    scenario = _fixture(repo_root, "scenarios/frost.json")
    specimen = specimens[LEMON_ON_TERRACE]
    threshold = frost_threshold_c(species[specimen["species_id"]]["min_temp_c"])

    last_frost = max(
        index
        for index, day in enumerate(scenario["days"])
        if day["tmin_c"] <= threshold
    )

    run = 0
    suggested_on = None
    for day in scenario["days"][last_frost + 1 :]:
        run = run + 1 if day["tmin_c"] > threshold else 0
        if run == 3:
            suggested_on = day["date"]
            break

    promised = next(
        a["from_day"] for a in scenario["expect"]["assertions"] if "from_day" in a
    )
    assert suggested_on == promised
