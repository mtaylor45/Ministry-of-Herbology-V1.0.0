"""What the Ministry Office reads about the hub — the hub.

``GET /hub/integrations``, ``GET /hub/sensors`` and ``POST /hub/sensors``, as
plain functions the router calls. Kept out of :mod:`workers.hub.router` so they
can be tested without an app, and so the one decision that matters here — what
an integration's status *is* — lives beside the engine that computes it rather
than in a request handler.

## A fresh deployment is unconfigured, not broken

A deployment that has never been pointed at a Home Assistant has no
``integration`` row at all. Serving an empty list would hide the integration;
serving ``down`` would call a setup step a fault. So the two integrations this
worker owns are **always listed**, from :data:`workers.hub.world.HUB_INTEGRATIONS`,
and a row in the database — when there is one — supplies only what it actually
knows: ``enabled``, ``last_ok_at``, ``last_error``. Whether the integration is
*configured* is read from this process's settings every time, because a row
outlives the environment variable that once justified it.

## What is not listed, and why

Open-Meteo and NWS do not report through this worker. ``integration.kind``'s
CHECK constraint does not admit them, and the weather engine's ingest records its
runs in ``job_run``, not on an ``integration`` row — so there is nothing here
that could compute their status without inventing it. Calendar push is the scheduler's and
has not landed. Any row of any other kind that *is* in the table (a
``google_calendar`` or ``caldav`` row the day the scheduler writes one) is served as found,
with its status computed by the same rule.

## Nothing secret leaves

``integration.config`` is never selected (:func:`workers.hub.store.integrations_sql`)
and ``last_error`` is redacted again on the way out with this deployment's own
token and MQTT password as literal secrets, on top of the patterns.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from .entities import SUPPORTED_METRICS
from .health import IntegrationHealth
from .mapping import NUMERIC_DOMAINS, SensorSource
from .settings import HubSettings
from .sources.base import HOME_ASSISTANT
from .store import Connection, integration_id_for

#: How long a success stays good, per kind, in seconds. The server decides the
#: ``ok``/``stale`` threshold once. Twice the cadence of the job
#: that stamps it: Home Assistant is checked every five minutes, the MQTT
#: publish runs twice an hour.
OK_FOR_S: Mapping[str, float] = {
    HOME_ASSISTANT: 900.0,
    "mqtt": 3600.0,
}

#: For a kind this worker does not run (a calendar row, say): a day. Long
#: enough not to cry wolf about a job whose cadence the hub does not know.
DEFAULT_OK_FOR_S = 86400.0

#: ``sensor_source.adapter``'s CHECK, which the contract's enum repeats.
ADAPTERS = frozenset(
    {HOME_ASSISTANT, "ecowitt", "miflora", "homekit", "nest", "manual"}
)


def secrets_of(settings: HubSettings) -> tuple[str, ...]:
    """The literal values :func:`~workers.hub.health.redact` must remove."""
    return tuple(
        value
        for value in (
            settings.ha_token.get_secret_value(),
            settings.mqtt_password.get_secret_value(),
        )
        if value
    )


# ------------------------------------------------------------- integrations


def _configured(kind: str, settings: HubSettings) -> bool:
    from .world import _is_configured

    if kind in (HOME_ASSISTANT, "mqtt"):
        return _is_configured(kind, settings)
    # A row of a kind the hub does not run exists because somebody configured it.
    return True


def merge_integrations(
    rows: Sequence[Mapping[str, Any]], settings: HubSettings
) -> list[IntegrationHealth]:
    """The hub's two integrations always, plus every other row the table holds."""
    from .world import HUB_INTEGRATIONS

    by_id = {str(row["id"]): row for row in rows}
    out: list[IntegrationHealth] = []
    for kind, name in HUB_INTEGRATIONS:
        row = by_id.pop(integration_id_for(kind, name), None)
        base = (
            IntegrationHealth.from_row(dict(row))
            if row is not None
            else IntegrationHealth(
                id=integration_id_for(kind, name), kind=kind, name=name
            )
        )
        out.append(
            replace(
                base,
                configured=_configured(kind, settings),
                ok_for_s=OK_FOR_S.get(kind, DEFAULT_OK_FOR_S),
            )
        )
    for row in by_id.values():
        kind = str(row.get("kind") or "")
        out.append(
            IntegrationHealth.from_row(
                dict(row),
                configured=_configured(kind, settings),
                ok_for_s=OK_FOR_S.get(kind, DEFAULT_OK_FOR_S),
            )
        )
    return out


