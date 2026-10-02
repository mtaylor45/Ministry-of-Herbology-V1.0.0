"""The hub's HTTP surface, through the running app. Owner: The hub.

Each route is driven through ``app.main`` with FastAPI's dependency overrides
standing in for the settings, the database connection and Home Assistant —
so what is asserted is what a client would receive, headers included.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr

from workers.hub import office
from workers.hub import router as hub
from workers.hub.settings import HubSettings
from workers.hub.store import integration_id_for

HA_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJsZWFrLXRlc3QifQ.c2lnbmF0dXJlLXRlc3Q"
LOCATION = "01890020-0000-7000-8000-000000000001"


@pytest.fixture
def app() -> Iterator[Any]:
    from app.main import app

    office.reset_mock_store()
    yield app
    app.dependency_overrides.clear()
    office.reset_mock_store()


def client(app: Any, settings: HubSettings, **overrides: Any) -> Any:
    from fastapi.testclient import TestClient

    app.dependency_overrides[hub.hub_settings] = lambda: settings
    for dependency, value in overrides.items():
        app.dependency_overrides[getattr(hub, dependency)] = value
    return TestClient(app)


def live_settings(**extra: Any) -> HubSettings:
    return HubSettings(
        mock_mode=False,
        ha_base_url="http://ha.lan:8123",
        ha_token=SecretStr(HA_TOKEN),
        **extra,
    )


class Rows:
    """A connection whose ``integration`` table holds the given rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return self.rows if "FROM integration" in sql else []


def connection_of(conn: Any) -> Any:
    async def dependency() -> Any:
        yield conn

    return dependency


# ------------------------------------------------------------ integrations


def test_a_fresh_mock_deployment_is_unconfigured_not_down(app):
    response = client(app, HubSettings(mock_mode=True)).get("/api/v1/hub/integrations")
    assert response.status_code == 200
    by_kind = {row["kind"]: row for row in response.json()}
    assert by_kind["home_assistant"]["status"] == "unconfigured"
    assert by_kind["mqtt"]["status"] == "unconfigured"
    assert all(row["last_error"] is None for row in by_kind.values())


def test_a_fresh_live_deployment_with_no_rows_still_lists_both(app):
    response = client(
        app, HubSettings(mock_mode=False), hub_connection=connection_of(Rows([]))
    ).get("/api/v1/hub/integrations")
    assert {row["kind"] for row in response.json()} == {"home_assistant", "mqtt"}
    assert {row["status"] for row in response.json()} == {"unconfigured"}


def test_status_is_computed_from_the_row_and_the_clock(app):
    now = datetime.now(UTC)
    ha_id = integration_id_for("home_assistant", "Home Assistant")
    rows = [
        {
            "id": ha_id,
            "kind": "home_assistant",
            "name": "Home Assistant",
            "enabled": True,
            "last_ok_at": now - timedelta(hours=3),
            "last_error": None,
        }
    ]
    response = client(
        app, live_settings(), hub_connection=connection_of(Rows(rows))
    ).get("/api/v1/hub/integrations")
    ha = next(row for row in response.json() if row["kind"] == "home_assistant")
    assert ha["status"] == "stale"  # answering, never erroring, hours behind


def test_a_token_in_last_error_never_reaches_the_office(app):
    """The row was written by somebody else, or before a pattern existed: the
    route redacts on the way out regardless."""
    rows = [
        {
            "id": integration_id_for("home_assistant", "Home Assistant"),
            "kind": "home_assistant",
            "name": "Home Assistant",
            "enabled": True,
            "last_ok_at": None,
            "last_error": (
                f"401 from http://admin:hunter2pass@ha.lan:8123/api/states "
                f"with Authorization: Bearer {HA_TOKEN}"
            ),
        },
        {
            "id": "a3f0c2d4-0000-4000-8000-000000000001",
            "kind": "caldav",
            "name": "Household calendar",
            "enabled": True,
            "last_ok_at": None,
            "last_error": f"token={HA_TOKEN[:24]}abcdef rejected",
        },
    ]
    response = client(
        app, live_settings(), hub_connection=connection_of(Rows(rows))
    ).get("/api/v1/hub/integrations")
    text = response.text
    assert HA_TOKEN not in text and HA_TOKEN[:24] not in text
    assert "hunter2pass" not in text
    ha = next(row for row in response.json() if row["kind"] == "home_assistant")
    assert ha["status"] == "down"
    assert "[redacted]" in ha["last_error"]
    # A kind the hub does not run is still served, as found.
    assert any(row["kind"] == "caldav" for row in response.json())


