"""The live fetcher's manners, without a live anything.

``HttpFetcher`` is the only part of the worker that would touch the network, so
it is tested with a stub client: what matters is who we say we are, how often we
knock, what we do when a service is rude, and what we conclude when it answers
with something that is not taxonomy.
"""

import pytest

from workers.botany.connectors.http import HttpFetcher, SourceUnavailable
from workers.botany.settings import BotanySettings


class StubResponse:
    def __init__(
        self, status_code=200, payload=None, text="", headers=None, url="https://x/y"
    ):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class StubClient:
    """Stands in for ``httpx.AsyncClient``; counts what it was asked for."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return (
            self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        )


def fetcher(*responses, **overrides):
    settings = BotanySettings(min_request_interval_s=0.0, **overrides)
    return HttpFetcher(settings, client=StubClient(*responses))


def test_we_say_who_we_are_and_how_to_reach_us():
    headers = HttpFetcher(BotanySettings()).client.headers
    assert "MinistryOfHerbology" in headers["User-Agent"]
    assert "+http" in headers["User-Agent"], "a contact URL is the price of a free API"


def test_a_payload_is_returned_with_the_url_it_came_from(run):
    f = fetcher(
        StubResponse(payload={"ok": True}, url="https://api.gbif.org/v1/species/match")
    )
    result = run(
        f.get_json(
            "gbif", "https://api.gbif.org/v1/species/match", {"name": "Monstera"}
        )
    )
    assert result.payload == {"ok": True}
    assert result.url == "https://api.gbif.org/v1/species/match"
    assert not result.from_cache


def test_the_same_question_twice_is_one_call(run):
    f = fetcher(StubResponse(payload={"ok": True}))
    args = ("gbif", "https://api.gbif.org/v1/species/match", {"name": "Monstera"})
    run(f.get_json(*args))
    second = run(f.get_json(*args))
    assert f.client.calls == [(args[1], args[2])]
    assert second.from_cache


def test_a_different_question_is_a_different_call(run):
    f = fetcher(StubResponse(payload={"ok": True}))
    url = "https://api.gbif.org/v1/species/match"
    run(f.get_json("gbif", url, {"name": "Monstera"}))
    run(f.get_json("gbif", url, {"name": "Hosta"}))
    assert len(f.client.calls) == 2


def test_a_rate_limit_is_waited_out_once(run):
    f = fetcher(
        StubResponse(status_code=429, headers={"Retry-After": "0"}),
        StubResponse(payload={"ok": True}),
    )
    assert run(f.get_json("gbif", "https://api.gbif.org/v1/species/match")).payload == {
        "ok": True
    }
    assert len(f.client.calls) == 2


def test_a_service_that_stays_down_is_unavailable_not_empty(run):
    f = fetcher(StubResponse(status_code=503))
    with pytest.raises(SourceUnavailable):
        run(f.get_json("powo", "https://powo.science.kew.org/api/2/search"))


def test_a_bot_challenge_is_unavailable_rather_than_no_such_plant(run):
    """POWO answers some clients with HTML and a 200. That is not a taxonomic opinion."""
    f = fetcher(StubResponse(status_code=200, text="<!DOCTYPE html>Just a moment..."))
    with pytest.raises(SourceUnavailable):
        run(f.get_json("powo", "https://powo.science.kew.org/api/2/search"))


def test_a_client_error_is_not_retried_forever(run):
    f = fetcher(StubResponse(status_code=404))
    with pytest.raises(SourceUnavailable):
        run(f.get_json("gbif", "https://api.gbif.org/v1/species/match"))
    assert len(f.client.calls) == 1
