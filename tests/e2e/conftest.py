"""Shared setup for the scenario suite. Owner: The test suite.

These tests drive the *app*. Nothing here reaches into an engine: every fact a
test asserts arrives through an HTTP response, because the earlier exit criterion is
about what a person sees, and a suite that called ``run_balance`` directly
could be green while every screen in the app was wrong.

The engines have their own unit tests — ``tests/engines/`` here and
``workers/weather/tests/`` in the weather engine's directory. This suite deliberately
duplicates none of that arithmetic.

Everything runs in mock mode with no database and no network, so the suite is
the same on a laptop and in CI.
"""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: the design four levels, best to worst — the order this suite compares in.
CONFIDENCE_ORDER = ("high", "medium", "low", "unknown")

#: The household's single member.
KEEPER_ID = "01890050-0000-7000-8000-000000000001"

# The cast, by the ids the frozen fixtures give them. Named here rather than
# inline so a test reads as a sentence about a plant instead of a uuid.
MONSTERA_IN_THE_STUDY = "01890040-0000-7000-8000-000000000001"  # indoor
MANDRAKE_IN_THE_GREENHOUSE = "01890040-0000-7000-8000-000000000009"  # indoor, dormant
LEMON_ON_THE_TERRACE = "01890040-0000-7000-8000-000000000004"  # outdoor, open sky
LEMON_ON_THE_PORCH = "01890040-0000-7000-8000-000000000005"  # outdoor, covered
LAVENDER_HEDGE = "01890040-0000-7000-8000-000000000006"  # outdoor, in ground
ROSE_IN_THE_BORDER = "01890040-0000-7000-8000-000000000007"  # outdoor, in ground
HOSTAS_IN_THE_SHADE_BED = "01890040-0000-7000-8000-000000000008"  # outdoor, in ground
BASIL_ON_THE_TERRACE = "01890040-0000-7000-8000-000000000010"  # outdoor, open sky
LAVENDER_ON_THE_PORCH = "01890040-0000-7000-8000-000000000011"  # outdoor, covered


def confidence_rank(value: str | None) -> int:
    """How far down the design ladder a claim sits. Bigger is less certain."""
    if value not in CONFIDENCE_ORDER:
        return len(CONFIDENCE_ORDER) - 1
    return CONFIDENCE_ORDER.index(value)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a socket.

    Mirrors the scheduler's suite. A scenario test that quietly started asking
    Open-Meteo for today's weather would pass on a good day and fail on a bad
    one, and would stop being a scenario test the moment it did.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "The scenario suite is network-free: a test tried to open a "
            "socket. Drive the app through its HTTP surface on fixtures."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


#: The environment the scenario selector reads. Named once,
#: because this suite is what needs editing if E renames them — and they
#: were renamed once already, which left five tests skipped over a spelling.
SCENARIO_ENV_VARS = ("MOH_SCENARIO", "MOH_SCENARIO_DAY")

#: Fixtures that put the app under a recording. Requesting one of these and
#: `client` in the same test is a contradiction, and `client` refuses it.
SCENARIO_FIXTURES = frozenset({"storm", "drought"})


def _reset_caches() -> None:
    """Drop everything that remembers which weather this deployment is under.

    Both settings objects and the fixture loaders are cached. Leaving one warm
    lets a scenario leak into the next test, which is the one failure mode a
    suite about determinism cannot have.
    """
    from app import fixtures as app_fixtures
    from app.settings import get_settings as app_settings
    from tending.fixture_repository import reset_fixture_repository

    from workers.weather import world
    from workers.weather.settings import get_settings as weather_settings

    weather_settings.cache_clear()
    app_settings.cache_clear()
    world._load.cache_clear()
    for loader in (
        app_fixtures.site,
        app_fixtures.locations,
        app_fixtures.species,
        app_fixtures.sources,
        app_fixtures.specimens,
        app_fixtures.scenario,
        app_fixtures.baseline_weather,
    ):
        loader.cache_clear()
    reset_fixture_repository()


