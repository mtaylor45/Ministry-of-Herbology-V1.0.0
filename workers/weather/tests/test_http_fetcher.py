"""The live fetcher's manners, against a transport that never leaves the process.

``httpx.MockTransport`` answers without a socket, so the retry, the headers and
the 200-with-an-error-body case are all exercisable offline. The autouse
``no_network`` fixture blocks the real transport underneath, so a mistake here
fails rather than dialling out.
"""

import httpx
import pytest

from workers.weather.settings import WeatherSettings
from workers.weather.sources.base import SourceUnavailable
from workers.weather.sources.http import HttpFetcher

URL = "https://api.open-meteo.com/v1/forecast"


def fetcher_for(handler, **overrides) -> HttpFetcher:
    settings = WeatherSettings(min_request_interval_s=0.0, **overrides)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": settings.user_agent},
    )
    return HttpFetcher(settings, client=client)


def test_a_good_response_comes_back_parsed(run):
    fetcher = fetcher_for(lambda request: httpx.Response(200, json={"daily": {}}))
    result = run(fetcher.get_json("open_meteo", URL))
    assert result.payload == {"daily": {}}
    assert not result.is_mock
    assert result.retrieved_at.tzinfo is not None


def test_every_request_names_us_and_a_way_to_complain(run):
    """NWS answers 403 without a contact in the User-Agent. Open-Meteo deserves one."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json={})

    run(fetcher_for(handler).get_json("nws", "https://api.weather.gov/alerts/active"))
    assert "MinistryOfHerbology" in seen[0]
    assert "github.com/mtaylor45" in seen[0]


def test_a_rate_limit_is_retried_once_then_reported(run):
    """A bad minute is not a verdict; a bad afternoon is."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, json={"error": True, "reason": "Daily API limit"})

    with pytest.raises(SourceUnavailable, match="429"):
        run(fetcher_for(handler).get_json("open_meteo", URL))
    assert len(attempts) == 2, "one retry, not a storm of them"


def test_a_retry_that_succeeds_is_not_an_error(run):
    responses = [
        httpx.Response(503, text="try later"),
        httpx.Response(200, json={"ok": True}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    result = run(fetcher_for(handler).get_json("nws", URL))
    assert result.payload == {"ok": True}


def test_a_four_hundred_is_not_retried(run):
    """A malformed request will be just as malformed the second time."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400, json={"error": True, "reason": "Invalid value"})

    with pytest.raises(SourceUnavailable, match="Invalid value"):
        run(fetcher_for(handler).get_json("open_meteo", URL))
    assert len(attempts) == 1


def test_an_error_body_behind_a_200_is_still_an_error(run):
    """Open-Meteo answers some malformed requests 200 with ``{"error": true}``.

    A status code alone is not consent, and a payload with no data in it must
    not reach a parser that would read it as "the weather is nothing".
    """
    fetcher = fetcher_for(
        lambda request: httpx.Response(200, json={"error": True, "reason": "nope"})
    )
    with pytest.raises(SourceUnavailable, match="nope"):
        run(fetcher.get_json("open_meteo", URL))


def test_html_behind_a_200_is_treated_as_unreachable(run):
    """A challenge page is not a weather forecast."""
    fetcher = fetcher_for(
        lambda request: httpx.Response(200, text="<html>are you a robot</html>")
    )
    with pytest.raises(SourceUnavailable, match="expected JSON"):
        run(fetcher.get_json("nws", URL))


def test_a_transport_failure_is_reported_as_unreachable(run):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(SourceUnavailable, match="timed out"):
        run(fetcher_for(handler).get_json("open_meteo", URL))


def test_the_failure_message_carries_the_service_s_own_reason(run):
    """ "HTTP 429" is not a bug report. "Daily API request limit exceeded" is."""
    fetcher = fetcher_for(
        lambda request: httpx.Response(
            403, json={"detail": "User-Agent header is required"}
        )
    )
    with pytest.raises(SourceUnavailable, match="User-Agent header is required"):
        run(fetcher.get_json("nws", URL))


def test_the_real_recorded_error_bodies_surface_their_reasons(run, payload):
    """The two bodies Open-Meteo actually returned to this project."""
    for name, expected in (
        ("open_meteo/error__rate-limited.json", "limit exceeded"),
        ("open_meteo/error__unknown-variable.json", "Invalid value"),
    ):
        body = payload(name)
        fetcher = fetcher_for(lambda request, body=body: httpx.Response(400, json=body))
        with pytest.raises(SourceUnavailable, match=expected):
            run(fetcher.get_json("open_meteo", URL))


def test_the_fetcher_closes_only_the_client_it_owns(run):
    """Handing a client in means the caller's lifecycle wins."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    fetcher = HttpFetcher(WeatherSettings(), client=client)
    run(fetcher.aclose())
    assert not client.is_closed