# ----------------------------------------------------------------- sensors


THERMOSTAT = {
    "name": "Shed thermostat",
    "adapter": "home_assistant",
    "external_ids": {"temperature_c": "sensor.shed_temperature"},
    "location_id": LOCATION,
}


def test_a_posted_sensor_is_listed_and_says_what_was_checked(app):
    api = client(app, HubSettings(mock_mode=True))
    before = len(api.get("/api/v1/hub/sensors").json())
    response = api.post("/api/v1/hub/sensors", json=THERMOSTAT)
    assert response.status_code == 201
    assert "shape only" in response.headers["X-Hub-Check"]
    body = response.json()
    assert body["last_seen_at"] is None
    listed = api.get("/api/v1/hub/sensors").json()
    assert len(listed) == before + 1 and body["id"] in {row["id"] for row in listed}


@pytest.mark.parametrize(
    ("external_ids", "specimen_id", "fragment"),
    [
        ({"temperature_c": "light.shed"}, None, "carries no reading"),
        ({"temperature_c": "shed_temperature"}, None, "not a Home Assistant entity id"),
        ({"soil_moisture_pct": "sensor.pot_moisture"}, None, "needs a specimen_id"),
    ],
)
def test_a_mapping_the_adapter_could_not_read_is_refused(
    app, external_ids, specimen_id, fragment
):
    response = client(app, HubSettings(mock_mode=True)).post(
        "/api/v1/hub/sensors",
        json={**THERMOSTAT, "external_ids": external_ids, "specimen_id": specimen_id},
    )
    assert response.status_code == 422
    assert fragment in str(response.json()["detail"])


def test_an_unknown_metric_is_kept_and_named_as_not_polled(app):
    """the design keeps ``external_ids`` open for keys the app does not know."""
    response = client(app, HubSettings(mock_mode=True)).post(
        "/api/v1/hub/sensors",
        json={**THERMOSTAT, "external_ids": {"co2_ppm": "sensor.shed_co2"}},
    )
    assert response.status_code == 201
    assert "co2_ppm" in response.headers["X-Hub-Check"]


class FakeHA:
    def __init__(self, states: dict[str, Any] | None = None, error: str = "") -> None:
        self._states, self._error = states or {}, error

    async def states(self) -> dict[str, Any]:
        if self._error:
            raise RuntimeError(self._error)
        return self._states


def test_live_mode_checks_the_entity_exists_in_home_assistant(app):
    conn = Rows([])
    api = client(
        app,
        live_settings(),
        hub_connection=connection_of(conn),
        ha_source=lambda: FakeHA({"sensor.shed_temperature": object()}),
    )
    ok = api.post("/api/v1/hub/sensors", json=THERMOSTAT)
    assert ok.status_code == 201
    assert "found in Home Assistant" in ok.headers["X-Hub-Check"]
    assert any("INSERT INTO sensor_source" in sql for sql, _ in conn.executed)

    missing = api.post(
        "/api/v1/hub/sensors",
        json={**THERMOSTAT, "external_ids": {"temperature_c": "sensor.nope"}},
    )
    assert missing.status_code == 422
    assert "sensor.nope" in str(missing.json()["detail"])


def test_a_hub_that_does_not_answer_is_said_plainly_and_without_the_token(app):
    api = client(
        app,
        live_settings(),
        hub_connection=connection_of(Rows([])),
        ha_source=lambda: FakeHA(error=f"401: Authorization: Bearer {HA_TOKEN}"),
    )
    response = api.post("/api/v1/hub/sensors", json=THERMOSTAT)
    assert response.status_code == 201
    note = response.headers["X-Hub-Check"]
    assert "not checked" in note and "did not answer" in note
    assert HA_TOKEN not in note and HA_TOKEN not in response.text


def test_live_mode_with_no_hub_configured_says_it_could_not_check(app):
    response = client(
        app, HubSettings(mock_mode=False), hub_connection=connection_of(Rows([]))
    ).post("/api/v1/hub/sensors", json=THERMOSTAT)
    assert response.status_code == 201
    assert "no Home Assistant is configured" in response.headers["X-Hub-Check"]
