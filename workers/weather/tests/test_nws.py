"""NWS, against the real recordings in ``mocks/recorded/nws/``.

Every payload here was fetched from api.weather.gov on 2026-09-23. The one
thing worth restating: **an empty alert collection is an answer**, and the
frost guard must never read "NWS is down" as "no frost is coming".
"""

from datetime import UTC, datetime

import pytest

from workers.weather.sources.base import CONDITIONS
from workers.weather.sources.nws import (
    NwsSource,
    condition_from_phrase,
    fahrenheit_to_c,
    measurement,
    parse_alerts,
    parse_latest_observation,
    parse_period_forecast,
    wind_kph,
)

ISSUED = datetime(2026, 9, 23, 20, 9, tzinfo=UTC)


@pytest.fixture
def source(fetcher):
    return NwsSource(fetcher)


def test_a_measurement_block_yields_its_value(payload):
    observation = payload("nws/observation__kind-latest.json")["properties"]
    assert measurement(observation["temperature"]) == 18.0
    assert measurement(observation["windSpeed"]) == pytest.approx(18.504)


def test_a_null_measurement_is_none_not_zero(payload):
    """An unmeasured reading means unmeasured, not "it did not rain"."""
    observation = payload("nws/observation__kind-latest.json")["properties"]
    assert observation["precipitationLast3Hours"]["value"] is None
    assert measurement(observation["precipitationLast3Hours"]) is None
    assert parse_latest_observation({"properties": observation})[0].precip_mm is None


def test_multi_hour_rainfall_totals_are_not_read_into_an_hourly_row(payload):
    """KIND publishes a 3-hour total and no 1-hour one, and that is the trap.

    ``weather_daily`` sums ``precip_mm`` across every row in the day. Reading a
    3-hour total into each of three hourly rows would triple the rainfall,
    clear a deficit nothing cleared, and leave a plant unwatered.
    """
    properties = dict(payload("nws/observation__kind-latest.json")["properties"])
    assert "precipitationLastHour" not in properties
    properties["precipitationLast3Hours"] = {"unitCode": "wmoUnit:mm", "value": 9.0}
    assert parse_latest_observation({"properties": properties})[0].precip_mm is None

    properties["precipitationLastHour"] = {"unitCode": "wmoUnit:mm", "value": 3.0}
    assert parse_latest_observation({"properties": properties})[0].precip_mm == 3.0


def test_the_recorded_observation_parses_whole(payload):
    row = parse_latest_observation(payload("nws/observation__kind-latest.json"))[0]
    assert row.time == datetime(2026, 9, 23, 19, 45, tzinfo=UTC)
    assert row.temperature_c == 18.0
    assert row.condition == "cloudy"
    assert row.cloud_pct == 100.0, "BKN over OVC is overcast, not the average"
    assert row.source == "nws"
    assert row.et0_mm is None, "NWS publishes no ET₀ — this is the design case"


def test_a_payload_with_no_timestamp_yields_nothing():
    assert parse_latest_observation({"properties": {"temperature": {"value": 4}}}) == ()
    assert parse_latest_observation({}) == ()


def test_wind_takes_the_top_of_a_range_and_converts_it():
    assert wind_kph("10 mph") == pytest.approx(16.09344)
    assert wind_kph("5 to 10 mph") == pytest.approx(16.09344)
    assert wind_kph("") is None
    assert wind_kph(None) is None
    assert wind_kph("calm") is None


def test_fahrenheit_converts():
    assert fahrenheit_to_c(32.0) == 0.0
    assert fahrenheit_to_c(64.0) == pytest.approx(17.7778, abs=1e-3)


def test_forecast_prose_maps_onto_the_shared_vocabulary():
    assert condition_from_phrase("Slight Chance Drizzle") == "rain"
    assert condition_from_phrase("Mostly Sunny") == "partly_cloudy"
    assert condition_from_phrase("Sunny") == "clear"
    assert condition_from_phrase("Patchy Fog") == "fog"
    assert condition_from_phrase("Chance Showers And Thunderstorms") == "storm"
    assert condition_from_phrase(None) is None


def test_the_wetter_half_of_a_mixed_forecast_wins():
    """ "Rain then partly sunny" still waters a plant."""
    assert condition_from_phrase("Chance Rain Showers then Partly Sunny") == "rain"


def test_a_night_period_sets_the_low_and_a_day_period_sets_the_high(payload):
    """Filling both from one number hands the frost guard a high as a low."""
    rows = parse_period_forecast(
        payload("nws/forecast__the-grounds.json"), issued_at=ISSUED
    )
    assert rows
    days = [row for row in rows if row.temp_max_c is not None]
    nights = [row for row in rows if row.temp_min_c is not None]
    assert days and nights
    assert all(row.temp_min_c is None for row in days)
    assert all(row.temp_max_c is None for row in nights)
    assert all(row.source == "nws" for row in rows)
    assert all(row.et0_mm is None for row in rows)


