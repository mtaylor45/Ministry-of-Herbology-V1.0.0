"""The MQTT publish-back, against the frozen contract — the hub.

``contracts/events/mqtt.md`` is the contract, so most of this file reads it
and asserts against it rather than restating it. A topic that drifts from the
contract is a Home Assistant entity that silently stops updating, and nothing
in either system would report that.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from workers.hub import mqtt
from workers.hub.mqtt import (
    AVAILABILITY_TOPIC,
    MemoryPublisher,
    SecretInPayload,
    availability,
    discovery_messages,
    frost_messages,
    guard,
    last_will,
    object_id_for,
    parse_command,
    publish_all,
    rounds_messages,
    specimen_messages,
)

CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "events" / "mqtt.md"
).read_text()

SPECIMEN = "01890040-0000-7000-8000-000000000001"


def contract_topics() -> set[str]:
    """Every ``herbology/...`` topic the contract's tables name."""
    return {
        topic.replace("<id>", SPECIMEN).replace("<task_id>", "task-1")
        for topic in re.findall(r"`(herbology/[^`]+)`", CONTRACT)
    }


def test_every_state_topic_the_contract_names_is_published():
    published = set()
    for message in [
        *rounds_messages(due=3, overdue=1),
        *frost_messages(active=True, night=date(2026, 10, 3), low_c=-2.0),
        *specimen_messages(SPECIMEN, water_due=True, deficit_mm=12.5),
        availability(True),
    ]:
        published.add(message.topic)

    for topic in contract_topics():
        if topic.startswith("herbology/cmd/"):
            continue  # subscribed, not published
        assert topic in published, topic


def test_attribute_topics_are_the_state_topic_plus_attributes():
    due = rounds_messages(due=2, overdue=0, tasks=[{"id": "t-1", "kind": "water"}])
    topics = [message.topic for message in due]
    assert "herbology/rounds/due" in topics
    assert "herbology/rounds/due/attributes" in topics


def test_everything_is_retained_so_home_assistant_restores_after_a_restart():
    """The alternative is a wall of `unknown` until the next publish, on a
    dashboard somebody put on their kitchen wall."""
    messages = [
        *discovery_messages(specimen_ids=[SPECIMEN]),
        *rounds_messages(due=0, overdue=0),
        *frost_messages(active=False),
        *specimen_messages(SPECIMEN, water_due=False, deficit_mm=0.0),
        availability(True),
    ]
    assert all(message.retain for message in messages)


def test_object_ids_are_stable_across_restarts():
    """An object id derived from anything that moves orphans an entity's
    history the first time it changes, and HA keeps the orphan forever."""
    assert object_id_for(SPECIMEN) == "specimen_" + SPECIMEN.replace("-", "")
    assert object_id_for(SPECIMEN) == object_id_for(SPECIMEN)


def test_discovery_goes_to_the_topic_layout_the_contract_fixes():
    configs = discovery_messages(specimen_ids=[SPECIMEN])
    topics = [message.topic for message in configs]
    assert "homeassistant/sensor/herbology/rounds_due/config" in topics
    assert (
        f"homeassistant/binary_sensor/herbology/{object_id_for(SPECIMEN)}"
        "_water_due/config" in topics
    )


def test_every_discovery_config_carries_the_shared_device_and_availability():
    for message in discovery_messages(specimen_ids=[SPECIMEN], sw_version="1.2.3"):
        config = message.as_json()
        assert config["device"]["identifiers"] == ["ministry_of_herbology"]
        assert config["device"]["sw_version"] == "1.2.3"
        assert config["availability_topic"] == AVAILABILITY_TOPIC
        assert config["unique_id"].startswith("herbology_")


def test_the_device_block_matches_the_contract_word_for_word():
    quoted = re.search(r"```json\n(.*?)\n```", CONTRACT, re.DOTALL)
    assert quoted is not None
    block = json.loads(quoted.group(1).replace('"<app version>"', '"1.0.0"'))
    assert mqtt.device_block("1.0.0") == block


def test_the_last_will_is_offline_on_the_availability_topic():
    """Without it a crashed worker leaves every entity frozen at its last
    value, which reads as "nothing has changed" — the silent failure, one
    layer out."""
    assert last_will().topic == AVAILABILITY_TOPIC
    assert last_will().payload == "offline"
    assert availability(True).payload == "online"


def test_an_unknown_deficit_is_published_as_unknown_not_as_zero():
    """A zero deficit means "watered this morning"; an unknown one means the
    water balance could not answer. Under the design that engine is the only
    thing deciding whether an outdoor plant gets water."""
    _, deficit = specimen_messages(SPECIMEN, water_due=False, deficit_mm=None)
    assert deficit.payload == "unknown"

    _, zero = specimen_messages(SPECIMEN, water_due=False, deficit_mm=0.0)
    assert zero.payload == "0.0"


