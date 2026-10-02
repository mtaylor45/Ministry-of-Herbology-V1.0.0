"""The live MQTT transport, against a fake ``aiomqtt``. Owner: The hub.

Nothing is installed and nothing opens a socket: :func:`connect_publisher`
takes the client module as an argument, and the fake below has the three
names the real one is used through — ``Client``, ``Will`` and ``MqttError`` —
with ``aiomqtt`` 2.x's keyword arguments. If the fake accepts a call the real
client would refuse, the keyword names are the place to look.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar, Self

import pytest
from pydantic import SecretStr

from workers.hub import mqtt, office, tasks
from workers.hub.settings import HubSettings

#: Token-shaped, so a leak is a substring match and not a judgement call.
PASSWORD = "mqtt-pw-Zk8sQ2vN7xR4"
HA_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJsZWFrLXRlc3QifQ.c2lnbmF0dXJlLXRlc3Q"


class FakeMqttError(Exception):
    pass


class FakeWill:
    def __init__(
        self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False
    ) -> None:
        self.topic, self.payload, self.qos, self.retain = topic, payload, qos, retain


class FakeClient:
    instances: ClassVar[list[FakeClient]] = []
    fail_with: ClassVar[str | None] = None

    def __init__(
        self,
        hostname: str,
        port: int = 1883,
        *,
        username: str | None = None,
        password: str | None = None,
        identifier: str | None = None,
        will: FakeWill | None = None,
    ) -> None:
        self.kwargs = {
            "hostname": hostname,
            "port": port,
            "username": username,
            "password": password,
            "identifier": identifier,
        }
        self.will = will
        self.published: list[tuple[str, str, int, bool]] = []
        self.connected = False
        FakeClient.instances.append(self)

    async def __aenter__(self) -> Self:
        if FakeClient.fail_with:
            raise FakeMqttError(FakeClient.fail_with)
        self.connected = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.connected = False

    async def publish(
        self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False
    ) -> None:
        assert self.connected, "published on a client that is not connected"
        self.published.append((topic, payload, qos, retain))


@pytest.fixture
def fake_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    FakeClient.instances = []
    FakeClient.fail_with = None
    module = SimpleNamespace(Client=FakeClient, Will=FakeWill, MqttError=FakeMqttError)
    monkeypatch.setattr(mqtt, "_client_module", lambda: module)
    return module


@pytest.fixture
def live() -> HubSettings:
    return HubSettings(
        mock_mode=False,
        mqtt_host="broker.lan",
        mqtt_username="herbology",
        mqtt_password=SecretStr(PASSWORD),
        ha_base_url="http://ha.lan:8123",
        ha_token=SecretStr(HA_TOKEN),
    )


def test_it_connects_with_the_settings_and_a_retained_offline_will(
    run, fake_aiomqtt, live
):
    async def go() -> None:
        async with mqtt.connect_publisher(live) as publisher:
            await publisher.publish(mqtt.Message("herbology/rounds/due", "3"))

    run(go())
    (client,) = FakeClient.instances
    assert client.kwargs == {
        "hostname": "broker.lan",
        "port": 1883,
        "username": "herbology",
        "password": PASSWORD,
        "identifier": "ministry-of-herbology",
    }
    assert client.will is not None
    assert (client.will.topic, client.will.payload) == ("herbology/status", "offline")
    assert client.will.retain is True
    # Online first, then the state, both retained.
    assert client.published == [
        ("herbology/status", "online", 1, True),
        ("herbology/rounds/due", "3", 1, True),
    ]


def test_a_clean_exit_does_not_announce_offline(run, fake_aiomqtt, live):
    """The job connects twice an hour; offline between runs would grey out a
    healthy Ministry for most of every half hour."""

    async def go() -> None:
        async with mqtt.connect_publisher(live):
            pass

    run(go())
    assert [p[1] for p in FakeClient.instances[0].published] == ["online"]


def test_the_publisher_refuses_a_credential_before_the_socket(run, fake_aiomqtt, live):
    async def go() -> None:
        async with mqtt.connect_publisher(live) as publisher:
            await publisher.publish(
                mqtt.Message(
                    "herbology/rounds/due/attributes",
                    '{"feed":"https://x/api/v1/tending/feeds/abc.ics?token=Zk8sQ2vN7xR4aa"}',
                )
            )

    with pytest.raises(mqtt.SecretInPayload):
        run(go())
    assert all("token" not in p[1] for p in FakeClient.instances[0].published)


def test_no_broker_named_is_a_setup_step(run, fake_aiomqtt):
    async def go() -> None:
        async with mqtt.connect_publisher(HubSettings(mock_mode=False)):
            pass

    with pytest.raises(mqtt.MqttNotConfigured, match="MOH_MQTT_HOST"):
        run(go())


def test_no_client_installed_is_a_setup_step(run, monkeypatch, live):
    monkeypatch.setattr(mqtt, "_client_module", lambda: None)

    async def go() -> None:
        async with mqtt.connect_publisher(live):
            pass

    with pytest.raises(mqtt.MqttNotConfigured, match="aiomqtt"):
        run(go())


def test_a_broker_error_carrying_the_password_is_redacted(run, fake_aiomqtt, live):
    FakeClient.fail_with = f"auth failed for herbology:{PASSWORD}@broker.lan"

    async def go() -> None:
        async with mqtt.connect_publisher(live):
            pass

    with pytest.raises(ConnectionError) as caught:
        run(go())
    assert PASSWORD not in str(caught.value)
    assert caught.value.__cause__ is None


def test_mqtt_reads_configured_only_with_a_broker_and_a_client(fake_aiomqtt, live):
    """``world._is_configured`` treated "client importable" as configured.
    It now needs a named broker too, and MOH_MQTT_HOST has no default."""
    rows = {i["kind"]: i for i in _integrations(HubSettings(mock_mode=True))}
    assert rows["mqtt"]["status"] == "unconfigured"
    rows = {i["kind"]: i for i in _integrations(live)}
    assert rows["mqtt"]["status"] == "stale"  # configured, never heard from
    assert rows["mqtt"]["last_ok_at"] is None


def _integrations(settings: HubSettings) -> list[dict[str, Any]]:
    import asyncio

    return asyncio.run(office.list_integrations(settings))


# ------------------------------------------------- the job, end to end


class Recorder:
    """An asyncpg stand-in holding ``integration`` rows the way the table does."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def execute(self, sql: str, *args: Any) -> str:
        if sql.startswith("INSERT INTO integration"):
            self.rows.setdefault(
                args[0],
                {
                    "id": args[0],
                    "kind": args[1],
                    "name": args[2],
                    "enabled": True,
                    "last_ok_at": None,
                    "last_error": None,
                },
            )
        elif sql.startswith("UPDATE integration SET last_ok_at"):
            self.rows[args[0]].update(last_ok_at=args[1], last_error=None)
        elif sql.startswith("UPDATE integration SET last_error"):
            self.rows[args[0]].update(last_error=args[1])
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return list(self.rows.values()) if "FROM integration" in sql else []


