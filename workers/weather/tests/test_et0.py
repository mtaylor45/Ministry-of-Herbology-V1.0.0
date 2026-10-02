"""the ET₀ fallback, and the day it refuses to invent.

The design decision's own sentence is the specification: a silent gap in ET₀ makes the
deficit look healthier than it is. These tests hold the three outcomes apart.
"""

from datetime import date

import pytest

from workers.weather.et0 import (
    HARGREAVES,
    INGESTED,
    UNAVAILABLE,
    extraterrestrial_radiation_mm,
    hargreaves_et0_mm,
    resolve_et0,
)

#: The Grounds (``fixtures/site.json``).
LATITUDE = 39.7684


def test_ingested_et0_always_wins():
    """The fallback never overwrites a value the source supplied."""
    resolved = resolve_et0(
        date(2026, 6, 1),
        ingested_mm=5.4,
        tmin_c=17.0,
        tmax_c=31.0,
        latitude_deg=LATITUDE,
    )
    assert resolved.mm == 5.4
    assert resolved.method == INGESTED
    assert not resolved.is_fallback


def test_hargreaves_fills_a_missing_day_rather_than_skipping_it():
    resolved = resolve_et0(
        date(2026, 6, 1),
        ingested_mm=None,
        tmin_c=17.0,
        tmax_c=31.0,
        latitude_deg=LATITUDE,
    )
    assert resolved.method == HARGREAVES
    assert resolved.mm is not None and resolved.mm > 0
    assert resolved.source == "local_hargreaves"
    assert resolved.is_fallback


def test_a_day_with_no_temperatures_is_missing_not_zero():
    """An unknown day is not a zero-evaporation day."""
    resolved = resolve_et0(
        date(2026, 6, 1),
        ingested_mm=None,
        tmin_c=None,
        tmax_c=None,
        latitude_deg=LATITUDE,
    )
    assert resolved.method == UNAVAILABLE
    assert resolved.mm is None
    assert resolved.is_missing


def test_the_fallback_lands_near_the_figure_it_stands_in_for(fixture):
    """Close enough to be useful, and known to run high — which is the point.

    Hargreaves needs no humidity, wind or radiation, and pays for that by
    overestimating in a humid continental climate. The design decision calls that a
    documented degradation rather than a defect, so this asserts the band, not
    a match: a fallback that silently drifted to twice the real figure would
    have people watering plants that do not need it.
    """
    days = fixture("weather/baseline_30d.json")["days"]
    ratios = []
    for day in days:
        computed = hargreaves_et0_mm(
            date.fromisoformat(day["date"]), day["tmin_c"], day["tmax_c"], LATITUDE
        )
        ratios.append(computed / day["et0_mm"])
    # Across the 30 baseline days the ratio runs 0.82–1.52, mean 1.08. The
    # worst days are the cool dull ones (2026-05-14 and -15): Hargreaves has no
    # cloud term, so a day Open-Meteo knows was overcast reads to it like any
    # other day with that temperature span.
    assert all(0.75 <= ratio <= 1.6 for ratio in ratios), ratios
    average = sum(ratios) / len(ratios)
    assert 0.9 <= average <= 1.25, f"mean ratio {average:.2f} against Open-Meteo"


def test_radiation_follows_the_season():
    """Ra at this latitude peaks at the solstice and bottoms in December."""
    midsummer = extraterrestrial_radiation_mm(LATITUDE, 172)
    midwinter = extraterrestrial_radiation_mm(LATITUDE, 355)
    equinox = extraterrestrial_radiation_mm(LATITUDE, 80)
    assert midsummer > equinox > midwinter
    assert midwinter > 0


def test_radiation_does_not_blow_up_inside_the_polar_circle():
    """``-tan φ · tan δ`` leaves [-1, 1] above 66.5°, where ``acos`` would raise."""
    for latitude in (67.0, 78.9, -80.0, 89.9):
        for day_of_year in (1, 100, 172, 300, 365):
            value = extraterrestrial_radiation_mm(latitude, day_of_year)
            assert value >= 0.0


def test_et0_is_never_negative_however_cold_it_gets():
    """Below -17.8 °C the ``(Tmean + 17.8)`` term turns negative.

    Unclamped, that would subtract from the deficit — crediting a frozen plant
    with rain that never fell.
    """
    assert hargreaves_et0_mm(date(2026, 1, 15), -30.0, -22.0, LATITUDE) == 0.0


def test_a_flat_day_evaporates_nothing():
    """No temperature span, no Hargreaves signal. Zero, not an error."""
    assert hargreaves_et0_mm(date(2026, 6, 1), 20.0, 20.0, LATITUDE) == 0.0


def test_reversed_temperatures_do_not_produce_a_nan():
    """A source that swaps min and max is wrong, not a reason to crash."""
    forward = hargreaves_et0_mm(date(2026, 6, 1), 17.0, 31.0, LATITUDE)
    reversed_ = hargreaves_et0_mm(date(2026, 6, 1), 31.0, 17.0, LATITUDE)
    assert reversed_ == pytest.approx(forward)


def test_the_day_records_how_it_was_arrived_at():
    """a fallback day is recorded as such, not silently mixed in."""
    fallback = resolve_et0(
        date(2026, 6, 1),
        ingested_mm=None,
        tmin_c=10.0,
        tmax_c=20.0,
        latitude_deg=LATITUDE,
    ).to_dict()
    assert fallback["et0_method"] == HARGREAVES
    assert fallback["et0_source"] == "local_hargreaves"
    assert fallback["day"] == "2026-06-01"