@contextmanager
def under_scenario(
    monkeypatch: pytest.MonkeyPatch, name: str, *, on: str | None = None
) -> Iterator[Any]:
    """The app as an operator running one of the recorded scenarios has it.

    Set through the environment, because that is the only route a deployment
    has and it is the route the weather engine built:
    ``MOH_SCENARIO`` picks the recording and
    ``MOH_SCENARIO_DAY`` says which of its days is "today". A suite
    that reached past the environment into a settings object would prove only
    that the private route works.
    """
    from app.main import app
    from fastapi.testclient import TestClient

    scenario_var, day_var = SCENARIO_ENV_VARS
    monkeypatch.setenv(scenario_var, name)
    if on is None:
        monkeypatch.delenv(day_var, raising=False)
    else:
        monkeypatch.setenv(day_var, on)
    _reset_caches()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        for variable in SCENARIO_ENV_VARS:
            monkeypatch.delenv(variable, raising=False)
        _reset_caches()


def scenario_day(name: str, index: int) -> str:
    """The date of one day of a recording, read from the fixture itself."""
    return str(load_fixture(f"scenarios/{name}.json")["days"][index]["date"])


def rain_day_of(name: str) -> str:
    """The date of a scenario's single soaking, from its own `expect` block."""
    fixture = load_fixture(f"scenarios/{name}.json")
    return str(fixture["days"][fixture["expect"]["rain_day_index"]]["date"])


def expectations(name: str) -> list[dict[str, Any]]:
    """A scenario's own per-specimen `expect.assertions`.

    `fixtures/README.md` has always promised that `tests/` asserts each one.
    Until the weather engine's selector landed nothing could: the running app
    only ever saw the baseline, so the expectations could be checked against
    the engine's arithmetic but never against a screen.
    """
    return [
        row
        for row in load_fixture(f"scenarios/{name}.json")["expect"]["assertions"]
        if "specimen" in row
    ]