async def list_integrations(
    settings: HubSettings,
    connection: Connection | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """``GET /hub/integrations``: one contract ``Integration`` per integration.

    With no connection (mock mode) there are no rows, and every integration is
    exactly as configured as the settings say and has never been heard from.
    """
    rows: list[Mapping[str, Any]] = []
    if connection is not None:
        from . import store

        rows = [dict(row) for row in await store.read_integrations(connection)]
    moment = now or datetime.now(UTC)
    secrets = secrets_of(settings)
    return [
        item.to_contract(moment, secrets) for item in merge_integrations(rows, settings)
    ]


# ------------------------------------------------------------------ sensors


class SensorRejected(ValueError):
    """A ``POST /hub/sensors`` body this deployment cannot use, and why."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True, slots=True)
class Checked:
    """A source that passed, and what was — and was not — checked about it."""

    source: SensorSource
    #: One plain sentence for the response's ``X-Hub-Check`` header. The
    #: contract's ``SensorSource`` has no field for it and none is invented.
    note: str


def parse_source(body: Mapping[str, Any]) -> SensorSource:
    """The request body as a :class:`SensorSource`, with a fresh id.

    ``id`` and ``last_seen_at`` are the server's: a client cannot claim a
    sensor has reported, and an id it supplies is ignored rather than trusted
    to be unique.
    """
    problems: list[str] = []
    name = str(body.get("name") or "").strip()
    if not name:
        problems.append("name is required")
    adapter = str(body.get("adapter") or "")
    if adapter not in ADAPTERS:
        problems.append(
            f"adapter must be one of {', '.join(sorted(ADAPTERS))}; got {adapter!r}"
        )
    external = body.get("external_ids") or {}
    if not isinstance(external, Mapping) or not all(
        isinstance(value, str) for value in external.values()
    ):
        problems.append("external_ids must map metric names to entity id strings")
        external = {}
    poll = body.get("poll_seconds", 300)
    if not isinstance(poll, int) or isinstance(poll, bool) or poll <= 0:
        problems.append("poll_seconds must be a positive whole number of seconds")
        poll = 300
    for key in ("location_id", "specimen_id"):
        value = body.get(key)
        if value is not None:
            try:
                uuid.UUID(str(value))
            except ValueError:
                problems.append(f"{key} must be a uuid or null")
    if problems:
        raise SensorRejected(problems)
    return SensorSource(
        id=str(uuid.uuid4()),
        name=name,
        adapter=adapter,
        external_ids={str(k): str(v) for k, v in dict(external).items()},
        location_id=_opt(body.get("location_id")),
        specimen_id=_opt(body.get("specimen_id")),
        poll_seconds=poll,
        enabled=bool(body.get("enabled", True)),
    )


def shape_problems(source: SensorSource) -> list[str]:
    """What is wrong with a Home Assistant mapping on its face.

    The contract keeps ``external_ids`` open for metrics this app does not
    know, so an unknown *key* is accepted and simply not polled.
    What is refused is an entity id that cannot carry a number, and a soil
    metric with no pot behind it.
    """
    if source.adapter != HOME_ASSISTANT:
        return []
    from .entities import SOIL_METRICS

    problems: list[str] = []
    for metric, entity in sorted(source.external_ids.items()):
        domain, _, object_id = entity.partition(".")
        if not domain or not object_id:
            problems.append(
                f"{entity!r} is not a Home Assistant entity id "
                "(expected <domain>.<object_id>, e.g. sensor.greenhouse_temperature)"
            )
        elif domain not in NUMERIC_DOMAINS:
            problems.append(
                f"{entity!r} is a {domain} entity, which carries no reading; "
                f"use one of: {', '.join(sorted(NUMERIC_DOMAINS))}"
            )
        if metric in SOIL_METRICS and not source.specimen_id:
            problems.append(
                f"{metric} needs a specimen_id — a soil reading with no pot "
                "behind it would invent a probe"
            )
    return problems


async def check_source(
    source: SensorSource,
    settings: HubSettings,
    *,
    ha: Any = None,
) -> Checked:
    """Can the adapter read what this row names? Says plainly when it cannot ask.

    ``ha`` is a :class:`~workers.hub.sources.home_assistant.HomeAssistantSource`;
    passed in by tests, built from the settings otherwise. It is only consulted
    in live mode with a configured hub: in mock mode the "Home Assistant" is
    synthesised, and checking a household's entity against it would be
    checking against fiction.
    """
    problems = shape_problems(source)
    if problems:
        raise SensorRejected(problems)
    unknown = sorted(set(source.external_ids) - set(SUPPORTED_METRICS))
    extra = (
        f" Not polled, because this app does not store them: {', '.join(unknown)}."
        if unknown
        else ""
    )
    if source.adapter != HOME_ASSISTANT:
        return Checked(
            source,
            f"Saved. The {source.adapter} adapter is not polled in this version, "
            "so nothing was checked." + extra,
        )
    if settings.mock_mode:
        return Checked(
            source,
            "Saved in mock mode: the entity ids were checked for shape only, not "
            "against a Home Assistant, because mock mode has none." + extra,
        )
    if not settings.is_configured:
        return Checked(
            source,
            "Saved, but not checked: no Home Assistant is configured "
            "(MOH_HA_BASE_URL and its token)." + extra,
        )
    if ha is None:
        from .factory import build_source

        ha = build_source(settings)
    from .health import redact

    try:
        states = await ha.states()
    except Exception as exc:  # noqa: BLE001 - reported to the operator, not raised
        reason = redact(str(exc), secrets_of(settings)) or type(exc).__name__
        return Checked(
            source,
            f"Saved, but not checked: Home Assistant did not answer ({reason})."
            + extra,
        )
    missing = sorted(
        entity for entity in source.external_ids.values() if entity not in states
    )
    if missing:
        raise SensorRejected(
            [f"Home Assistant has no entity {entity!r}" for entity in missing]
        )
    return Checked(
        source, "Saved. Every entity id was found in Home Assistant." + extra
    )


# --------------------------------------------------------- mock-mode store


class MockSensorStore:
    """The derived world's sources plus whatever was posted, in memory.

    The build-against-mocks rule writable mock: The app's screens can build the Office's "add a
    sensor" flow with
    no database. Nothing here survives a restart and nothing pretends to.
    """

    def __init__(self, settings: HubSettings) -> None:
        from . import world

        self._rows: list[SensorSource] = list(world.sensor_sources(settings))

    def list(self) -> list[SensorSource]:
        return list(self._rows)

    def add(self, source: SensorSource) -> SensorSource:
        self._rows.append(source)
        return source


_MOCK: MockSensorStore | None = None


def mock_store(settings: HubSettings) -> MockSensorStore:
    global _MOCK
    if _MOCK is None:
        _MOCK = MockSensorStore(settings)
    return _MOCK


def reset_mock_store() -> None:
    """Back to the derived world. For tests."""
    global _MOCK
    _MOCK = None


async def list_sensors(
    settings: HubSettings, connection: Connection | None = None
) -> list[dict[str, Any]]:
    if connection is None:
        return [source.to_dict() for source in mock_store(settings).list()]
    from . import store

    rows = await store.read_sensor_sources(connection)
    return [SensorSource.from_row(dict(row)).to_dict() for row in rows]


async def create_sensor(
    settings: HubSettings,
    body: Mapping[str, Any],
    connection: Connection | None = None,
    *,
    ha: Any = None,
) -> Checked:
    checked = await check_source(parse_source(body), settings, ha=ha)
    if connection is None:
        mock_store(settings).add(checked.source)
    else:
        from . import store

        sql, params = store.insert_sensor_source_sql(checked.source)
        await connection.execute(sql, *params)
    return checked


def _opt(value: Any) -> str | None:
    return None if value is None else str(value)
