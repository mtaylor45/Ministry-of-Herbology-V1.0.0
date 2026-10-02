"""The one socket in this worker — the hub.

Every request the hub makes carries a long-lived Home Assistant access token,
so this file is as much about what does *not* leave the process as about what
does. The tests run against ``httpx.MockTransport``, which the no-network
guard deliberately leaves usable: blocking the real transport and the socket
layer underneath it is stricter than patching the client, and it still lets a
test serve a canned response so the retry and error paths can be exercised at
all.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from workers.hub.settings import HubSettings
from workers.hub.sources.base import HubUnavailable
from workers.hub.sources.http import HomeAssistantFetcher

TOKEN = "eyJhbGciOiJIUzI1NiJ9.aVeryLongLivedAccessToken.signaturegoeshere"


def settings_with(**kwargs) -> HubSettings:
    return HubSettings(
        mock_mode=False,
        ha_base_url="http://hub.invalid:8123",
        ha_token=SecretStr(TOKEN),
        min_request_interval_s=0.0,
        **kwargs,
    )


def fetcher_serving(handler, **kwargs) -> HomeAssistantFetcher:
    settings = settings_with(**kwargs)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {settings.ha_token.get_secret_value()}"},
    )
    return HomeAssistantFetcher(settings, client=client)


def test_the_token_goes_in_one_header_and_nowhere_else(run):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "API running."})

    fetcher = fetcher_serving(handler)
    result = run(fetcher.get_json("home_assistant", "/"))

    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(seen[0].url)
    assert TOKEN not in str(result.url)


def test_an_unset_token_is_absent_rather_than_sent_empty():
    """An empty Authorization header makes HA answer 400, which reads as a
    malformed request when the real problem is an unconfigured deployment."""
    bare = HomeAssistantFetcher(HubSettings(mock_mode=False, ha_base_url="http://x"))
    assert "Authorization" not in bare._headers()


def test_a_refused_token_names_the_setting_rather_than_the_status_code(run):
    fetcher = fetcher_serving(lambda request: httpx.Response(401, json={}))
    with pytest.raises(HubUnavailable) as raised:
        run(fetcher.get_json("home_assistant", "/states"))
    assert "MOH_HA_TOKEN" in str(raised.value)
    assert TOKEN not in str(raised.value)


def test_a_refused_token_is_not_retried(run):
    """A rate limit is a bad minute; a refused token is a verdict, and
    re-presenting it only helps a brute-force detector decide we are one."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(403, json={})

    with pytest.raises(HubUnavailable):
        run(fetcher_serving(handler).get_json("home_assistant", "/states"))
    assert len(attempts) == 1


def test_a_restarting_hub_is_retried_once(run):
    answers = [httpx.Response(503, json={}), httpx.Response(200, json=[])]

    def handler(request: httpx.Request) -> httpx.Response:
        return answers.pop(0)

    result = run(fetcher_serving(handler).get_json("home_assistant", "/states"))
    assert result.payload == []
    assert answers == []


def test_a_missing_entity_says_so_in_words(run):
    fetcher = fetcher_serving(lambda request: httpx.Response(404, json={}))
    with pytest.raises(HubUnavailable, match="renamed or removed"):
        run(fetcher.get_json("home_assistant", "/states/sensor.gone"))


def test_an_error_body_is_quoted_but_the_url_never_is(run):
    """A misconfigured deployment can put credentials in a base URL, and this
    string is bound for a column the Ministry Office renders."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "template error"})

    with pytest.raises(HubUnavailable) as raised:
        run(fetcher_serving(handler).get_json("home_assistant", "/states"))
    assert "template error" in str(raised.value)
    assert "hub.invalid" not in str(raised.value)


def test_html_where_json_was_expected_is_a_clear_failure(run):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})

    with pytest.raises(HubUnavailable, match="expected JSON"):
        run(fetcher_serving(handler).get_json("home_assistant", "/states"))


def test_a_network_failure_is_reported_not_swallowed(run):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(HubUnavailable, match="no route to host"):
        run(fetcher_serving(handler).get_json("home_assistant", "/states"))


def test_an_unconfigured_deployment_says_which_variable_is_missing(run):
    fetcher = HomeAssistantFetcher(HubSettings(mock_mode=False, ha_base_url=""))
    with pytest.raises(HubUnavailable, match="MOH_HA_BASE_URL"):
        run(fetcher.get_json("home_assistant", "/states"))


def test_urls_are_built_without_doubled_slashes():
    fetcher = HomeAssistantFetcher(settings_with())
    assert fetcher.url_for("/states") == "http://hub.invalid:8123/api/states"
    assert fetcher.url_for("states") == "http://hub.invalid:8123/api/states"
    assert fetcher.url_for("/") == "http://hub.invalid:8123/api"


def test_the_websocket_url_is_derived_rather_than_configured_twice():
    """Two base URLs for one Home Assistant is two things to get wrong."""
    assert settings_with().ha_websocket_url == "ws://hub.invalid:8123/api/websocket"
    secure = HubSettings(ha_base_url="https://hub.example/")
    assert secure.ha_websocket_url == "wss://hub.example/api/websocket"


def test_is_configured_needs_both_a_url_and_a_token():
    assert not HubSettings(ha_base_url="http://x").is_configured
    assert not HubSettings(ha_token=SecretStr(TOKEN)).is_configured
    assert settings_with().is_configured


def test_the_token_does_not_survive_a_repr():
    """A traceback, a log line and a debugger all reach for this."""
    assert TOKEN not in repr(settings_with())
    assert TOKEN not in str(settings_with().ha_token)
