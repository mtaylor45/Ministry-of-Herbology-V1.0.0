"""Publishing back into Home Assistant — the hub.

``contracts/events/mqtt.md`` is the contract and this module implements it
literally: the topics, the payloads, the discovery configs, the retain flags
and the availability topic are all read from that file, not invented here. A
new topic is a contract change and goes to the maintainers as a recorded decision.

The whole point is that the Ministry's plants become *native* Home Assistant
entities — so a household can put "the mandrake needs water" on a dashboard,
speak it through an announcement, or hang an automation off it, without this
app knowing anything about any of that.

## Three rules the contract states, and this module enforces

**Everything is retained**, so Home Assistant restores state after a restart
rather than showing a wall of `unknown` until the next publish. That is the
default on :class:`Message` and the discovery configs set it too.

**Object ids are stable across restarts** — ``specimen_<uuid-without-dashes>``.
An object id derived from anything that moves (a list position, a name someone
can edit, a per-process id) silently orphans an entity's history the first
time it changes, and Home Assistant keeps the orphan forever.

**Nothing secret goes in a payload.** The ICS feed tokens the scheduler mints
are exactly the kind of thing that would otherwise end up in an attributes
blob — a calendar URL is a convenient thing to publish and it carries a
bearer token in its path. :func:`guard` refuses any payload that looks like it
carries a credential, and :func:`publish_all` runs every message through it.
It is a check rather than a comment because a comment does not fail a build.

## The transport

:func:`connect_publisher` speaks to the broker through ``aiomqtt``, written
against its interface and tested with a fake client injected through
:func:`_client_module`, so nothing has to be installed for CI to prove it.
The deployment adds ``aiomqtt`` to ``api/pyproject.toml`` (agreed on #56); until
then :func:`transport_available` is false and the Ministry Office says
*unconfigured*. The seam is still :class:`Publisher` — one ``publish``
coroutine — and :class:`MemoryPublisher` remains what most tests assert
against: the bytes on the topic, not the library that carried them.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from .credentials import FORBIDDEN_KEYS, SecretInPayload, assert_clean

#: Re-exported: ``contracts/events/mqtt.md`` states the rule ("nothing secret
#: goes in a payload") and a reader of this module should find its enforcement
#: here rather than having to go looking. The implementation moved to
#: :mod:`workers.hub.credentials` when notifications became a second way
#: a payload leaves this worker. One rule, one implementation, two senders.
__all__ = [
    "AVAILABILITY_TOPIC",
    "COMMAND_COMPLETE",
    "COMMAND_REFRESH",
    "COMMAND_TOPICS",
    "DISCOVERY_PREFIX",
    "FORBIDDEN_KEYS",
    "MQTT_PREFIX",
    "OFFLINE",
    "ONLINE",
    "ClientPublisher",
    "Command",
    "MemoryPublisher",
    "Message",
    "MqttNotConfigured",
    "Publisher",
    "SecretInPayload",
    "attributes_topic",
    "availability",
    "connect_publisher",
    "device_block",
    "discovery_config",
    "discovery_messages",
    "discovery_topic",
    "frost_messages",
    "guard",
    "last_will",
    "object_id_for",
    "parse_command",
    "publish_all",
    "rounds_messages",
    "specimen_messages",
    "state_topic",
    "transport_available",
]

#: Prefixes from the contract. ``homeassistant/`` is HA's discovery prefix and
#: is configurable at the HA end; ``herbology/`` is ours.
MQTT_PREFIX = "herbology"
DISCOVERY_PREFIX = "homeassistant"

#: The availability topic, and the last will published on it. Every discovery
#: config points at this, so one dropped connection greys out every entity
#: rather than freezing them all at their last value.
AVAILABILITY_TOPIC = f"{MQTT_PREFIX}/status"
ONLINE = "online"
OFFLINE = "offline"

#: Command topics this app subscribes to, from the contract.
COMMAND_COMPLETE = f"{MQTT_PREFIX}/cmd/task/+/complete"
COMMAND_REFRESH = f"{MQTT_PREFIX}/cmd/rounds/refresh"
COMMAND_TOPICS = (COMMAND_COMPLETE, COMMAND_REFRESH)

_COMPLETE_PATTERN = re.compile(rf"^{MQTT_PREFIX}/cmd/task/([^/]+)/complete$")


@dataclass(frozen=True, slots=True)
class Message:
    """One publish. Retained by default, because the contract says so."""

    topic: str
    payload: str
    retain: bool = True
    qos: int = 1

    def as_json(self) -> Any:
        """The payload parsed, for a test that wants to assert on structure."""
        return json.loads(self.payload)


def device_block(sw_version: str) -> dict[str, Any]:
    """The device every entity belongs to, from the contract, verbatim."""
    return {
        "identifiers": ["ministry_of_herbology"],
        "name": "The Ministry of Herbology",
        "manufacturer": "Ministry of Herbology",
        "model": "Greenhouse",
        "sw_version": sw_version,
    }


def state_topic(kind: str, key: str) -> str:
    """See ``contracts/events/mqtt.md`` — the layout is contract, not detail."""
    return f"{MQTT_PREFIX}/{kind}/{key}"


def attributes_topic(state: str) -> str:
    """ "The state topic plus ``/attributes``", from the contract."""
    return f"{state}/attributes"


def discovery_topic(component: str, object_id: str) -> str:
    return f"{DISCOVERY_PREFIX}/{component}/{MQTT_PREFIX}/{object_id}/config"


def object_id_for(specimen_id: str) -> str:
    """Stable across restarts, so Home Assistant keeps its entity history."""
    return f"specimen_{specimen_id.replace('-', '')}"


def discovery_config(
    *,
    component: str,
    object_id: str,
    name: str,
    state: str,
    sw_version: str,
    with_attributes: bool = False,
    **extra: Any,
) -> Message:
    """One retained discovery config, pointing at the availability topic.

    ``unique_id`` is the object id rather than a fresh value: it is what Home
    Assistant keys the entity registry on, and a ``unique_id`` that changes
    between restarts creates a second entity beside the first and leaves the
    history on the one nobody is looking at.
    """
    config: dict[str, Any] = {
        "name": name,
        "unique_id": f"{MQTT_PREFIX}_{object_id}",
        "object_id": f"{MQTT_PREFIX}_{object_id}",
        "state_topic": state,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": ONLINE,
        "payload_not_available": OFFLINE,
        "device": device_block(sw_version),
        **extra,
    }
    if with_attributes:
        config["json_attributes_topic"] = attributes_topic(state)
    return Message(discovery_topic(component, object_id), _dump(config))


def availability(online: bool) -> Message:
    return Message(AVAILABILITY_TOPIC, ONLINE if online else OFFLINE)


def last_will() -> Message:
    """What the broker publishes for us when we stop answering.

    Set at connect time. Without it a crashed worker leaves every entity
    frozen at its last value, which reads as "nothing has changed" — the same
    silent failure the design asks this parts of the project to design against, one layer
    out.
    """
    return Message(AVAILABILITY_TOPIC, OFFLINE)


# ------------------------------------------------------------------ entities


def rounds_messages(
    *,
    due: int,
    overdue: int,
    tasks: Sequence[Mapping[str, Any]] = (),
) -> list[Message]:
    """Tasks due today and overdue, with the task list as attributes."""
    due_topic = state_topic("rounds", "due")
    return [
        Message(due_topic, str(int(due))),
        Message(
            attributes_topic(due_topic),
            _dump({"tasks": [_task_attributes(task) for task in tasks]}),
        ),
        Message(state_topic("rounds", "overdue"), str(int(overdue))),
    ]


def frost_messages(
    *,
    active: bool,
    night: date | str | None = None,
    low_c: float | None = None,
    specimens: Sequence[str] = (),
    next_frost: date | str | None = None,
) -> list[Message]:
    """The frost binary sensor, its attributes, and the next-frost date.

    ``next_frost`` of ``None`` publishes the literal ``unknown``, which the
    contract specifies and which Home Assistant renders as an unknown date
    rather than as a blank. "We do not know when the next frost is" and "there
    is no frost coming" are different claims and only one of them is safe to
    make.
    """
    state = state_topic("frost", "state")
    return [
        Message(state, "ON" if active else "OFF"),
        Message(
            attributes_topic(state),
            _dump(
                {
                    "night": _as_iso(night),
                    "low_c": low_c,
                    "specimens": list(specimens),
                }
            ),
        ),
        Message(state_topic("frost", "next"), _as_iso(next_frost) or "unknown"),
    ]


def specimen_messages(
    specimen_id: str, *, water_due: bool, deficit_mm: float | None
) -> list[Message]:
    """One plant's two entities.

    A ``deficit_mm`` of ``None`` publishes ``unknown`` rather than ``0``. A
    zero deficit means "this plant was watered this morning"; an unknown one
    means the water balance could not answer, and that engine
    is the only thing deciding whether an outdoor plant gets water. Those two
    must not arrive on the same topic looking the same.
    """
    return [
        Message(
            state_topic("specimen", f"{specimen_id}/water_due"),
            "ON" if water_due else "OFF",
        ),
        Message(
            state_topic("specimen", f"{specimen_id}/deficit_mm"),
            "unknown" if deficit_mm is None else f"{float(deficit_mm):.1f}",
        ),
    ]


def discovery_messages(
    *, specimen_ids: Iterable[str] = (), sw_version: str = "1.0.0"
) -> list[Message]:
    """Every discovery config the contract lists, retained, in one call.

    Published on first sight of an entity. Re-publishing is harmless — Home
    Assistant treats a config for a known ``unique_id`` as an update — so this
    runs at startup rather than being tracked, which is one less piece of
    state to get wrong.
    """
    messages = [
        discovery_config(
            component="sensor",
            object_id="rounds_due",
            name="Tasks due today",
            state=state_topic("rounds", "due"),
            sw_version=sw_version,
            with_attributes=True,
            icon="mdi:sprout",
            state_class="measurement",
        ),
        discovery_config(
            component="sensor",
            object_id="rounds_overdue",
            name="Tasks overdue",
            state=state_topic("rounds", "overdue"),
            sw_version=sw_version,
            icon="mdi:sprout-outline",
            state_class="measurement",
        ),
        discovery_config(
            component="binary_sensor",
            object_id="frost_state",
            name="Frost alert",
            state=state_topic("frost", "state"),
            sw_version=sw_version,
            with_attributes=True,
            device_class="cold",
            payload_on="ON",
            payload_off="OFF",
        ),
        discovery_config(
            component="sensor",
            object_id="frost_next",
            name="Next frost",
            state=state_topic("frost", "next"),
            sw_version=sw_version,
            device_class="date",
        ),
    ]
    for specimen_id in specimen_ids:
        object_id = object_id_for(specimen_id)
        messages.append(
            discovery_config(
                component="binary_sensor",
                object_id=f"{object_id}_water_due",
                name="Water due",
                state=state_topic("specimen", f"{specimen_id}/water_due"),
                sw_version=sw_version,
                device_class="problem",
                payload_on="ON",
                payload_off="OFF",
            )
        )
        messages.append(
            discovery_config(
                component="sensor",
                object_id=f"{object_id}_deficit_mm",
                name="Soil moisture deficit",
                state=state_topic("specimen", f"{specimen_id}/deficit_mm"),
                sw_version=sw_version,
                unit_of_measurement="mm",
                state_class="measurement",
            )
        )
    return messages


# ------------------------------------------------------------------ commands


@dataclass(frozen=True, slots=True)
class Command:
    """One instruction arriving from Home Assistant."""

    kind: str
    task_id: str | None = None
    member_id: str | None = None


def parse_command(topic: str, payload: str | bytes) -> Command | None:
    """A command topic and its body, or ``None`` if it is neither of ours.

    A completion with no ``member_id`` is refused rather than attributed to
    nobody: the design makes the household a shared login with a member picker,
    so an unattributed completion is a log entry that cannot answer the one
    question anybody asks of it — who watered it?
    """
    if topic == COMMAND_REFRESH:
        return Command("refresh")
    match = _COMPLETE_PATTERN.match(topic)
    if not match:
        return None
    text = payload.decode() if isinstance(payload, bytes) else payload
    try:
        body = json.loads(text) if text.strip() else {}
    except ValueError:
        return None
    member_id = body.get("member_id") if isinstance(body, Mapping) else None
    if not member_id:
        return None
    return Command("complete", task_id=match.group(1), member_id=str(member_id))


# ----------------------------------------------------------------- publishing


@runtime_checkable
class Publisher(Protocol):
    """A broker. The only thing that would open a socket."""

    async def publish(self, message: Message) -> None: ...


@dataclass(slots=True)
class MemoryPublisher:
    """Records what would have gone out. What the tests assert against."""

    sent: list[Message] = field(default_factory=list)

    async def publish(self, message: Message) -> None:
        self.sent.append(message)

    def topics(self) -> list[str]:
        return [message.topic for message in self.sent]

    def payload_for(self, topic: str) -> str | None:
        """The last payload published on ``topic``, which is what a broker keeps."""
        for message in reversed(self.sent):
            if message.topic == topic:
                return message.payload
        return None


def guard(message: Message) -> Message:
    """Refuse a payload carrying anything credential-shaped.

    Both halves are checked: the JSON keys, because a token is usually
    *labelled*, and the raw text, because the interesting case is the one
    nobody labelled — a feed URL pasted into an attribute.

    The scanning itself is :mod:`workers.hub.credentials`, shared with the
    notification channel. A broker retains a message and a phone keeps
    a notification: one rule, one implementation, two places it has to hold.
    """
    assert_clean(message.topic, message.payload)
    return message


async def publish_all(
    publisher: Publisher, messages: Sequence[Message]
) -> list[Message]:
    """Guard every message, then publish it. Returns what went out."""
    sent: list[Message] = []
    for message in messages:
        await publisher.publish(guard(message))
        sent.append(message)
    return sent


class MqttNotConfigured(RuntimeError):
    """No broker named, or no client to reach it with. A setup step, not a fault."""


def _client_module() -> Any:
    """``aiomqtt``, imported, or ``None`` when it is not installed.

    The one place this module touches the library, so a test can hand
    :func:`connect_publisher` a fake with the same three names (``Client``,
    ``Will``, ``MqttError``) and nothing needs installing.
    """
    try:
        import aiomqtt  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return None
    return aiomqtt


def transport_available() -> bool:
    """Can this process reach a broker at all?

    True iff the client library is importable — the transport below is
    written, so importable is now the whole question. Asked rather than
    assumed, so the Ministry Office reports MQTT as *unconfigured* (a setup
    step) rather than *down* (a fault) on an image built without the client.
    """
    return _client_module() is not None


@dataclass(slots=True)
class ClientPublisher:
    """A :class:`Publisher` over a connected ``aiomqtt.Client``.

    Every message goes through :func:`guard` here as well as in
    :func:`publish_all`: this is the last line before the socket, and a
    caller that publishes directly must not be able to skip the check.
    """

    client: Any

    async def publish(self, message: Message) -> None:
        guard(message)
        await self.client.publish(
            message.topic, message.payload, qos=message.qos, retain=message.retain
        )


@asynccontextmanager
async def connect_publisher(
    settings: Any, *, client_module: Any = None
) -> AsyncIterator[ClientPublisher]:
    """Connect to the broker, announce ``online``, yield a publisher.

    Written against ``aiomqtt`` 2.x: ``Client(hostname, port, username=,
    password=, identifier=, will=)`` used as an async context manager, and
    ``Will(topic, payload, qos, retain)``. The last will is
    :func:`last_will` — ``offline``, retained — so a worker that dies
    mid-publish greys every entity out rather than freezing it.

    Nothing is announced ``offline`` on a clean exit. The publish job connects
    twice an hour and leaves; marking every entity unavailable between runs
    would make a healthy Ministry look dead for twenty-nine minutes in thirty.

    The password is read from its :class:`~pydantic.SecretStr` at the last
    moment and handed to the client only. It is never in a message, and a
    connection error is raised with it redacted out.
    """
    module = client_module if client_module is not None else _client_module()
    if module is None:
        raise MqttNotConfigured(
            "no MQTT client is installed in this image (aiomqtt), so nothing "
            "can be published to Home Assistant"
        )
    host = str(getattr(settings, "mqtt_host", "") or "")
    if not host:
        raise MqttNotConfigured("no MQTT broker is configured (MOH_MQTT_HOST)")
    secret = getattr(settings, "mqtt_password", None)
    password = secret.get_secret_value() if secret is not None else ""
    will = last_will()
    client = module.Client(
        hostname=host,
        port=int(getattr(settings, "mqtt_port", 1883)),
        username=(getattr(settings, "mqtt_username", "") or None),
        password=(password or None),
        identifier=str(getattr(settings, "mqtt_client_id", "") or MQTT_PREFIX),
        will=module.Will(will.topic, will.payload, qos=will.qos, retain=will.retain),
    )
    error_type = getattr(module, "MqttError", OSError)
    try:
        async with client:
            publisher = ClientPublisher(client)
            await publisher.publish(availability(True))
            yield publisher
    except error_type as exc:
        from .health import redact

        raise ConnectionError(
            redact(f"mqtt: could not publish to {host}: {exc}", (password,))
        ) from None


# ------------------------------------------------------------------- helpers


def _dump(payload: Any) -> str:
    """Compact and key-sorted, so a retained payload is byte-stable.

    A broker keeps the last message on a topic. If the same state serialised
    two different ways each publish, every restart would look like a change to
    anything watching.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _as_iso(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _task_attributes(task: Mapping[str, Any]) -> dict[str, Any]:
    """Only the fields a dashboard needs. An allow-list, deliberately.

    Copying a task through wholesale is how a field nobody thought about — a
    feed token, a note someone typed a password into — reaches a broker that
    retains it. Adding a field here is a decision; copying the dict is not.
    """
    return {
        "id": str(task.get("id", "")),
        "specimen": str(task.get("specimen") or task.get("nickname") or ""),
        "kind": str(task.get("kind") or ""),
        "due_on": _as_iso(task.get("due_on")),
    }
