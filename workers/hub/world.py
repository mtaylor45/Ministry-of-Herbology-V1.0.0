"""The world this worker runs against with no Home Assistant — the hub.

The build-against-mocks rule: every service ships a mock matching the contract, so no agent waits on
another and the whole stack runs with no network at all. For E that meant
weather payloads; for the hub it means something slightly different, because there
is no ``fixtures/sensors/`` file to read. ``fixtures/`` is L and the maintainers', and the
frozen set has a site, locations, species, specimens, scenarios and weather —
no ``sensor_source`` rows. So this module **derives** a plausible set from the
locations that already exist, and the pull request asks the maintainers and the test suite for the
real
fixture.

Three rules keep the derivation honest, and the third is the one that matters.

1. **Everything derived says so.** Every source built here carries a
   ``_synthetic`` note through :func:`describe`, and the mock fetcher stamps
   the same on every payload. A mock cannot quietly pass for a fetch — in a
   test, in a log, or on a screen.
2. **Only indoor locations get one.** An outdoor bed's temperature comes from
   The weather engine's weather ingest, not from a thermostat, and inventing an
   outdoor HA sensor would put two different answers for the same question
   into one database.
3. **No soil probe is invented.** the design is unambiguous: there is no
   soil-moisture hardware and none is expected in v1.0. The adapter's soil
   path is complete — :mod:`workers.hub.mapping` will bind a probe to a
   specimen and :mod:`workers.hub.entities` will store its reading the day one
   appears — but nothing in this file claims one exists. The mock has no
   ``soil_moisture_pct`` entity, and the day a household adds a real probe the
   only change needed is a ``sensor_source`` row.
"""

from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from .health import IntegrationHealth
from .mapping import SensorSource
from .settings import HubSettings, get_settings
from .sources.base import HOME_ASSISTANT
from .store import integration_id_for

#: Namespace for the derived source ids. Fixed so a mock's ids are the same in
#: every checkout, which is what lets a test assert one.
DERIVED_NAMESPACE = uuid.UUID("6f6d6f68-0000-5000-8000-000000000f01")

#: What a derived indoor source maps. A thermostat reports both, and these two
#: are exactly what the releases's exit criterion is about.
DERIVED_METRICS = ("temperature_c", "humidity_pct")

#: HA entity suffixes for those metrics, in the naming a real installation
#: uses (``sensor.<area>_temperature``).
_ENTITY_SUFFIX = {
    "temperature_c": "temperature",
    "humidity_pct": "humidity",
}

#: The integrations a v1.0 deployment has rows for. ``integration.kind``'s
#: CHECK allows seven; these are the two this worker owns.
HUB_INTEGRATIONS = (
    (HOME_ASSISTANT, "Home Assistant"),
    ("mqtt", "MQTT broker"),
)


def slug(name: str) -> str:
    """``"Greenhouse Window"`` into ``"greenhouse_window"``."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _settings(settings: HubSettings | None) -> HubSettings:
    return settings or get_settings()


@lru_cache
def _read(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else []


def locations(settings: HubSettings | None = None) -> list[dict[str, Any]]:
    config = _settings(settings)
    rows = _read(config.fixtures_dir / "locations" / "locations.json")
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def indoor_locations(settings: HubSettings | None = None) -> list[dict[str, Any]]:
    return [row for row in locations(settings) if not row.get("is_outdoor")]


def sensor_sources(settings: HubSettings | None = None) -> list[SensorSource]:
    """One Home Assistant climate source per indoor location.

    ``poll_seconds`` is the schema's own default of 300 — five minutes, the
    fast end of the releases's 5–15 minute band, and the right cadence for a
    room whose temperature a person can feel changing.
    """
    sources: list[SensorSource] = []
    for row in indoor_locations(settings):
        area = slug(str(row.get("name") or ""))
        if not area:
            continue
        sources.append(
            SensorSource(
                id=str(uuid.uuid5(DERIVED_NAMESPACE, str(row["id"]))),
                name=str(row["name"]),
                adapter=HOME_ASSISTANT,
                external_ids={
                    metric: f"sensor.{area}_{_ENTITY_SUFFIX[metric]}"
                    for metric in DERIVED_METRICS
                },
                location_id=str(row["id"]),
                poll_seconds=300,
                enabled=True,
            )
        )
    return sources


def integrations(settings: HubSettings | None = None) -> list[IntegrationHealth]:
    """The rows the Ministry Office reads, with no database attached.

    ``configured`` comes from the settings rather than from a guess, so an
    install with no ``MOH_HA_BASE_URL`` reads as *unconfigured* — a setup step
    — rather than as *down*, which is a fault. Telling those two apart is most
    of what this screen is for.
    """
    config = _settings(settings)
    return [
        IntegrationHealth(
            id=integration_id_for(kind, name),
            kind=kind,
            name=name,
            enabled=True,
            configured=_is_configured(kind, config),
        )
        for kind, name in HUB_INTEGRATIONS
    ]


def _is_configured(kind: str, config: HubSettings) -> bool:
    """Has this deployment been given what the integration needs to run?

    For Home Assistant that is a base URL and a token. For MQTT it is a named
    broker *and* a client library to reach it with: ``MOH_MQTT_HOST`` has no
    default, and an image built without ``aiomqtt`` cannot publish
    whatever the broker setting says. Reporting either gap as
    *unconfigured* rather than as *down* is the difference between a setup
    step and a fault, and a health screen that cries wolf on a fresh install
    is a health screen nobody reads on the day it means something.
    """
    from .mqtt import transport_available

    if kind == HOME_ASSISTANT:
        return config.is_configured
    return bool(config.mqtt_host) and transport_available()


def describe(settings: HubSettings | None = None) -> dict[str, Any]:
    """What the mock world contains, and that it is a mock.

    Returned by the jobs in mock mode and asserted by the tests, so "these
    sources were derived, not configured" travels with the data rather than
    living only in this docstring.
    """
    sources = sensor_sources(settings)
    return {
        "_synthetic": {
            "from": "fixtures/locations/locations.json",
            "note": (
                "Mock mode. One Home Assistant climate source derived per "
                "indoor location, because fixtures/ has no sensor_source "
                "rows. No soil probe is derived: the design says none exists."
            ),
        },
        "sources": [source.to_dict() for source in sources],
    }