@pytest.fixture
def storm(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The storm, read on the day it rained."""
    with under_scenario(monkeypatch, "storm", on=rain_day_of("storm")) as client:
        yield client


@pytest.fixture
def drought(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The drought, read on its last day — three weeks without rain."""
    with under_scenario(monkeypatch, "drought") as client:
        yield client


@pytest.fixture
def client(request: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The control case: no scenario, the baseline recording, a clean schedule.

    Two things this has to guarantee, and the second is the one that bites.

    The in-memory store is process-wide so a completion outlives its request;
    resetting it around every test keeps one test's completions out of the next
    one's rounds.

    And **no scenario may be in force.** This fixture and the scenario fixtures
    above both decide what weather the app is under, so a test that asked for
    both would get one deployment wearing two hats — whichever set the
    environment last, with the other's cache-clear possibly in between. Rather
    than leave that to fixture ordering, this one unsets the variables itself,
    drops the same caches, and then *asserts* the app really is on the baseline.
    A scenario leaking in here would silently turn every test that uses this
    fixture into a test of the storm.
    """
    from app.main import app
    from fastapi.testclient import TestClient

    from workers.weather import world

    # Checked on the *request*, not on the environment. Asserting
    # `active_scenario() is None` here would always pass and prove nothing:
    # this fixture clears the variables itself, so by the time it could look
    # they are gone — and the damage is done in the other order, where a
    # scenario fixture sets them again after this client was built.
    both = SCENARIO_FIXTURES & set(request.fixturenames)
    assert not both, (
        f"this test requests `client` and {sorted(both)}, which are two answers "
        "to the question 'what weather is this deployment under'. Whichever set "
        "the environment last wins and the other's cache-clear may land in "
        "between, so the test would pass or fail on fixture ordering. Use one."
    )

    for name in SCENARIO_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _reset_caches()
    assert world.active_scenario() is None, "the baseline is the control case"
    with TestClient(app) as test_client:
        yield test_client
    _reset_caches()


# --------------------------------------------------------------- the fixtures


def load_fixture(relative: str) -> Any:
    return json.loads((REPO_ROOT / "fixtures" / relative).read_text())


@pytest.fixture(scope="session")
def baseline_days() -> list[dict[str, Any]]:
    return load_fixture("weather/baseline_30d.json")["days"]


@pytest.fixture(scope="session")
def weather_last_day(baseline_days: list[dict[str, Any]]) -> str:
    """The newest day the shipped weather actually covers.

    Read from the fixture rather than written down, so that extending or
    trimming the baseline moves the suite with it instead of breaking it. A
    round asked for on this day is "the morning after", with a balance that is
    current; a round asked for on any later day is working from stale weather
    and must say so — which is what
    ``test_certainty_survives_the_round_trip.py`` is about.
    """
    return str(baseline_days[-1]["date"])


@pytest.fixture(scope="session")
def a_day_the_mandrake_is_dormant() -> str:
    """A date inside the greenhouse mandrake's dormancy, read from the fixtures.

    Its care rule *suspends* watering rather than stretching it, so on such a
    day the plant has no task at all — and the round has to say so by name
    instead of letting it drop off. Derived rather than written down so that
    editing the species moves the test with it.
    """
    specimen = next(
        row
        for row in load_fixture("specimens/specimens.json")
        if row["id"] == MANDRAKE_IN_THE_GREENHOUSE
    )
    species = next(
        row
        for row in load_fixture("species/species.json")
        if row["id"] == specimen["species_id"]
    )
    months = sorted(species["dormancy_months"])
    assert months, "fixture drift: the mandrake is the dormancy case"
    return date(2026, months[0], 15).isoformat()


@pytest.fixture(scope="session")
def a_day_the_weather_does_not_cover(weather_last_day: str) -> str:
    """Six weeks past the end of the shipped weather."""
    return (date.fromisoformat(weather_last_day) + timedelta(days=46)).isoformat()


# ------------------------------------------------------------- the contract


@pytest.fixture(scope="session")
def contract(spec: dict) -> Any:
    """A validator for one named schema out of the frozen OpenAPI document.

    ``jsonschema`` arrives with ``openapi-spec-validator``, which
    ``tests/contract/`` already depends on.

    Contract 1.3.0 made ``confidence``, ``degraded`` and ``degradations``
    required on ``Task``, ``WaterBalance`` and ``FrostAlert``, and
    ``unscheduled`` required on ``MorningRounds``. Validating the live
    responses here is how this suite proves the app is not quietly dropping
    them: a required field that goes missing is a silent loss of exactly the
    honesty the design and the design were written to keep.

    This validates the schemas this suite's own assertions are about.
    ``tests/contract/test_responses_match_their_schemas.py`` is the general
    case: every endpoint, every declared response.
    """
    from jsonschema import Draft202012Validator

    schemas = spec["components"]["schemas"]

    def check(payload: Any, schema_name: str) -> None:
        schema = dict(schemas[schema_name])
        # Resolve $ref against the same document by handing the validator the
        # component section as the schema's own definitions.
        schema["components"] = {"schemas": schemas}
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda error: list(error.path),
        )
        assert not errors, "\n".join(
            f"{schema_name}{list(error.path)}: {error.message}" for error in errors
        )

    return check


# ------------------------------------------------------------------ the feed


def subscribe(client: Any, **filters: Any) -> str:
    """Create a calendar feed and return the path a subscriber would fetch.

    The token is only ever in the URL, so this pulls the path out of ``https_url`` the way a
    calendar client would follow it.
    """
    from urllib.parse import urlparse

    response = client.post(
        "/api/v1/tending/feeds",
        json={
            "member_id": KEEPER_ID,
            "name": "Scenario suite",
            "filters": filters,
        },
    )
    assert response.status_code == 201, response.text
    return str(urlparse(response.json()["https_url"]).path)


_UNFOLD = re.compile(r"\r\n[ \t]")


def ics_events(document: str) -> dict[str, dict[str, str]]:
    """Every ``VEVENT`` in a feed, keyed by UID.

    Keyed by UID because that is the assertion this suite keeps making: a
    watering the rain settled is *cancelled by the UID it already had*, not
    dropped and not reissued under a new one. A dict keyed by UID also makes a
    duplicate impossible to miss, so the count is checked before it is built.
    """
    unfolded = _UNFOLD.sub("", document)
    events: dict[str, dict[str, str]] = {}
    uids: list[str] = []
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        body = block.split("END:VEVENT")[0]
        properties: dict[str, str] = {}
        for line in body.splitlines():
            if not line.strip() or ":" not in line:
                continue
            name, _, value = line.partition(":")
            properties[name.split(";")[0].strip().upper()] = value.strip()
        uid = properties.get("UID", "")
        uids.append(uid)
        events[uid] = properties
    assert len(uids) == len(set(uids)), (
        "the same UID appears twice in one feed — every subscriber would get "
        "two events for one task"
    )
    return events


def tasks_by_specimen(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {task["specimen"]["id"]: task for task in tasks}
