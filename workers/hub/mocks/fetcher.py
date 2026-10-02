"""A Home Assistant that answers with no Home Assistant — the hub.

The build-against-mocks rule again, with one honest difference from the weather engine's version
worth
stating at the top rather than in a footnote.

**There are no recordings here.** E could record NWS and Open-Meteo because
both answer an anonymous request from any host. Home Assistant answers nobody:
it is somebody's house, reached over their network, behind a long-lived access
token. There is no public instance to record and this branch went looking for
no private one — the brief's rule about credentials cuts both ways, and a
payload obtained by finding somebody's exposed hub would be worse than no
payload at all.

So every response this fetcher serves is **synthesised** in Home Assistant's
documented ``GET /api/states`` shape, from the frozen fixtures, and every one
carries a ``_synthetic`` marker so it cannot pass for a fetch. ``recorded/``
exists, is empty, and explains itself; ``record.py`` fills it from a real
instance the day somebody runs it against their own, and :class:`RecordedFetcher`
prefers a real recording the moment one appears.

## What the synthesised installation contains

The mapped entities from :func:`workers.hub.world.sensor_sources` — one
temperature and one humidity sensor per indoor location — and a handful of
entities nothing maps: a light, a switch, an outdoor weather entity. Those are
not padding. A real Home Assistant carries hundreds of entities and the
adapter's first job is to ignore all of them, so the mock has to be chatty
enough for a test to prove it.

Nothing awkward is synthesised: no Fahrenheit thermostat, no dead battery, no
soil probe. A mock world that contains a broken sensor would make every job's
report in mock mode contain a failure that is not real, and the failure paths
deserve tests that name them rather than a world that quietly includes them.
Those live in ``tests/test_hub_entities.py``, built entity by entity.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..settings import HubSettings, get_settings
from ..sources.base import FetchResult, HubUnavailable

RECORDED_DIR = Path(__file__).resolve().parent / "recorded"

#: Home Assistant's greeting at ``GET /api/``. Quoted from its REST API
#: documentation, which is where this string is specified.
API_RUNNING = "API running."

#: Entities the synthesised installation carries that nothing maps. A real hub
#: has hundreds; three is enough to prove the adapter ignores them.
UNMAPPED_ENTITIES: tuple[dict[str, Any], ...] = (
    {
        "entity_id": "light.study_lamp",
        "state": "on",
        "attributes": {"friendly_name": "Study Lamp", "brightness": 180},
    },
    {
        "entity_id": "switch.greenhouse_fan",
        "state": "off",
        "attributes": {"friendly_name": "Greenhouse Fan"},
    },
    {
        "entity_id": "weather.home",
        "state": "partlycloudy",
        "attributes": {"friendly_name": "Home", "temperature": 17.0},
    },
)


def recording_name(kind: str, path: str) -> str | None:
    """Which file under ``recorded/`` answers this request, if any."""
    clean = path.split("?", 1)[0].strip("/")
    if kind != "home_assistant":
        return None
    if clean == "":
        return "home_assistant/api__root.json"
    if clean == "states":
        return "home_assistant/states__all.json"
    return None


class RecordedFetcher:
    """A ``Fetcher`` that never opens a socket.

    ``now`` is injected rather than read off the clock so a test can freeze
    it. That matters more here than it does for weather: every synthesised
    entity's ``last_updated`` is relative to it, and freshness — whether a
    value counts as a measurement at all — is decided by exactly that
    difference.
    """

    is_mock = True

    def __init__(
        self,
        settings: HubSettings | None = None,
        recorded_dir: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.recorded_dir = recorded_dir or RECORDED_DIR
        self._now = now or (lambda: datetime.now(UTC))
        #: Every request this fetcher served, for tests that count calls.
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        #: Every service call, with its body. What the notification tests read.
        self.posted: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(
        self, kind: str, path: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        params = dict(params or {})
        self.calls.append((kind, path, params))
        moment = self._now()

        name = recording_name(kind, path)
        if name:
            recorded = self.recorded_dir / name
            if recorded.exists():
                return FetchResult(
                    url=path,
                    payload=json.loads(recorded.read_text()),
                    retrieved_at=moment,
                    is_mock=True,
                )

        clean = path.split("?", 1)[0].strip("/")
        if kind == "home_assistant" and clean == "":
            return FetchResult(
                url=path,
                payload={"message": API_RUNNING, **_synthetic()},
                retrieved_at=moment,
                is_mock=True,
            )
        if kind == "home_assistant" and clean == "states":
            return FetchResult(
                url=path,
                payload=self._states(moment),
                retrieved_at=moment,
                is_mock=True,
            )
        if kind == "home_assistant" and clean.startswith("states/"):
            entity_id = clean.split("/", 1)[1]
            for row in self._states(moment):
                if isinstance(row, dict) and row.get("entity_id") == entity_id:
                    return FetchResult(
                        url=path, payload=row, retrieved_at=moment, is_mock=True
                    )
            raise HubUnavailable(
                f"{kind}: Home Assistant has no {entity_id} (HTTP 404)."
            )

        raise HubUnavailable(
            f"{kind}: nothing recorded for {path} and nothing to synthesise"
        )

    async def post_json(
        self, kind: str, path: str, body: Mapping[str, Any] | None = None
    ) -> FetchResult:
        """A service call that goes nowhere, and is kept so a test can read it.

        Mock mode has to be able to demonstrate the notification path end to
        end — the earlier exit criterion is shown on the mock stack before it is
        shown on a deployment — and the useful half of a service call is the
        body, not the socket. ``posted`` is what the tests assert against.

        A ``notify`` service call is answered the way Home Assistant answers
        one: ``200`` with an empty list, because it changed no entity's state.
        """
        payload = dict(body or {})
        self.posted.append((kind, path, payload))
        self.calls.append((kind, path, {}))
        clean = path.split("?", 1)[0].strip("/")
        if kind == "home_assistant" and clean.startswith("services/"):
            return FetchResult(
                url=path, payload=[], retrieved_at=self._now(), is_mock=True
            )
        raise HubUnavailable(f"{kind}: nothing to synthesise for POST {path}")

    # ------------------------------------------------------------ synthesis

    def _states(self, moment: datetime) -> list[dict[str, Any]]:
        from .. import world

        rows: list[dict[str, Any]] = []
        for source in world.sensor_sources(self.settings):
            area = world.slug(source.name)
            for metric, entity_id in source.bindings():
                rows.append(
                    _state_row(
                        entity_id=entity_id,
                        metric=metric,
                        area=area,
                        name=source.name,
                        moment=moment,
                    )
                )
        for extra in UNMAPPED_ENTITIES:
            rows.append(
                {
                    **extra,
                    "last_changed": moment.isoformat(),
                    "last_updated": moment.isoformat(),
                    **_synthetic(),
                }
            )
        return rows


class UnavailableFetcher:
    """A ``Fetcher`` for which Home Assistant is down.

    Under the design this is not a hypothetical: HA is the only route to indoor
    conditions, so "the hub is off" is a state every household will be in at
    some point, and the adapter's behaviour there is a shipping path. Having
    this here means it is exercised rather than reasoned about.
    """

    is_mock = True

    def __init__(self, reason: str = "mock: the hub is unreachable") -> None:
        self.reason = reason
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.posted: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(
        self, kind: str, path: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        self.calls.append((kind, path, dict(params or {})))
        raise HubUnavailable(f"{kind}: {self.reason}")

    async def post_json(
        self, kind: str, path: str, body: Mapping[str, Any] | None = None
    ) -> FetchResult:
        """A hub that is down cannot be notified through either.

        The same failure for a service call as for a read, because it is the
        same failure: Home Assistant is the only way out, so a
        hub that is unreachable means the notification did not happen and the
        job has to say so rather than count it sent.
        """
        self.posted.append((kind, path, dict(body or {})))
        raise HubUnavailable(f"{kind}: {self.reason}")


# ------------------------------------------------------------------ helpers


def _synthetic() -> dict[str, Any]:
    """Stamped into every synthesised payload, so a mock cannot pass for a fetch."""
    return {
        "_synthetic": {
            "from": "fixtures/locations/locations.json",
            "note": (
                "Mock mode. Built in Home Assistant's /api/states shape from "
                "the frozen fixtures, not fetched from Home Assistant. See "
                "workers/hub/mocks/recorded/PROVENANCE.md."
            ),
        }
    }


def _state_row(
    *, entity_id: str, metric: str, area: str, name: str, moment: datetime
) -> dict[str, Any]:
    value, unit, device_class = _value_for(metric, area, moment)
    return {
        "entity_id": entity_id,
        "state": f"{value:.1f}",
        "attributes": {
            "friendly_name": f"{name} {device_class.title()}",
            "unit_of_measurement": unit,
            "device_class": device_class,
            "state_class": "measurement",
        },
        # Two minutes old: a plausible gap between a sensor reporting and us
        # asking, and comfortably inside `entity_max_age_s`, so the mock
        # world's readings are fresh without being suspiciously instantaneous.
        "last_changed": _minus(moment, 120).isoformat(),
        "last_updated": _minus(moment, 120).isoformat(),
        **_synthetic(),
    }


def _minus(moment: datetime, seconds: float) -> datetime:
    from datetime import timedelta

    return moment - timedelta(seconds=seconds)


def _value_for(metric: str, area: str, moment: datetime) -> tuple[float, str, str]:
    """A defensible indoor climate — not a measurement, and not random either.

    Deterministic in the area name and the hour, so the same checkout gives
    the same numbers and a chart of the mock looks like a room rather than
    like noise. Rooms differ by a fixed offset; the day has a small swing,
    smaller than outdoors because that is what a house does.
    """
    offset = (sum(area.encode()) % 7) - 3  # −3..3, stable per room
    hour = moment.hour + moment.minute / 60.0
    swing = math.sin(math.pi * (hour - 5.0) / 12.0)
    if metric == "temperature_c":
        return 20.5 + offset * 0.4 + 1.2 * swing, "°C", "temperature"
    if metric == "humidity_pct":
        return 46.0 + offset * 1.5 - 6.0 * swing, "%", "humidity"
    raise ValueError(f"the mock world has no {metric} entity: see the module note")
