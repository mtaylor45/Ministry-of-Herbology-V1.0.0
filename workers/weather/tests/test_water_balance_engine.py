"""The water balance as the sole authority on outdoor watering.

the design removed the soil sensor from v1 and did not replace it. So these
tests are less about the arithmetic — ``tests/engines/test_water_balance.py``
owns that, against the frozen scenarios — and more about the thing that
arithmetic cannot do for itself: **say how much it is worth.**

The failure this file exists to prevent: an input goes missing, the deficit
stops advancing, every plant reads as comfortable, and the app goes quiet.
"""

from datetime import date, timedelta

import pytest

from workers.weather.tasks import (
    DayWeather,
    WaterCoefficient,
    capacity_mm,
    run_balance,
)

LATITUDE = 39.7684
CITED = WaterCoefficient(
    value=0.9, confidence="medium", source="Perenual plant care API"
)


def dry_days(count: int, *, et0_mm: float | None = 5.0, **kwargs) -> list[DayWeather]:
    start = date(2026, 6, 1)
    return [
        DayWeather(
            day=start + timedelta(days=offset),
            precip_mm=0.0,
            et0_mm=et0_mm,
            tmin_c=17.0,
            tmax_c=31.0,
            **kwargs,
        )
        for offset in range(count)
    ]


