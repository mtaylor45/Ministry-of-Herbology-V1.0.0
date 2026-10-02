"""Every Almanac response, validated against the frozen contract — the weather engine.

The maintainers found four contract defects before shipping 1.4.0 by validating live API
responses against the OpenAPI schemas, something this project had never done in
five releases, and turned up that **every task the API served had violated the
frozen contract since 1.0.0** while the unit tests stayed green throughout.

The defect class is specific: a unit test asserts the fields it was written to
care about, so a field with the wrong *type*, or one the contract requires and
nobody thought to assert, passes for as long as nobody looks. The contract-first rule makes the
contract authoritative; nothing was checking that the code agreed with it.

So this checks all four of the weather engine's responses against the frozen document, under the
baseline *and* under a scenario — because a scenario is a different code path
through the same serialisers and is exactly where a field would quietly go
missing. It is the weather engine's own suite: ``tests/contract/`` is the test suite's and this does
not
duplicate it, since nothing there validates a response body.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from workers.weather.settings import get_settings as weather_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE = "01890000-0000-7000-8000-000000000001"
LEMON_ON_TERRACE = "01890040-0000-7000-8000-000000000004"
MONSTERA_INDOORS = "01890040-0000-7000-8000-000000000001"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    with (REPO_ROOT / "contracts" / "openapi" / "openapi.yaml").open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def validator_for(spec):
    """A validator for one path's 200 response, ``$ref``s resolved.

    The declared schema is taken verbatim and the document's own ``components``
    block is hung beside it, so every ``#/components/schemas/…`` pointer
    resolves inside the schema being validated. Nothing is rewritten: a
    rewritten schema is not the frozen one, and checking against a paraphrase
    of the contract is how a contract drifts.
    """

    def _for(path: str) -> Draft202012Validator:
        declared = spec["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        schema = dict(declared) | {"components": spec["components"]}
        return Draft202012Validator(schema, format_checker=FormatChecker())

    return _for


def check(validator: Draft202012Validator, payload: Any) -> None:
    """Report *every* violation, not just the first one.

    A failure here is a contract breach, and the useful output is the whole list
    — fixing them one test run at a time is how four of them survived five
    releases.
    """
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{list(error.absolute_path) or '<root>'}: {error.message}" for error in errors
    )


@pytest.fixture(params=["baseline", "storm"])
def client(request, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app under each recording. One parameter, eight validations.

    A scenario is a different route through the same serialisers, so it gets the
    same scrutiny as the default; a field that survives the baseline and goes
    missing under ``storm`` is the kind of thing only this notices.
    """
    from app.main import app

    if request.param == "storm":
        monkeypatch.setenv("MOH_SCENARIO", "storm")
    else:
        monkeypatch.delenv("MOH_SCENARIO", raising=False)
    monkeypatch.delenv("MOH_SCENARIO_DAY", raising=False)
    weather_settings.cache_clear()
    yield TestClient(app)
    weather_settings.cache_clear()


def test_the_forecast_matches_forecastpoint(client, validator_for):
    for horizon in ("daily", "hourly"):
        payload = client.get(
            "/api/v1/almanac/forecast",
            params={"site_id": SITE, "horizon": horizon},
        ).json()
        check(validator_for("/almanac/forecast"), payload)


def test_the_history_matches_series(client, validator_for):
    validator = validator_for("/almanac/history")
    for window in ("1d", "7d", "30d"):
        for metric in ("temperature_c", "precip_mm", "et0_mm", "soil_moisture_pct"):
            payload = client.get(
                "/api/v1/almanac/history",
                params={"window": window, "metric": metric, "site_id": SITE},
            ).json()
            check(validator, payload)


def test_the_water_balance_matches_waterbalance(client, validator_for):
    """Including the indoor specimen, which takes the ``applies: false`` branch."""
    validator = validator_for("/almanac/water-balance/{specimen_id}")
    for specimen_id in (LEMON_ON_TERRACE, MONSTERA_INDOORS):
        payload = client.get(f"/api/v1/almanac/water-balance/{specimen_id}").json()
        check(validator, payload)


def test_the_frost_report_matches_frostreport(client, validator_for):
    payload = client.get("/api/v1/almanac/frost").json()
    check(validator_for("/almanac/frost"), payload)


def blinded_fixtures(tmp_path: Path):
    """The frozen fixtures with every ``min_temp_c`` removed.

    The frozen set gives every outdoor species a minimum temperature, so nothing
    is unassessable against it and this half of the response would otherwise
    ship untested. ``fixtures/`` is the test suite's and is read, never written: a
    copy goes in pytest's ``tmp_path``.
    """
    import json
    import shutil

    from workers.weather.settings import WeatherSettings

    shutil.copytree(REPO_ROOT / "fixtures", tmp_path / "fixtures")
    species_file = tmp_path / "fixtures" / "species" / "species.json"
    species = json.loads(species_file.read_text())
    for row in species:
        row["min_temp_c"] = None
    species_file.write_text(json.dumps(species))
    return WeatherSettings(mock_mode=True, fixtures_dir=tmp_path / "fixtures")


def test_a_plant_nobody_could_judge_is_named_not_numbered(tmp_path: Path):
    """the panel that exists to name plants now carries the name."""
    from almanac import service as almanac

    unassessable = almanac.unassessable_for_frost(settings=blinded_fixtures(tmp_path))

    assert unassessable, "a species with no minimum temperature must be named"
    for entry in unassessable:
        assert entry["specimen"]["id"] == entry["specimen_id"]
        assert entry["specimen"]["display_name"]
        assert entry["specimen"]["is_outdoor"] is True
        assert "no minimum temperature" in entry["reason"]
        # The failure this field exists to prevent: a uuid shown to a reader.
        assert entry["specimen"]["display_name"] != entry["specimen_id"]


def test_the_unassessable_half_is_contract_shaped_too(tmp_path: Path, validator_for):
    """The half of ``/almanac/frost`` the frozen fixtures cannot exercise."""
    from almanac import service as almanac

    settings = blinded_fixtures(tmp_path)
    payload = {
        "alerts": almanac.frost(settings=settings),
        "unassessable": almanac.unassessable_for_frost(settings=settings),
    }
    assert payload["unassessable"] and not payload["alerts"], (
        "no species has a threshold to cross, so every outdoor plant is "
        "unassessable and none is alerted"
    )
    check(validator_for("/almanac/frost"), payload)


def test_this_validator_would_actually_notice(client, validator_for):
    """A schema check that passes everything is worse than none at all.

    It reads as coverage, which is how four breaches survived five releases of
    green tests. So: the real response validates, and five deliberate breaches
    of it do not — including a uuid-format violation, which is only checked
    because ``FormatChecker`` is installed and would otherwise be skipped
    silently.
    """
    import copy

    validator = validator_for("/almanac/water-balance/{specimen_id}")
    real = client.get(f"/api/v1/almanac/water-balance/{LEMON_ON_TERRACE}").json()
    check(validator, real)

    breaches = (
        ("a required field removed", lambda p: p.pop("confidence")),
        ("a value outside an enum", lambda p: p.update(status="soggy")),
        ("a number served as text", lambda p: p.update(deficit_mm="lots")),
        ("a bad per-day enum", lambda p: p["days"][0].update(et0_method="vibes")),
        ("a malformed uuid", lambda p: p.update(specimen_id="not-a-uuid")),
    )
    for label, breach in breaches:
        broken = copy.deepcopy(real)
        breach(broken)
        assert list(validator.iter_errors(broken)), label
