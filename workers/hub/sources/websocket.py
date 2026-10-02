"""Home Assistant's WebSocket API — the protocol, without the socket.

REST polling is what ships this release and what meets the exit criterion: a
reading every five minutes is a reading every five minutes, and a poll is the
thing that keeps working through a hub restart, a Wi-Fi drop and a laptop
suspend. The WebSocket API is the *optimisation* on top of it — events arrive
the moment a sensor changes rather than up to five minutes later — and it is
worth having because a soil probe that reports once an hour at an unknown
minute is badly served by any polling interval.

What is here is everything about that protocol that is not a socket:

* the handshake, which Home Assistant drives and which is easy to get subtly
  wrong (it greets *first*, the token goes in the second frame, and the id
  counter starts at 1 and never repeats within a connection);
* :func:`entity_state_from_event`, which turns a ``state_changed`` event into
  the same :class:`~workers.hub.sources.base.EntityState` the REST parser
  produces, so exactly one set of rules in :mod:`workers.hub.entities` decides
  what becomes a reading, whichever way the value arrived;
* :class:`Backoff`, the reconnect schedule.

What is **not** here is the transport. ``api/pyproject.toml`` carries no
WebSocket client and the hub does not own that file, so adding ``websockets`` (or
reusing ``httpx``'s) is a request to the maintainers and the deployment — it is in the pull request.
The
seam is :class:`Transport` below: a class with ``send_json`` and ``receive_json``
is the entire remaining surface, and :class:`MemoryTransport` plays both sides
of the handshake in the tests today.

**The token appears in exactly one frame**, built by :func:`auth_message`, and
nothing in this module logs a frame.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .base import EntityState, HubUnavailable, parse_state

#: The event Home Assistant emits when any entity changes. It is the only one
#: this adapter subscribes to: subscribing to everything and filtering on our
#: side would carry every button press on the network over the wire.
STATE_CHANGED = "state_changed"


@runtime_checkable
class Transport(Protocol):
    """A bidirectional JSON channel. The only thing that would open a socket."""

    async def send_json(self, message: Mapping[str, Any]) -> None: ...

    async def receive_json(self) -> Mapping[str, Any]: ...


def auth_message(token: str) -> dict[str, Any]:
    """The second frame of the handshake — the only one carrying the token."""
    return {"type": "auth", "access_token": token}


def subscribe_message(
    message_id: int, event_type: str = STATE_CHANGED
) -> dict[str, Any]:
    """Ask for one event type. Ids are per-connection and must not repeat."""
    return {
        "id": message_id,
        "type": "subscribe_events",
        "event_type": event_type,
    }


def entity_state_from_event(event: Mapping[str, Any]) -> EntityState | None:
    """A ``state_changed`` event's *new* state, as the REST parser would give it.

    Returns ``None`` for anything else, including the event Home Assistant
    sends when an entity is removed (``new_state: null``). That is a real
    absence and it is handled by the entity simply stopping — not by
    synthesising a final reading for it.
    """
    if event.get("event_type") != STATE_CHANGED:
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    return parse_state(data.get("new_state"))


@dataclass(slots=True)
class Handshake:
    """Home Assistant's connect sequence, as a small state machine.

    It is a state machine rather than three awaits in a row because the
    failure that matters — ``auth_invalid`` — is a refused token, and telling
    that apart from a dropped connection is the difference between "check
    MOH_HA_TOKEN" and "check the hub is on".
    """

    token: str
    _next_id: int = 1

    def take_id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current

    async def run(self, transport: Transport) -> str:
        """Authenticate. Returns the version Home Assistant reports.

        Raises :class:`HubUnavailable` on a refusal, with the token nowhere in
        the message.
        """
        greeting = await transport.receive_json()
        if greeting.get("type") != "auth_required":
            raise HubUnavailable(
                "home_assistant: the WebSocket greeted with "
                f"{str(greeting.get('type'))!r}, not auth_required"
            )
        await transport.send_json(auth_message(self.token))
        answer = await transport.receive_json()
        if answer.get("type") == "auth_invalid":
            raise HubUnavailable(
                "home_assistant: the WebSocket refused the access token. "
                "Check MOH_HA_TOKEN."
            )
        if answer.get("type") != "auth_ok":
            raise HubUnavailable(
                "home_assistant: the WebSocket answered "
                f"{str(answer.get('type'))!r} to auth"
            )
        return str(answer.get("ha_version") or "unknown")

    async def subscribe(
        self, transport: Transport, event_type: str = STATE_CHANGED
    ) -> int:
        """Subscribe, and confirm Home Assistant accepted it.

        The confirmation is checked rather than assumed. An unconfirmed
        subscription is a connection that stays open and silent forever, which
        is exactly the failure this parts of the project is not allowed to have.
        """
        message_id = self.take_id()
        await transport.send_json(subscribe_message(message_id, event_type))
        reply = await transport.receive_json()
        if reply.get("id") != message_id or not reply.get("success"):
            raise HubUnavailable(
                "home_assistant: the WebSocket would not subscribe to "
                f"{event_type} ({_error_of(reply)})"
            )
        return message_id


def _error_of(reply: Mapping[str, Any]) -> str:
    error = reply.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("code") or error)[:120]
    return "no reason given"


@dataclass(slots=True)
class Backoff:
    """Reconnect delays: exponential, capped, and jittered.

    Jittered because a household with the hub and the app on one machine
    restarts both at once, and a fixed schedule means every reconnect attempt
    lands in the same instant as the last one that failed.
    """

    first_s: float = 1.0
    cap_s: float = 300.0
    factor: float = 2.0
    jitter: float = 0.25
    attempts: int = 0
    _random: random.Random = field(default_factory=random.Random)

    def reset(self) -> None:
        self.attempts = 0

    def next_delay(self) -> float:
        delay = min(self.first_s * self.factor**self.attempts, self.cap_s)
        self.attempts += 1
        spread = delay * self.jitter
        return max(0.0, delay + self._random.uniform(-spread, spread))
