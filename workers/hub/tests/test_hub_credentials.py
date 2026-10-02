"""The one credential check, for both senders. Owner: The hub.

an earlier release tested this inside ``test_hub_mqtt.py`` because MQTT was the only thing F
published. an earlier release gave it a second caller, so it gets its own file — and a few
cases MQTT never had, because a notification body is assembled from text other
people wrote: a task's ``detail``, an integration's ``last_error``, a note
somebody typed.
"""

from __future__ import annotations

import json

import pytest

from workers.hub.credentials import (
    FORBIDDEN_KEYS,
    SecretInPayload,
    assert_clean,
    credential_reason,
    keys_of,
)


@pytest.mark.parametrize("key", sorted(FORBIDDEN_KEYS))
def test_every_forbidden_key_is_caught_at_the_top_level(key):
    assert credential_reason(json.dumps({key: "abcdefghijkl"})) is not None


def test_a_forbidden_key_is_caught_however_deeply_it_is_buried():
    """Copying a dict through wholesale is how a field nobody thought about
    reaches a payload. The check does not care which level it is on."""
    payload = {"tasks": [{"specimen": {"debug": {"api_key": "abcdefghijkl"}}}]}
    assert credential_reason(json.dumps(payload)) is not None


def test_the_tokenised_calendar_feed_url_is_the_case_this_exists_for():
    """The scheduler escalated that this credential was reaching two
    access logs. A notification body is a third door onto the same mistake."""
    reason = credential_reason(
        "Subscribe: https://moh.example/api/v1/calendar/9f3a2b7c1d4e5f60a1b2.ics"
    )
    assert reason == "a tokenised calendar feed URL"


def test_a_home_assistant_long_lived_token_is_a_jwt_and_is_caught():
    reason = credential_reason(
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OD.dBjftJeZ4CVP"
    )
    assert reason is not None and "web token" in reason


def test_credentials_in_a_url_are_caught():
    assert (
        credential_reason("dialled https://admin:hunter2@hub.local:8123/api")
        is not None
    )


@pytest.mark.parametrize(
    "text",
    [
        "• Water Gilderoy — 450 ml",
        "Frost tonight: 3 plants at risk",
        "Home Assistant is not answering — connection refused",
        "Bring indoors The Lemon Tree.",
        "Freeze Warning in effect from 2 AM to 9 AM",
        "Nothing measures the soil; waterings are worked out from the weather.",
    ],
)
def test_the_real_notifications_pass_the_guard(text):
    """A guard that refuses real messages is a guard somebody removes.

    Every string here is one this package actually sends.
    """
    assert credential_reason(text) is None


def test_a_plain_text_body_that_is_not_json_is_still_scanned():
    """A notification body is prose, not JSON. Failing to parse it must not be
    read as "nothing to check"."""
    with pytest.raises(SecretInPayload):
        assert_clean("notify.x", "the hub said Bearer: sk-abcdefghijklmnop")


def test_the_refusal_names_the_field_without_repeating_the_secret():
    """The traceback must not become the second place it is written down."""
    with pytest.raises(SecretInPayload) as caught:
        assert_clean("notify.x", json.dumps({"access_token": "sk-abcdefghijkl"}))
    message = str(caught.value)
    assert "access_token" in message
    assert "sk-abcdefghijkl" not in message


def test_a_clean_payload_is_returned_unchanged():
    assert assert_clean("notify.x", "Water Gilderoy") == "Water Gilderoy"


def test_keys_of_walks_lists_and_mappings_alike():
    assert set(keys_of({"a": [{"b": 1}], "c": {"d": 2}})) == {"a", "b", "c", "d"}


def test_a_decoded_body_is_used_when_the_caller_already_has_one():
    """The channel renders a dict before serialising it, and passing it in
    saves a parse — the answer must not change."""
    body = {"data": {"password": "abcdefghijkl"}}
    assert credential_reason("<not json>", body) is not None