def test_the_recorded_forecast_parses_every_period(payload):
    raw = payload("nws/forecast__the-grounds.json")
    rows = parse_period_forecast(raw, issued_at=ISSUED)
    assert len(rows) == len(raw["properties"]["periods"])
    assert all(row.condition is None or row.condition in CONDITIONS for row in rows)


def test_the_hourly_recording_is_hourly(payload):
    raw = payload("nws/forecast-hourly__the-grounds.json")
    assert raw["properties"]["_trimmed"], "the trim must stay declared in the payload"
    rows = parse_period_forecast(raw, issued_at=ISSUED, horizon="hourly")
    assert len(rows) == 48
    gaps = {
        (rows[index + 1].time - rows[index].time).total_seconds()
        for index in range(len(rows) - 1)
    }
    assert gaps == {3600.0}


def test_an_empty_alert_collection_is_an_answer_not_an_error(payload, source, run):
    """The normal state of the world, and it must not look like a failure."""
    raw = payload("nws/alerts__inz050.json")
    assert raw["features"] == []
    assert parse_alerts(raw) == ()

    result = run(source.fetch_advisories("INZ050"))
    assert result.ok, "no advisories in force is not an error"
    assert result.advisories == ()


def test_a_live_frost_advisory_parses_into_a_row(payload):
    advisories = parse_alerts(payload("nws/alerts__frost-advisory-active.json"))
    assert len(advisories) == 4
    first = advisories[0]
    assert first.event == "Frost Advisory"
    assert first.is_frost
    assert first.severity == "Minor"
    assert first.onset is not None and first.onset.tzinfo is not None
    assert first.headline and "Frost Advisory" in first.headline
    assert first.external_id.startswith("urn:oid:")


def test_an_advisory_knows_the_window_it_covers(payload):
    advisory = parse_alerts(payload("nws/alerts__frost-advisory-active.json"))[0]
    assert advisory.onset is not None and advisory.expires is not None
    assert advisory.covers(advisory.onset)
    assert advisory.covers(advisory.expires)
    assert not advisory.covers(advisory.onset.replace(year=advisory.onset.year - 1))
    assert not advisory.covers(advisory.expires.replace(year=advisory.expires.year + 1))


def test_an_advisory_with_no_window_is_treated_as_in_force():
    """NWS omits ``onset`` on messages effective immediately."""
    from workers.weather.sources.base import Advisory

    advisory = Advisory(external_id="x", event="Freeze Warning")
    assert advisory.covers(datetime(2026, 1, 1, tzinfo=UTC))
    assert advisory.is_frost


def test_only_frost_events_concern_this_engine():
    from workers.weather.sources.base import Advisory

    assert Advisory(external_id="a", event="Frost Advisory").is_frost
    assert Advisory(external_id="b", event="Freeze Warning").is_frost
    assert Advisory(external_id="c", event="Hard Freeze Warning").is_frost
    assert not Advisory(external_id="d", event="Excessive Heat Warning").is_frost
    assert not Advisory(external_id="e", event="Flood Watch").is_frost


def test_an_alert_without_an_id_or_an_event_is_skipped():
    """A row we cannot key is a row we cannot upsert or dismiss."""
    raw = {"features": [{"properties": {"event": "Frost Advisory"}}, {"x": 1}]}
    assert parse_alerts(raw) == ()


def test_the_point_lookup_names_the_zone_the_coordinates_are_actually_in(
    source, run, fixture
):
    """``site.json`` and the coordinates must name the same zone.

    They did not until the fixture said ``INZ050`` (Wayne County)
    while the site's own coordinates resolve to ``INZ047`` (Marion County), and
    an advisory fetched for the wrong county is an advisory about somebody
    else's frost. The fixture was corrected; this asserts the agreement so it
    cannot drift back. The recorded ``/points`` payload is the evidence — see
    ``mocks/recorded/PROVENANCE.md``.
    """
    point = run(source.resolve_point(39.7684, -86.1581))
    assert point["forecast_zone"] == "INZ047"
    assert point["grid_id"] == "IND"
    assert point["forecast_url"].endswith("/forecast")
    assert fixture("site.json")["nws_zone"] == point["forecast_zone"]


def test_both_zone_recordings_name_the_county_they_cover(payload):
    """Why the zone had to be corrected, kept as evidence.

    NWS titles each zone's alert feed with the county it covers. Both zones stay
    recorded so the correction rests on the two feeds rather than on
    anybody's report of them — and so a future edit back to INZ050 has this
    sitting next to it.
    """
    wrong = payload("nws/alerts__inz050.json")["title"]
    right = payload("nws/alerts__inz047.json")["title"]
    assert "Wayne (INZ050)" in wrong, "the zone site.json used to name"
    assert "Marion (INZ047)" in right, "the zone the coordinates resolve to"
    assert wrong != right


def test_a_source_that_is_down_is_reported_not_raised(run):
    from workers.weather.mocks.fetcher import UnavailableFetcher

    result = run(NwsSource(UnavailableFetcher()).fetch_advisories("INZ047"))
    assert not result.ok
    assert result.advisories == ()
