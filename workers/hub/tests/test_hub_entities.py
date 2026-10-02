"""One entity into one reading, or into a named reason — the hub.

These are the tests for the three refusals in ``workers/hub/entities.py``.
Each one exists because the alternative puts a wrong number somewhere nobody
will question it, so each is asserted on its consequence rather than on its
return value alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from workers.hub.entities import (
    PLAUSIBLE_RANGE,
    SUPPORTED_METRICS,
    convert,
    device_class_agrees,
    reading_from_state,
)
from workers.hub.sources.base import EntityState, Reading, Skipped

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def entity(
    state: str,
    *,
    unit: str | None = "°C",
    device_class: str | None = "temperature",
    age_s: float = 60.0,
    entity_id: str = "sensor.study_temperature",
) -> EntityState:
    attributes: dict[str, object] = {}
    if unit is not None:
        attributes["unit_of_measurement"] = unit
    if device_class is not None:
        attributes["device_class"] = device_class
    return EntityState(
        entity_id=entity_id,
        state=state,
        attributes=attributes,
        last_updated=NOW - timedelta(seconds=age_s),
    )


def read(state: EntityState, metric: str = "temperature_c", **kwargs):
    return reading_from_state(
        state,
        metric=metric,
        source_id="source-1",
        at=NOW,
        max_age_s=kwargs.pop("max_age_s", 3600.0),
        **kwargs,
    )


def test_a_celsius_thermostat_becomes_a_reading_at_the_poll_time():
    outcome = read(entity("21.4"))
    assert isinstance(outcome, Reading)
    assert outcome.value == pytest.approx(21.4)
    # The poll's clock, not Home Assistant's. See the docstring on
    # `reading_from_state` for the argument: `last_updated` only moves when a
    # value *changes*, so stamping rows with it would make a room with a
    # draught meet the releases's cadence and a still room miss it.
    assert outcome.time == NOW
    assert outcome.entity_id == "sensor.study_temperature"


def test_a_fahrenheit_thermostat_is_converted_rather_than_stored_raw():
    """The failure this prevents is the one that kills a plant.

    68 °the hub is a comfortable room. Stored as 68 it is a heatwave; stored as the
    20 °C it actually is, it is a room. The same sensor read the other way
    turns a mild night into a frost alert.
    """
    outcome = read(entity("68.0", unit="°F"))
    assert isinstance(outcome, Reading)
    assert outcome.value == pytest.approx(20.0)


def test_kelvin_converts_and_an_unknown_unit_is_refused_not_assumed():
    assert convert("temperature_c", 293.15, "K") == pytest.approx(20.0)
    assert convert("temperature_c", 21.0, "°Ré") is None

    outcome = read(entity("21.0", unit="°Ré"))
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "unconvertible_unit"


def test_a_missing_unit_on_a_temperature_is_read_as_celsius():
    """Everything internal is SI and HA's metric default is Celsius.

    Asserted because it is a guess, and a guess that is written down is one
    somebody can argue with.
    """
    outcome = read(entity("19.0", unit=None))
    assert isinstance(outcome, Reading)
    assert outcome.value == pytest.approx(19.0)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("unavailable", "entity_unavailable"),
        ("unknown", "entity_unavailable"),
        ("", "entity_unavailable"),
        ("comfortable", "not_a_number"),
    ],
)
def test_home_assistant_saying_nothing_is_absence_never_zero(state, reason):
    """where a reading is absent, the API says absent.

    ``unavailable`` arrives in the same field a number would, and reading it
    as 0 would put a 0 °C room — or a 0 % soil probe, which is a watering
    decision — into the hypertable.
    """
    outcome = read(entity(state))
    assert isinstance(outcome, Skipped)
    assert outcome.reason == reason


def test_a_dead_battery_is_refused_however_confidently_home_assistant_answers():
    """HA serves the last state it saw forever; that is not a measurement.

    Under the design there is no second route to indoor conditions, so a stale
    value is not a conservative choice — it is the only number anyone sees.
    """
    stale = entity("19.4", age_s=6 * 3600)
    outcome = read(stale, max_age_s=3600.0)
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "stale_entity"
    assert "21600s ago" in outcome.detail


def test_an_entity_with_no_last_updated_is_not_given_the_benefit_of_the_doubt():
    bare = EntityState(entity_id="sensor.x", state="21.0", attributes={})
    outcome = read(bare)
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "stale_entity"


def test_a_clock_a_little_ahead_does_not_drop_every_reading():
    ahead = entity("21.0", age_s=-30.0)
    assert isinstance(read(ahead), Reading)


def test_a_bathroom_hygrometer_cannot_be_stored_as_a_soil_probe():
    """The the design case, and the reason `device_class` is checked at all.

    ``external_ids`` is the operator's claim; ``device_class`` is Home
    Assistant's. When they disagree about *soil*, accepting the operator's
    would not be a mislabelled row — it would be the app inventing a probe
    that does not exist and handing the weather engine's water balance an override
    to obey.
    """
    outcome = read(
        entity("62.0", unit="%", device_class="pressure", entity_id="sensor.bath"),
        "soil_moisture_pct",
        specimen_id="specimen-1",
    )
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "device_class_mismatch"


def test_a_probe_that_calls_itself_humidity_is_still_a_probe():
    """MiFlora and HA's own plant integration report soil moisture that way.

    What makes the reading a soil reading is the specimen it is bound to, not
    the word Home Assistant chose.
    """
    outcome = read(
        entity("31.0", unit="%", device_class="humidity", entity_id="sensor.pot"),
        "soil_moisture_pct",
        specimen_id="specimen-1",
    )
    assert isinstance(outcome, Reading)
    assert outcome.specimen_id == "specimen-1"
    assert outcome.metric == "soil_moisture_pct"


def test_an_entity_with_no_device_class_at_all_is_accepted():
    """Template and MQTT sensors often have none; refusing them refuses half
    of a real installation."""
    outcome = read(entity("44.0", unit="%", device_class=None), "humidity_pct")
    assert isinstance(outcome, Reading)


def test_device_class_agreement_is_per_metric():
    assert device_class_agrees("humidity_pct", "humidity")
    assert not device_class_agrees("humidity_pct", "temperature")
    assert not device_class_agrees("not_a_metric", None)


def test_an_impossible_percentage_is_refused_before_it_reaches_a_rollup():
    """340 % is a unit error upstream. Stored, it poisons the hourly average
    the Almanac draws, and no later correction reaches it."""
    outcome = read(entity("340", unit="%", device_class="humidity"), "humidity_pct")
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "out_of_range"
    assert "0..100" in outcome.detail


def test_every_supported_metric_has_a_range_and_a_device_class_rule():
    """A metric added to the contract without either would be stored unchecked."""
    from workers.hub.entities import ALLOWED_DEVICE_CLASSES

    for metric in SUPPORTED_METRICS:
        assert metric in PLAUSIBLE_RANGE, metric
        assert metric in ALLOWED_DEVICE_CLASSES, metric


def test_supported_metrics_match_the_contracts_check_constraint():
    """``reading.metric`` has a CHECK; a metric this worker would store and
    the database would refuse is a row lost at 3 a.m. rather than in CI."""
    import re
    from pathlib import Path

    schema = (
        Path(__file__).resolve().parents[3] / "contracts" / "schema" / "001_init.sql"
    ).read_text()
    block = re.search(r"CREATE TABLE reading \((.*?)\n\);", schema, re.DOTALL)
    assert block is not None
    allowed = set(re.findall(r"'([a-z0-9_]+)'", block.group(1)))
    assert set(SUPPORTED_METRICS) == allowed


def test_soil_ec_converts_from_the_spellings_a_probe_might_use():
    assert convert("soil_ec", 1.2, "mS/cm") == pytest.approx(1200.0)
    assert convert("soil_ec", 1.2, "dS/m") == pytest.approx(1200.0)
    assert convert("soil_ec", 800.0, "µS/cm") == pytest.approx(800.0)
    assert convert("soil_ec", 800.0, "ppm") is None


def test_an_unsupported_metric_is_refused_rather_than_stored():
    outcome = read(entity("1013", unit="hPa", device_class="pressure"), "pressure_hpa")
    assert isinstance(outcome, Skipped)
    assert outcome.reason == "unsupported_metric"