def test_an_unknown_next_frost_is_published_as_unknown():
    """ "We do not know when the next frost is" and "there is no frost coming"
    are different claims, and only one is safe to make."""
    messages = {m.topic: m.payload for m in frost_messages(active=False)}
    assert messages["herbology/frost/next"] == "unknown"

    dated = {
        m.topic: m.payload
        for m in frost_messages(active=True, next_frost=date(2026, 10, 3))
    }
    assert dated["herbology/frost/next"] == "2026-10-03"


def test_a_retained_payload_is_byte_stable_for_the_same_state():
    """A broker keeps the last message on a topic. If one state serialised two
    ways, every restart would look like a change to anything watching."""
    one = frost_messages(active=True, night=date(2026, 10, 3), specimens=["a", "b"])
    other = frost_messages(active=True, night=date(2026, 10, 3), specimens=["a", "b"])
    assert [m.payload for m in one] == [m.payload for m in other]


def test_a_feed_token_is_refused_rather_than_published(run):
    """The contract's "nothing secret goes in a payload", as a check.

    The scheduler's ICS subscriptions are addressed by a token in a URL path, and a
    calendar link is exactly the sort of convenient thing that ends up in an
    attributes blob. A broker retains it until something replaces it, so
    publishing one once is publishing it until somebody notices.
    """
    leak = mqtt.Message(
        "herbology/rounds/due/attributes",
        json.dumps({"feed": "https://moh.example/feeds/6f2c1ab9d4e7f08312bc55aa"}),
    )
    with pytest.raises(SecretInPayload):
        guard(leak)


def test_a_labelled_credential_is_refused_by_its_key():
    with pytest.raises(SecretInPayload, match="'api_key'"):
        guard(mqtt.Message("herbology/rounds/due/attributes", '{"api_key": "abc"}'))


def test_a_credential_nested_in_an_attribute_list_is_still_caught():
    payload = json.dumps({"tasks": [{"id": "t-1", "token": "secretvalue"}]})
    with pytest.raises(SecretInPayload):
        guard(mqtt.Message("herbology/rounds/due/attributes", payload))


def test_the_task_attributes_are_an_allow_list_not_a_copy():
    """Copying a task through wholesale is how a field nobody thought about
    reaches a broker that retains it."""
    messages = rounds_messages(
        due=1,
        overdue=0,
        tasks=[
            {
                "id": "t-1",
                "kind": "water",
                "specimen": "Gilderoy",
                "due_on": date(2026, 6, 15),
                "feed_token": "6f2c1ab9d4e7f08312bc55aa",
                "note": "the spare key is under the mat",
            }
        ],
    )
    attributes = next(m for m in messages if m.topic.endswith("/attributes"))
    task = attributes.as_json()["tasks"][0]
    assert set(task) == {"id", "specimen", "kind", "due_on"}
    guard(attributes)


def test_publishing_guards_every_message(run):
    publisher = MemoryPublisher()
    run(
        publish_all(publisher, [availability(True), *rounds_messages(due=1, overdue=0)])
    )
    assert publisher.topics()[0] == AVAILABILITY_TOPIC
    assert publisher.payload_for("herbology/rounds/due") == "1"


def test_a_completion_command_is_parsed_with_its_member():
    command = parse_command(
        "herbology/cmd/task/task-1/complete", '{"member_id": "member-1"}'
    )
    assert command is not None
    assert (command.kind, command.task_id, command.member_id) == (
        "complete",
        "task-1",
        "member-1",
    )


def test_an_unattributed_completion_is_refused():
    """the design makes the household a shared login with a member picker, so a
    completion with no member cannot answer the one question anybody asks of
    it — who watered it?"""
    assert parse_command("herbology/cmd/task/task-1/complete", "{}") is None
    assert parse_command("herbology/cmd/task/task-1/complete", "") is None


def test_a_refresh_command_takes_an_empty_payload():
    command = parse_command("herbology/cmd/rounds/refresh", "")
    assert command is not None and command.kind == "refresh"


def test_a_topic_that_is_not_ours_is_ignored():
    assert parse_command("homeassistant/status", "online") is None
    assert parse_command("herbology/rounds/due", "3") is None


def test_malformed_json_on_a_command_topic_does_not_raise():
    assert parse_command("herbology/cmd/task/t-1/complete", "{not json") is None


def test_the_transport_is_available_exactly_when_the_client_is_installed():
    """The earlier tripwire, made conditional as agreed on #56.

    The transport is written now, so "available" means "``aiomqtt`` is
    importable" and nothing else. This holds before B adds the dependency
    (False, and the Office says *unconfigured*) and after (True), so neither
    PR turns the other red.
    """
    from importlib.util import find_spec

    assert mqtt.transport_available() is (find_spec("aiomqtt") is not None)
