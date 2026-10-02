"""The transport, and the rule that guards it. Owner: The hub.

the design makes Home Assistant the only route out, so this file is about one
HTTP POST. The interesting tests are not about the POST.
"""

from __future__ import annotations

import json

import pytest

from workers.hub.credentials import SecretInPayload, assert_clean, credential_reason
from workers.hub.notify.channels import (
    HomeAssistantChannel,
    MemoryChannel,
    build_channel,
    render,
    split_service,
)
from workers.hub.notify.model import Certainty, Notification
from workers.hub.settings import HubSettings


def note(**overrides):
    base = {
        "kind": "rounds",
        "title": "Today's rounds: 1 task",
        "body": "• Water Gilderoy — 450 ml",
        "dedupe_key": "rounds:m:2026-10-23",
        "themed_title": "The morning rounds await",
        "deep_link": "/rounds",
        "certainty": Certainty(confidence="high", stated=True),
    }
    base.update(overrides)
    return Notification(**base)


# ------------------------------------------- nothing secret leaves this worker


def test_a_feed_token_in_a_task_detail_is_refused_rather_than_sent(recipient):
    """The exact failure the scheduler escalated arriving by a new door.

    A calendar URL is a convenient thing to put in a notification and it
    carries a bearer token in its path. Refused at the boundary, because a
    notification sits on a lock screen until somebody swipes it.
    """
    leaky = note(
        body="Subscribe: https://moh.example/api/v1/calendar/9f3a2b7c1d4e5f60a1b2.ics"
    )
    with pytest.raises(SecretInPayload) as caught:
        render(leaky, recipient)
    assert "calendar feed URL" in str(caught.value)


def test_a_labelled_token_anywhere_in_the_payload_is_refused(recipient):
    leaky = note(data={"debug": {"access_token": "abcdefghijkl"}})
    with pytest.raises(SecretInPayload):
        render(leaky, recipient)


def test_a_home_assistant_long_lived_token_is_refused(recipient):
    """It is a JWT, and this is the one credential the worker actually holds."""
    leaky = note(
        body="hub said: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVP"
    )
    with pytest.raises(SecretInPayload):
        render(leaky, recipient)


def test_the_ordinary_message_passes_the_guard_unchanged(recipient):
    """A guard that refuses real notifications is a guard somebody removes."""
    body = render(note(), recipient)
    assert body["message"] == "• Water Gilderoy — 450 ml"


def test_the_same_check_guards_mqtt_and_notifications():
    """One rule, one implementation. the earlier guard, lifted out rather than copied.

    A second copy is a second thing to forget when a new pattern is added.
    """
    from workers.hub import mqtt

    assert mqtt.SecretInPayload is SecretInPayload
    with pytest.raises(SecretInPayload):
        mqtt.guard(mqtt.Message("herbology/x", json.dumps({"api_key": "abcdefgh"})))
    assert credential_reason("plain text about a plant") is None


def test_the_guard_names_what_it_found_without_quoting_the_payload_back():
    """The traceback must not become the second place the credential is written."""
    with pytest.raises(SecretInPayload) as caught:
        assert_clean("notify.x", "Bearer: sk-abcdefghijklmnop")
    assert "sk-abcdefghijklmnop" not in str(caught.value)


# ------------------------------------------------------------- the service call


def test_the_service_call_is_addressed_the_way_home_assistant_expects(
    run, recipient, settings
):
    from workers.hub.mocks.fetcher import RecordedFetcher

    fetcher = RecordedFetcher(settings)
    delivery = run(HomeAssistantChannel(fetcher, settings).send(note(), recipient))
    assert delivery.ok is True
    kind, path, body = fetcher.posted[0]
    assert kind == "home_assistant"
    assert path == "services/notify/mobile_app_test_phone"
    assert body["title"] == "Today's rounds: 1 task"
    assert "message" in body


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("notify.mobile_app_x", ("notify", "mobile_app_x")),
        ("mobile_app_x", ("notify", "mobile_app_x")),
        ("script.tell_everyone", ("script", "tell_everyone")),
    ],
)
def test_a_household_may_route_notifications_however_it_likes(configured, expected):
    """``script.tell_everyone`` is a perfectly good route. Refusing it would be
    this app deciding how somebody's hub is organised."""
    assert split_service(configured) == expected


def test_a_hub_that_is_down_is_a_failed_delivery_not_an_exception(
    run, recipient, settings
):
    """One unreachable phone must not stop the other two members being told."""
    from workers.hub.mocks.fetcher import UnavailableFetcher

    delivery = run(
        HomeAssistantChannel(UnavailableFetcher(), settings).send(note(), recipient)
    )
    assert delivery.ok is False
    assert "unreachable" in delivery.reason


