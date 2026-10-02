"""The Lunette feed. Owner: The hub.

Two halves. The pure builder is driven with hand-made rounds, so each rule —
frost first, the hedge on the line, the stale clock, no invented zero — is
pinned on its own. Then the route is driven end to end under the frost
scenario, reading the scheduler's real round over the same HTTP request a deployment
makes to ``MOH_API_URL``, carried back into the app with no socket.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from workers.hub import router as hub
from workers.hub.lunette import build_feed
from workers.hub.settings import HubSettings

NOW = datetime(2026, 10, 22, 6, 5, tzinfo=UTC)
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJsdW5ldHRlIn0.c2lnbmF0dXJlLWx1bmV0dGU"


def task(name: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"task-{name}",
        "specimen": {"id": f"spec-{name}", "display_name": name},
        "task_type": "water",
        "status": "due",
        "plain_title": f"Water {name} — 200 ml",
        "confidence": "high",
        "degraded": False,
        "degradations": [],
        **extra,
    }


def alert(name: str, night: str, low: float, **extra: Any) -> dict[str, Any]:
    return {
        "specimen": {"id": f"spec-{name}", "display_name": name},
        "night_of": night,
        "forecast_low_c": low,
        "action": "bring_indoors",
        "state": "open",
        "confidence": "high",
        "degraded": False,
        **extra,
    }


def rounds(**parts: Any) -> dict[str, Any]:
    return {
        "date": "2026-10-22",
        "due": [],
        "satisfied": [],
        "alerts": [],
        "unscheduled": [],
        **parts,
    }


def test_frost_leads_and_says_it_is_a_forecast():
    feed = build_feed(
        rounds(
            due=[task("Fern")],
            alerts=[
                alert("Lemon", "2026-10-23", -2.0),
                alert("Basil", "2026-10-22", 4),
            ],
        ),
        now=NOW,
    )
    first, second = feed["lines"][:2]
    assert first.startswith("COLD Thu 22 Oct") and "Basil" in first
    assert second.startswith("FROST Fri 23 Oct") and "Lemon" in second
    assert all("(forecast)" in line for line in (first, second))
    assert feed["frost_warning"].startswith("Cold night forecast for Thu 22 Oct")
    assert feed["headline"] == "Thu 22 Oct: 1 due, frost forecast"


def test_certainty_reaches_each_instruction():
    feed = build_feed(
        rounds(
            due=[
                task("Fern"),
                task("Screamer", confidence="unknown", degraded=True),
                task("Ivy", confidence="medium", degraded=True),
                task("Aloe", confidence="low"),
            ]
        ),
        now=NOW,
    )
    lines = feed["lines"]
    assert "Water Fern — 200 ml" in lines
    assert "Water Screamer — 200 ml (a guess)" in lines
    assert "Water Ivy — 200 ml (estimate)" in lines
    assert "Water Aloe — 200 ml (estimate)" in lines


def test_rain_is_listed_briefly_and_unscheduled_plants_are_counted():
    feed = build_feed(
        rounds(
            satisfied=[
                task("Fern", status="satisfied", satisfied_by="rain"),
                task("Rose", status="satisfied", satisfied_by="rain"),
            ],
            unscheduled=[{"specimen_id": "x", "reason": "no interval"}],
        ),
        now=NOW,
    )
    assert "Nothing due today." in feed["lines"]
    assert "Rain covered: Fern, Rose" in feed["lines"]
    assert "1 plant has no schedule — see the app" in feed["lines"]
    assert feed["due_count"] == 0


def test_the_last_line_is_the_clock_in_the_site_zone():
    feed = build_feed(rounds(), now=NOW, tz="Europe/London")
    assert feed["lines"][-1] == "Updated Thu 22 Oct 07:05 BST"
    assert feed["generated_at"] == NOW.isoformat()


def test_a_long_round_is_capped_for_the_glass():
    feed = build_feed(rounds(due=[task(f"Plant{i}") for i in range(12)]), now=NOW)
    assert "…and 4 more in the app" in feed["lines"]
    assert feed["due_count"] == 12


def test_no_round_is_not_an_empty_round():
    """``due_count`` is omitted, not zero: zero would claim nothing is due."""
    feed = build_feed(None, now=NOW)
    assert feed["headline"] == "Rounds unavailable"
    assert "due_count" not in feed
    assert feed["lines"][-1].startswith("Updated")


def test_nothing_token_shaped_reaches_the_panel():
    feed = build_feed(
        rounds(
            due=[task(f"token={TOKEN}")],
            alerts=[alert("Lemon", "2026-10-23", -2.0, advisory=f"see {TOKEN}")],
        ),
        now=NOW,
        secrets=(TOKEN,),
    )
    assert TOKEN not in str(feed)


# ------------------------------------------------------- through the app


@pytest.fixture
def app() -> Iterator[Any]:
    from app.main import app

    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def frost_day(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The frost scenario, standing on 22 October, and nothing left behind.

    The weather engine's settings are cached per process, so the scenario is cleared out of the
    cache on the way in and on the way out — the same pattern
    ``api/almanac/tests/test_almanac_scenario_end_to_end.py`` uses. Without it
    the next suite in the run inherits a frost recording it never asked for.
    """
    from workers.weather.factory import get_ingest
    from workers.weather.settings import get_settings as weather_settings

    monkeypatch.setenv("MOH_SCENARIO", "frost")
    monkeypatch.setenv("MOH_SCENARIO_DAY", "2026-10-22")
    weather_settings.cache_clear()
    get_ingest.cache_clear()
    yield
    monkeypatch.delenv("MOH_SCENARIO", raising=False)
    monkeypatch.delenv("MOH_SCENARIO_DAY", raising=False)
    weather_settings.cache_clear()
    get_ingest.cache_clear()


def test_the_frost_scenario_on_22_october(app, frost_day):
    """The earlier exit criterion: "Lunette shows today's rounds"."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[hub.rounds_reader] = hub.loopback_reader(app)
    feed = TestClient(app).get("/api/v1/hub/lunette").json()
    assert feed["lines"][0].startswith(("FROST", "COLD")), feed["lines"]
    assert "(forecast" in feed["lines"][0]
    assert feed["frost_warning"] and "forecast" in feed["frost_warning"]
    assert feed["due_count"] >= 1
    assert feed["lines"][-1].startswith("Updated")


class Failing:
    closed = False

    async def rounds(self) -> Any:
        raise RuntimeError(f"401 from http://api:8000 Authorization: Bearer {TOKEN}")

    async def aclose(self) -> None:
        Failing.closed = True


def test_an_unreachable_ministry_is_said_and_the_error_stays_out(app, caplog):
    from fastapi.testclient import TestClient

    app.dependency_overrides[hub.hub_settings] = lambda: HubSettings(mock_mode=True)
    app.dependency_overrides[hub.rounds_reader] = Failing
    with caplog.at_level("WARNING"):
        response = TestClient(app).get("/api/v1/hub/lunette")
    assert response.status_code == 200
    assert response.json()["headline"] == "Rounds unavailable"
    assert TOKEN not in response.text
    assert TOKEN not in caplog.text
    assert Failing.closed