def test_a_clean_run_is_medium_not_high():
    """A modelled deficit is a calculation about soil nobody has measured.

    ``high`` is reserved for something observed, and nothing
    observes the soil. A water balance that called itself ``high`` would be
    claiming a measurement it does not have.
    """
    series = run_balance(
        dry_days(10),
        k_c=CITED,
        capacity=32.75,
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    assert series.assessment.confidence == "medium"
    assert not series.assessment.is_degraded


def test_a_missing_et0_day_does_not_advance_the_deficit_and_says_so():
    """The failure the design was written about, held in one test.

    A day with no ET₀ and no temperatures cannot be computed. The deficit
    stands still, which makes the plant look better watered than it is — so the
    series reports the gap rather than letting the number speak for itself.
    """
    days = dry_days(5)
    days[2] = DayWeather(day=days[2].day, precip_mm=0.0, et0_mm=None)

    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    third, fourth = series.days[1], series.days[2]
    assert fourth.deficit_mm == third.deficit_mm, "a missing day must not advance"
    assert fourth.et0.is_missing
    assert fourth.to_dict()["reference_et0_mm"] is None

    codes = {d.code for d in series.assessment.degradations}
    assert "et0_missing" in codes
    assert series.assessment.confidence == "low"

    full = run_balance(
        dry_days(5), k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    assert series.deficit_mm < full.deficit_mm, (
        "the reported deficit is lower than the real one, which is exactly why "
        "the gap has to be declared"
    )


def test_the_hargreaves_fallback_keeps_the_deficit_moving_and_is_labelled():
    """compute locally rather than skip a day — and say which days."""
    days = [
        DayWeather(day=day.day, precip_mm=0.0, et0_mm=None, tmin_c=17.0, tmax_c=31.0)
        for day in dry_days(5)
    ]
    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )

    assert series.deficit_mm > 0, "the deficit must keep advancing"
    assert all(day.et0.is_fallback for day in series.days)
    assert all(day.to_dict()["et0_method"] == "hargreaves" for day in series.days)

    codes = {d.code for d in series.assessment.degradations}
    assert codes == {"et0_fallback"}
    assert series.assessment.confidence == "medium"
    assert "5 days" in series.assessment.degradations[0].detail


def test_an_ingested_value_is_never_overwritten_by_the_fallback():
    days = [
        DayWeather(day=day.day, precip_mm=0.0, et0_mm=5.0, tmin_c=17.0, tmax_c=31.0)
        for day in dry_days(3)
    ]
    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    assert all(day.et0.method == "ingested" for day in series.days)
    assert all(day.et0.mm == 5.0 for day in series.days)
    assert not series.assessment.is_degraded


def test_an_uncited_coefficient_makes_the_whole_answer_unknown():
    """the design, the no-invented-plant-facts rule. The balance still answers; it does not pretend
    to know."""
    series = run_balance(
        dry_days(10),
        k_c=WaterCoefficient(value=0.25, confidence="unknown", source=None),
        capacity=32.75,
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    assert series.assessment.confidence == "unknown"
    assert {d.code for d in series.assessment.degradations} == {"k_c_uncited"}
    # Still a complete, definite answer — the design shipping path.
    assert isinstance(series.deficit_mm, float)
    assert series.is_due in (True, False)


def test_a_category_default_is_carried_through_as_a_category_default():
    """cited to a table, at category scope, capped at medium.

    The thing being guarded against is laundering — a coefficient that arrives
    as "typical for a broadleaf evergreen shrub" and leaves as "water on
    Tuesday" with nothing said.
    """
    coefficient = WaterCoefficient.from_care_value(
        {"field": "water_k_c", "value": 0.8, "confidence": "high"},
        {"title": "FAO-56 table 12", "scope": "category", "category": "shrub"},
    )
    assert coefficient.is_category_default
    assert coefficient.confidence == "medium", "the design caps it, never high"

    series = run_balance(
        dry_days(6),
        k_c=coefficient,
        capacity=60.0,
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    assert series.assessment.confidence == "medium"
    reason = series.assessment.degradations[0]
    assert reason.code == "k_c_category_default"
    assert "shrub" in reason.detail and "FAO-56" in reason.detail


def test_a_species_level_citation_carries_no_category_caveat():
    coefficient = WaterCoefficient.from_care_value(
        {"field": "water_k_c", "value": 0.9, "confidence": "medium"},
        {"title": "Perenual plant care API"},
    )
    assert not coefficient.is_category_default
    assert coefficient.degradations() == []


def test_no_coefficient_at_all_is_unknown_and_still_computes():
    """A plant whose category cannot be established honestly has no coefficient.

    the design says that case must stay reachable and rendered. The engine uses a
    placeholder so the arithmetic is defined, and reports ``unknown`` so nobody
    mistakes the placeholder for a fact about the plant.
    """
    coefficient = WaterCoefficient.from_care_value(None)
    assert coefficient.value is None
    assert coefficient.effective == WaterCoefficient.FALLBACK
    series = run_balance(
        dry_days(8),
        k_c=coefficient,
        capacity=60.0,
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    assert series.assessment.confidence == "unknown"
    assert series.deficit_mm > 0


def test_a_stale_ingest_degrades_the_answer():
    """A deficit that stopped advancing reads lower than the plant's real one."""
    fresh = run_balance(
        dry_days(5),
        k_c=CITED,
        capacity=60.0,
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    stale = run_balance(
        dry_days(5),
        k_c=CITED,
        capacity=60.0,
        cover_factor=1.0,
        latitude=LATITUDE,
        stale_hours=30.0,
    )
    assert fresh.assessment.confidence == "medium"
    assert stale.assessment.confidence == "low"
    assert "30 hours old" in stale.assessment.degradations[0].detail


def test_forecast_days_are_declared_as_forecast():
    """Rain that has not fallen yet has not watered anything."""
    days = dry_days(3) + [
        DayWeather(
            day=date(2026, 6, 4),
            precip_mm=20.0,
            et0_mm=5.0,
            tmin_c=17.0,
            tmax_c=31.0,
            is_forecast=True,
        )
    ]
    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    assert series.days[-1].is_forecast
    assert series.days[-1].to_dict()["is_forecast"] is True
    assert "forecast_not_observed" in {d.code for d in series.assessment.degradations}


def test_a_secondary_source_day_is_declared():
    """NWS has no ET₀, so a run on NWS is a run on the fallback throughout."""
    days = [
        DayWeather(
            day=day.day,
            precip_mm=0.0,
            et0_mm=None,
            tmin_c=17.0,
            tmax_c=31.0,
            source="nws",
        )
        for day in dry_days(4)
    ]
    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    codes = {d.code for d in series.assessment.degradations}
    assert {"secondary_source", "et0_fallback"} <= codes


def test_rain_on_a_covered_porch_never_reaches_the_pot():
    """``f_cover = 0`` — the most commonly got-wrong term in the model."""
    days = dry_days(6) + [DayWeather(day=date(2026, 6, 7), precip_mm=38.0, et0_mm=5.0)]
    capacity = capacity_mm(True, 25)

    open_sky = run_balance(
        days, k_c=CITED, capacity=capacity, cover_factor=1.0, latitude=LATITUDE
    )
    covered = run_balance(
        days, k_c=CITED, capacity=capacity, cover_factor=0.0, latitude=LATITUDE
    )

    assert open_sky.deficit_mm == 0.0
    assert covered.is_due, "the porch lemon is still thirsty after the storm"
    assert all(day.precip_mm == 0.0 for day in covered.days)
    assert covered.days[-1].gross_precip_mm == 38.0, "what fell is still reported"


def test_rain_that_clears_a_due_watering_marks_it_satisfied():
    """The plan is explicit: the task must not simply vanish."""
    days = dry_days(6) + [DayWeather(day=date(2026, 6, 7), precip_mm=38.0, et0_mm=5.0)]
    series = run_balance(
        days,
        k_c=CITED,
        capacity=capacity_mm(True, 45),
        cover_factor=1.0,
        latitude=LATITUDE,
    )
    assert series.days[-2].status == "due"
    assert series.status == "satisfied"
    assert series.satisfied_by == "rain"


def test_watering_it_yourself_also_satisfies_the_task():
    days = dry_days(8)
    series = run_balance(
        days,
        k_c=CITED,
        capacity=capacity_mm(True, 45),
        cover_factor=1.0,
        latitude=LATITUDE,
        irrigation={days[-1].day: 40.0},
    )
    assert series.status == "satisfied"
    assert series.satisfied_by == "irrigation"
    assert not series.is_due


def test_a_day_that_was_never_due_is_not_reported_as_satisfied():
    """ "Satisfied" means a watering was owed and the weather settled it."""
    days = [DayWeather(day=date(2026, 6, 1), precip_mm=20.0, et0_mm=1.0)]
    series = run_balance(
        days, k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    assert series.status == "ok"
    assert series.satisfied_by is None


def test_a_wet_probe_overrides_a_model_that_thinks_it_is_bone_dry():
    """The override seam the design says to keep. No hardware drives it today."""
    series = run_balance(
        dry_days(30),
        k_c=CITED,
        capacity=32.75,
        cover_factor=1.0,
        latitude=LATITUDE,
        sensor_override_pct=62.0,
    )
    assert series.deficit_mm == pytest.approx(32.75)
    assert not series.is_due, "a wet probe must win"


def test_an_empty_series_answers_rather_than_raising():
    series = run_balance(
        [], k_c=CITED, capacity=60.0, cover_factor=1.0, latitude=LATITUDE
    )
    assert series.days == ()
    assert series.deficit_mm == 0.0
    assert series.status == "ok"


def test_the_deficit_never_leaves_its_bounds():
    days = [
        DayWeather(day=date(2026, 6, 1) + timedelta(days=n), precip_mm=0.0, et0_mm=50.0)
        for n in range(20)
    ]
    series = run_balance(
        days, k_c=CITED, capacity=32.75, cover_factor=1.0, latitude=LATITUDE
    )
    assert all(0.0 <= day.deficit_mm <= 32.75 for day in series.days)
