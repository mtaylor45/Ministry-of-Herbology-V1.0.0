"""The Home Assistant adapter, against the synthesised installation.

The hub. Nothing here opens a socket; ``conftest.no_network`` makes sure
of it, and it matters more here than it does for weather because every request
this worker would make carries a long-lived access token.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from workers.hub.mapping import SensorSource
from workers.hub.mocks.fetcher import RecordedFetcher, UnavailableFetcher
from workers.hub.sources.base import HubUnavailable
from workers.hub.sources.home_assistant import HomeAssistantSource


def test_the_mock_world_has_one_climate_source_per_indoor_room(sensor_sources):
    names = {row.name for row in sensor_sources}
    assert names == {"Greenhouse Window", "Study", "Kitchen Sill"}
    assert all(row.location_id for row in sensor_sources)


def test_no_outdoor_location_gets_a_thermostat(sensor_sources):
    """An outdoor bed's temperature is the weather engine's weather ingest.

    Inventing an HA sensor for one would put two different answers to the same
    question into one database.
    """
    assert not any(
        row.name in {"South Border", "Covered Porch"} for row in sensor_sources
    )


def test_the_mock_world_invents_no_soil_probe(sensor_sources):
    """the design, asserted rather than promised.

    The adapter's soil path is complete — ``test_hub_entities`` and
    ``test_hub_mapping`` exercise it — and nothing here claims a probe exists.
    """
    for row in sensor_sources:
        assert not row.is_soil_probe
        assert row.specimen_id is None


def test_a_poll_reads_every_mapped_entity(run, source, sensor_sources, now):
    result = run(source.poll(sensor_sources, now=now))
    assert result.ok
    assert len(result.readings) == 6
    assert {reading.metric for reading in result.readings} == {
        "temperature_c",
        "humidity_pct",
    }
    assert all(reading.time == now for reading in result.readings)


def test_one_poll_is_one_request_however_many_sources(
    run, source, fetcher, sensor_sources, now
):
    """``GET /api/states`` returns the whole installation, so ask once.

    A per-entity fetch names a missing entity no more precisely — absence
    from the collection names it just as well — and costs a round trip per
    sensor on a household that has mapped twenty.
    """
    run(source.poll(sensor_sources, now=now))
    assert [path for _, path, _ in fetcher.calls] == ["/states"]


def test_every_reading_carries_the_room_it_belongs_to(run, source, sensor_sources, now):
    result = run(source.poll(sensor_sources, now=now))
    by_location = {reading.location_id for reading in result.readings}
    assert by_location == {row.location_id for row in sensor_sources}
    assert all(reading.specimen_id is None for reading in result.readings)


def test_a_chatty_home_assistant_is_ignored_rather_than_stored(
    run, source, sensor_sources, now
):
    """A real hub carries hundreds of entities; the adapter's first job is to
    ignore all of them."""
    result = run(source.poll(sensor_sources, now=now))
    entity_ids = {reading.entity_id for reading in result.readings}
    assert not any(
        entity.startswith(("light.", "switch.", "weather.")) for entity in entity_ids
    )


def test_an_entity_home_assistant_does_not_have_is_named(
    run, source, sensor_sources, now
):
    typo = SensorSource(
        id="typo",
        name="Study",
        external_ids={"temperature_c": "sensor.sutdy_temperature"},
        location_id="location-1",
    )
    result = run(source.poll([*sensor_sources, typo], now=now))
    reasons = {item.reason for item in result.skipped}
    assert "entity_not_found" in reasons
    assert any("sutdy" in item.detail for item in result.skipped)
    # The other five still land: one bad row does not cost the rest.
    assert len(result.readings) == 6


def test_a_hub_that_is_down_is_reported_rather_than_raised(
    run, settings, sensor_sources, now
):
    """A hub that is off is a state to put on a screen, not an exception for
    Arq to log and forget."""
    adapter = HomeAssistantSource(UnavailableFetcher(), settings)
    result = run(adapter.poll(sensor_sources, now=now))
    assert not result.ok
    assert result.readings == ()
    assert "unreachable" in (result.error or "")


def test_a_hub_that_is_down_does_not_look_like_a_hub_with_nothing_to_say(
    run, settings, source, sensor_sources, now
):
    down = HomeAssistantSource(UnavailableFetcher(), settings)
    empty = run(source.poll([], now=now))
    broken = run(down.poll(sensor_sources, now=now))
    assert empty.ok and empty.readings == ()
    assert not broken.ok and broken.readings == ()
    # Same emptiness, opposite meaning — which is the whole point of `error`.
    assert empty.error is None and broken.error is not None


def test_the_probe_is_the_cheap_way_to_ask_whether_the_hub_is_there(run, source):
    assert "running" in run(source.probe()).lower()


def test_a_proxy_answering_200_is_not_counted_as_health(run, settings):
    """An HTTP 200 from something that is not Home Assistant is the failure a
    naive health check cannot see."""

    class ProxyFetcher(RecordedFetcher):
        async def get_json(self, kind, path, params=None):
            result = await super().get_json(kind, path, params)
            if path.strip("/") == "":
                return type(result)(
                    url=result.url,
                    payload={"message": "Welcome to nginx!"},
                    retrieved_at=result.retrieved_at,
                    is_mock=True,
                )
            return result

    adapter = HomeAssistantSource(ProxyFetcher(settings), settings)
    with pytest.raises(HubUnavailable, match="not as Home Assistant does"):
        run(adapter.probe())


def test_a_dead_sensor_in_a_live_hub_is_absent_not_flat(
    run, settings, sensor_sources, now
):
    """the design other half: a gap has to render as no recent reading.

    The hub answers, the entity answers, and its value is six hours old. The
    row is not written — which is what makes the Almanac able to draw a gap
    rather than a line.
    """
    old = now - timedelta(hours=6)
    adapter = HomeAssistantSource(RecordedFetcher(settings, now=lambda: old), settings)
    result = run(adapter.poll(sensor_sources, now=now))
    assert result.ok
    assert result.readings == ()
    assert {item.reason for item in result.skipped} == {"stale_entity"}


def test_every_synthesised_payload_says_it_is_synthesised(run, fetcher):
    """A mock cannot quietly pass for a fetch — in a test, in a log, or in a
    citation. The same rule the botany worker and E hold to."""
    states = run(fetcher.get_json("home_assistant", "/states"))
    assert states.is_mock
    assert all("_synthetic" in row for row in states.payload)


def test_the_mocks_freshness_is_relative_to_the_injected_clock(run, fetcher, now):
    result = run(fetcher.get_json("home_assistant", "/states"))
    stamps = {row["last_updated"] for row in result.payload if "last_updated" in row}
    assert (now - timedelta(seconds=120)).isoformat() in stamps


def test_a_single_entity_fetch_is_served_and_a_missing_one_raises(run, fetcher):
    one = run(fetcher.get_json("home_assistant", "/states/sensor.study_temperature"))
    assert one.payload["entity_id"] == "sensor.study_temperature"
    with pytest.raises(HubUnavailable, match="404"):
        run(fetcher.get_json("home_assistant", "/states/sensor.nope"))
