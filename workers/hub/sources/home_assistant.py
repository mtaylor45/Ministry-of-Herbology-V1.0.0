"""The Home Assistant adapter — the hub.

the design settles what this is: **the only route to indoor conditions**, spoken
to over its own REST API, addressing devices by entity id. There is no
Nest-specific, HomeKit-specific or Matter-specific code here and there is not
meant to be. Whatever Home Assistant exposes we can read; how it came by it is
Home Assistant's problem.

## One request per poll

``GET /api/states`` returns every entity in the installation. This adapter
asks for that once and indexes it, rather than issuing one request per mapped
entity. Both name a missing entity precisely — an entity absent from the
collection is reported as ``entity_not_found`` with its id — and the bulk call
is one round trip whether a household has mapped two sensors or twenty.

## Absence is reported, never filled

Every mapped entity that does not become a reading leaves as a
:class:`~workers.hub.sources.base.Skipped` naming why: not found, unavailable,
stale, wrong device class, unconvertible unit, out of range. The job puts that
list in its report and the count on ``integration.last_error`` when it is the
whole story. Nothing here substitutes a default, a last-known value or a zero
— the design rule, and the reason a gap in the Almanac has to render as "no
recent reading" rather than as a line drawn across it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from ..entities import reading_from_state
from ..mapping import SensorSource
from ..settings import HubSettings, get_settings
from .base import (
    EntityState,
    Fetcher,
    HubUnavailable,
    PollResult,
    Reading,
    Skipped,
    parse_states,
)

#: ``GET /api/`` — Home Assistant's own liveness endpoint. It answers
#: ``{"message": "API running."}`` with a valid token and 401 without one,
#: which makes it the cheapest way to tell "hub is down" from "token is wrong".
PROBE_PATH = "/"
STATES_PATH = "/states"


class HomeAssistantSource:
    """Reads entity states and turns the mapped ones into ``reading`` rows."""

    def __init__(
        self,
        fetcher: Fetcher,
        settings: HubSettings | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.settings = settings or get_settings()

    async def probe(self) -> str:
        """Is Home Assistant answering? Returns its own greeting.

        Raises :class:`HubUnavailable` when it is not, which is what the
        health job records. The message is Home Assistant's, so a proxy
        returning an unexpected 200 is visible rather than counted as health.
        """
        result = await self.fetcher.get_json("home_assistant", PROBE_PATH)
        payload = result.payload
        message = (payload.get("message") if isinstance(payload, dict) else None) or ""
        if "running" not in str(message).lower():
            raise HubUnavailable(
                "home_assistant: the API root answered, but not as Home "
                f"Assistant does ({str(message)[:80]!r})"
            )
        return str(message)

    async def states(self) -> dict[str, EntityState]:
        """Every entity Home Assistant currently has, keyed by entity id."""
        result = await self.fetcher.get_json("home_assistant", STATES_PATH)
        return parse_states(result.payload)

    async def poll(
        self,
        sources: Sequence[SensorSource],
        *,
        now: datetime | None = None,
    ) -> PollResult:
        """Read every mapped entity in ``sources`` once.

        The whole poll shares one ``now``: the readings from one run belong to
        one moment, and letting each entity carry its own timestamp would put
        the study and the greenhouse in different hourly buckets on a slow
        night.
        """
        at = now or datetime.now(UTC)
        if not sources:
            return PollResult(polled_at=at)
        try:
            states = await self.states()
        except HubUnavailable as exc:
            # Not re-raised. A hub that is down is a fact to record on
            # ``integration.last_error`` and show in the Ministry Office, not
            # an exception for Arq to log and forget.
            return PollResult(error=str(exc), polled_at=at)

        readings: list[Reading] = []
        skipped: list[Skipped] = []
        for source in sources:
            for metric, entity_id in source.bindings():
                state = states.get(entity_id)
                if state is None:
                    skipped.append(
                        Skipped(
                            entity_id,
                            metric,
                            "entity_not_found",
                            f"{source.name}: Home Assistant has no {entity_id}",
                        )
                    )
                    continue
                outcome = reading_from_state(
                    state,
                    metric=metric,
                    source_id=source.id,
                    at=at,
                    location_id=source.location_id,
                    specimen_id=source.specimen_id,
                    max_age_s=self.settings.entity_max_age_s,
                )
                if isinstance(outcome, Reading):
                    readings.append(outcome)
                else:
                    skipped.append(outcome)

        return PollResult(
            readings=tuple(readings),
            skipped=tuple(skipped),
            is_mock=getattr(self.fetcher, "is_mock", False),
            polled_at=at,
        )