def test_a_delivery_failure_is_redacted_before_it_is_reported(run, recipient):
    """It lands on ``integration.last_error``, which the Ministry Office renders."""
    from pydantic import SecretStr

    from workers.hub.mocks.fetcher import UnavailableFetcher

    settings = HubSettings(mock_mode=True, ha_token=SecretStr("supersecrettoken"))
    fetcher = UnavailableFetcher("refused: token=supersecrettoken")
    delivery = run(HomeAssistantChannel(fetcher, settings).send(note(), recipient))
    assert "supersecrettoken" not in delivery.reason


# ------------------------------------------------------------ the urgent hints


def test_a_frost_notification_is_marked_time_sensitive_on_both_platforms(recipient):
    """iOS holds a notification for the next summary; Android's doze mode sits
    on it. A freeze warning held until 9 AM is a freeze warning that did not
    happen, so both hints go on the same message."""
    data = render(note(kind="frost", urgent=True), recipient)["data"]
    assert data["push"] == {"interruption-level": "time-sensitive"}
    assert data["priority"] == "high"
    assert data["ttl"] == 0


def test_an_ordinary_notification_carries_no_urgency_hints(recipient):
    """If everything is urgent, nothing is."""
    data = render(note(), recipient)["data"]
    assert "push" not in data
    assert "priority" not in data


def test_the_certainty_travels_with_the_message_for_a_client_that_can_use_it(recipient):
    data = render(
        note(certainty=Certainty(confidence="low", degraded=True)), recipient
    )["data"]
    assert data["confidence"] == "low"
    assert data["degraded"] is True


def test_the_deep_link_is_a_path_and_never_a_url(recipient):
    """A URL needs a host; a host needs the public base URL; and a public base
    URL is one refactor away from carrying a feed token into a payload."""
    data = render(note(), recipient)["data"]
    assert data["url"] == "/rounds"
    assert "://" not in data["url"]


# ------------------------------------------------------------- which channel


def test_a_deployment_with_no_home_assistant_records_rather_than_dials():
    """The same fallback :mod:`workers.hub.factory` makes for reads, and it
    leaves the integration reported as *unconfigured* rather than as ok."""
    assert isinstance(build_channel(HubSettings(mock_mode=True)), MemoryChannel)
    assert isinstance(build_channel(HubSettings(mock_mode=False)), MemoryChannel)


def test_a_configured_deployment_dials_home_assistant():
    from pydantic import SecretStr

    configured = HubSettings(
        mock_mode=False, ha_base_url="http://hub.local:8123", ha_token=SecretStr("t")
    )
    assert isinstance(build_channel(configured), HomeAssistantChannel)


# --------------------------------- the internal API call carries no credential


def test_the_ministry_api_client_sends_no_authorization_header():
    """``MOH_HA_TOKEN`` belongs to Home Assistant and to nothing else.

    A shared client is one refactor away from presenting a hub token to an
    unrelated host, which is why this is a separate client.
    """
    from pydantic import SecretStr

    from workers.hub.notify.state import ApiReader

    settings = HubSettings(
        mock_mode=False,
        ha_base_url="http://hub.local:8123",
        ha_token=SecretStr("a-long-lived-hub-token"),
    )
    client = ApiReader(settings).build_client()
    headers = {key.lower() for key in client.headers}
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert "a-long-lived-hub-token" not in str(dict(client.headers))


def test_the_api_reader_builds_the_url_from_the_contracts_server_block():
    from workers.hub.notify.state import API_PREFIX, FROST_PATH, ROUNDS_PATH, ApiReader

    assert API_PREFIX == "/api/v1"
    assert ROUNDS_PATH == "/tending/rounds"
    assert FROST_PATH == "/almanac/frost"
    reader = ApiReader(HubSettings(api_url="http://api:8000/"))
    assert reader.url_for(ROUNDS_PATH) == "http://api:8000/api/v1/tending/rounds"


# ------------------------------------------------------------ the memory channel


def test_the_memory_channel_records_the_words_on_the_wire(run, recipient):
    channel = MemoryChannel()
    run(channel.send(note(), recipient))
    assert channel.titles() == ["Today's rounds: 1 task"]
    assert channel.messages() == ["• Water Gilderoy — 450 ml"]


def test_the_memory_channel_runs_the_same_guard_as_the_real_one(run, recipient):
    """A test channel that skipped the check would make the check untested."""
    channel = MemoryChannel()
    leaky = note(body="token: abcdefghijklmnop")
    with pytest.raises(SecretInPayload):
        run(channel.send(leaky, recipient))