def test_the_publish_job_goes_live_and_stamps_mqtt_ok(
    run, fake_aiomqtt, live, ministry
):
    connection = Recorder()
    report = run(
        tasks.publish_to_mqtt(
            {"settings": live, "reader": ministry, "connection": connection}
        )
    )
    assert report["ok"] is True
    assert report["transport"] == "ClientPublisher"
    topics = [p[0] for p in FakeClient.instances[0].published]
    # Per-specimen discovery reaches the broker, one object id per plant.
    assert any(
        t.startswith("homeassistant/binary_sensor/herbology/specimen_") for t in topics
    )
    rows = run(office.list_integrations(live, connection))
    mqtt_row = next(r for r in rows if r["kind"] == "mqtt")
    assert mqtt_row["status"] == "ok"


def test_a_failing_broker_lands_on_the_row_redacted_and_never_in_a_response(
    run, fake_aiomqtt, live, ministry
):
    """Write the test that would catch a leak: a token-shaped value in the
    adapter's error path, followed all the way to the Ministry Office."""
    FakeClient.fail_with = (
        f"connection refused; Authorization: Bearer {HA_TOKEN}; "
        f"url mqtt://herbology:{PASSWORD}@broker.lan:1883"
    )
    connection = Recorder()
    report = run(
        tasks.publish_to_mqtt(
            {"settings": live, "reader": ministry, "connection": connection}
        )
    )
    assert report["ok"] is False
    for text in (str(report), str(connection.rows)):
        assert HA_TOKEN not in text and PASSWORD not in text
    rows = run(office.list_integrations(live, connection))
    mqtt_row = next(r for r in rows if r["kind"] == "mqtt")
    assert mqtt_row["status"] == "down"
    assert "[redacted]" in mqtt_row["last_error"]
    assert HA_TOKEN not in str(rows) and PASSWORD not in str(rows)


def test_mock_mode_never_dials_the_broker(run, fake_aiomqtt, ministry):
    settings = HubSettings(mock_mode=True, mqtt_host="broker.lan")
    report = run(tasks.publish_to_mqtt({"settings": settings, "reader": ministry}))
    assert report["transport"] == "MemoryPublisher"
    assert FakeClient.instances == []
