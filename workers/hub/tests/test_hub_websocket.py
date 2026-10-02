"""Home Assistant's WebSocket protocol, without the socket — the hub.

The transport waits on a dependency the hub does not own (see the module docstring
and the earlier pull request). Everything that is *not* the socket is here and is
tested, so the day ``websockets`` lands the remaining work is a class with two
methods.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from workers.hub.sources.base import HubUnavailable
from workers.hub.sources.websocket import (
    STATE_CHANGED,
    Backoff,
    Handshake,
    auth_message,
    entity_state_from_event,
    subscribe_message,
)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.aVeryLongLivedAccessToken.signaturegoeshere"


class MemoryTransport:
    """Plays Home Assistant's side of the conversation."""

    def __init__(self, *incoming: Mapping[str, Any]) -> None:
        self.incoming = list(incoming)
        self.sent: list[Mapping[str, Any]] = []

    async def send_json(self, message: Mapping[str, Any]) -> None:
        self.sent.append(message)

    async def receive_json(self) -> Mapping[str, Any]:
        return self.incoming.pop(0)


def test_the_handshake_greets_first_and_the_token_goes_in_the_second_frame(run):
    transport = MemoryTransport(
        {"type": "auth_required", "ha_version": "2026.6.1"},
        {"type": "auth_ok", "ha_version": "2026.6.1"},
    )
    version = run(Handshake(TOKEN).run(transport))
    assert version == "2026.6.1"
    assert transport.sent == [{"type": "auth", "access_token": TOKEN}]


def test_a_refused_token_is_told_apart_from_a_dropped_connection(run):
    """The difference between "check MOH_HA_TOKEN" and "check the hub is on"."""
    transport = MemoryTransport({"type": "auth_required"}, {"type": "auth_invalid"})
    with pytest.raises(HubUnavailable, match="MOH_HA_TOKEN"):
        run(Handshake(TOKEN).run(transport))


def test_the_refusal_does_not_quote_the_token_back(run):
    transport = MemoryTransport({"type": "auth_required"}, {"type": "auth_invalid"})
    with pytest.raises(HubUnavailable) as raised:
        run(Handshake(TOKEN).run(transport))
    assert TOKEN not in str(raised.value)


def test_something_that_is_not_home_assistant_is_not_authenticated_against(run):
    transport = MemoryTransport({"type": "hello"})
    with pytest.raises(HubUnavailable, match="not auth_required"):
        run(Handshake(TOKEN).run(transport))
    assert transport.sent == []  # the token was never sent


def test_a_subscription_is_confirmed_rather_than_assumed(run):
    """An unconfirmed subscription is a connection that stays open and silent
    forever, which is exactly the failure this parts of the project is not allowed to
    have."""
    transport = MemoryTransport({"id": 1, "type": "result", "success": True})
    handshake = Handshake(TOKEN)
    assert run(handshake.subscribe(transport)) == 1
    assert transport.sent == [
        {"id": 1, "type": "subscribe_events", "event_type": STATE_CHANGED}
    ]


def test_a_refused_subscription_raises_with_the_reason(run):
    transport = MemoryTransport(
        {
            "id": 1,
            "type": "result",
            "success": False,
            "error": {"code": "invalid_format", "message": "no such event"},
        }
    )
    with pytest.raises(HubUnavailable, match="no such event"):
        run(Handshake(TOKEN).subscribe(transport))


def test_message_ids_do_not_repeat_within_a_connection():
    handshake = Handshake(TOKEN)
    assert [handshake.take_id() for _ in range(3)] == [1, 2, 3]


def test_the_message_builders_are_the_shapes_home_assistant_documents():
    assert auth_message(TOKEN) == {"type": "auth", "access_token": TOKEN}
    assert subscribe_message(7) == {
        "id": 7,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }


def test_an_event_parses_into_the_same_entity_state_the_rest_parser_gives():
    """One set of rules in ``entities.py`` decides what becomes a reading,
    whichever way the value arrived."""
    state = entity_state_from_event(
        {
            "event_type": "state_changed",
            "data": {
                "entity_id": "sensor.study_temperature",
                "new_state": {
                    "entity_id": "sensor.study_temperature",
                    "state": "21.4",
                    "attributes": {
                        "unit_of_measurement": "°C",
                        "device_class": "temperature",
                    },
                    "last_updated": "2026-06-15T11:58:00+00:00",
                },
            },
        }
    )
    assert state is not None
    assert state.numeric == pytest.approx(21.4)
    assert state.device_class == "temperature"


def test_a_removed_entity_does_not_synthesise_a_final_reading():
    """That is a real absence, and it is handled by the entity stopping."""
    assert (
        entity_state_from_event(
            {
                "event_type": "state_changed",
                "data": {"entity_id": "sensor.gone", "new_state": None},
            }
        )
        is None
    )


def test_another_event_type_is_ignored():
    assert entity_state_from_event({"event_type": "call_service"}) is None


def test_reconnects_back_off_and_are_capped():
    backoff = Backoff(first_s=1.0, cap_s=8.0, jitter=0.0)
    assert [backoff.next_delay() for _ in range(5)] == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_reconnects_are_jittered_so_a_household_does_not_retry_in_lockstep():
    """The hub and the app often restart together; a fixed schedule means
    every attempt lands in the same instant as the last one that failed."""
    import random

    backoff = Backoff(first_s=10.0, jitter=0.25, _random=random.Random(0))
    delays = {
        round(
            Backoff(
                first_s=10.0, jitter=0.25, _random=random.Random(seed)
            ).next_delay(),
            6,
        )
        for seed in range(5)
    }
    assert len(delays) > 1
    assert all(7.5 <= delay <= 12.5 for delay in delays)
    backoff.reset()
    assert backoff.attempts == 0
