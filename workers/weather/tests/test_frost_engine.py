"""The frost guard: who gets warned, who does not, and who cannot be judged.

``tests/engines/test_frost_guard.py`` owns the scenario expectations. This
file covers the parts that only exist in the earlier engine: one alert per plant,
the advisory, the unassessable list, and the return-outdoors rule.
"""

from datetime import UTC, date, datetime

from workers.weather.sources.base import Advisory
from workers.weather.tasks import (
    FROST_MARGIN_C,
    FrostNight,
    FrostSubject,
    frost_alerts,
    frost_threshold_c,
    return_outdoors_day,
)

NIGHTS = [
    FrostNight(day=date(2026, 10, 20), low_c=14.0),
    FrostNight(day=date(2026, 10, 21), low_c=12.0),
    FrostNight(day=date(2026, 10, 22), low_c=4.0),
    FrostNight(day=date(2026, 10, 23), low_c=-2.0),
    FrostNight(day=date(2026, 10, 24), low_c=-1.0),
    FrostNight(day=date(2026, 10, 25), low_c=6.0),
    FrostNight(day=date(2026, 10, 26), low_c=9.0),
    FrostNight(day=date(2026, 10, 27), low_c=10.0),
    FrostNight(day=date(2026, 10, 28), low_c=11.0),
]

LEMON = FrostSubject(
    specimen_id="lemon",
    is_outdoor=True,
    in_container=True,
    min_temp_c=2.0,
    min_temp_confidence="high",
)
BASIL = FrostSubject(
    specimen_id="basil",
    is_outdoor=True,
    in_container=True,
    min_temp_c=10.0,
    min_temp_confidence="high",
)
ROSE = FrostSubject(
    specimen_id="rose",
    is_outdoor=True,
    in_container=False,
    min_temp_c=-29.0,
    min_temp_confidence="high",
)
MONSTERA = FrostSubject(
    specimen_id="monstera",
    is_outdoor=False,
    in_container=True,
    min_temp_c=10.0,
    min_temp_confidence="high",
)
UNKNOWN_SPECIES = FrostSubject(
    specimen_id="mystery", is_outdoor=True, in_container=True, min_temp_c=None
)

ADVISORY = Advisory(
    external_id="NWS-2026-1023-FROST",
    event="Freeze Warning",
    severity="Moderate",
    onset=datetime(2026, 10, 23, 2, 0, tzinfo=UTC),
    expires=datetime(2026, 10, 24, 13, 0, tzinfo=UTC),
    headline="Freeze Warning in effect from 2 AM to 9 AM",
)


def test_the_margin_is_three_fahrenheit():
    assert FROST_MARGIN_C == 3.0 * 5.0 / 9.0
    assert round(frost_threshold_c(2.0), 2) == 3.67


def test_one_alert_per_plant_not_one_per_cold_night():
    """Three warnings for one cold snap is how people learn to swipe them away."""
    report = frost_alerts(NIGHTS, [LEMON], today=date(2026, 10, 20))
    assert len(report.alerts) == 1
    assert report.alerts[0].night_of == date(2026, 10, 23)


def test_the_tenderest_plant_is_warned_first():
    report = frost_alerts(NIGHTS, [LEMON, BASIL], today=date(2026, 10, 20))
    nights = {alert.specimen_id: alert.night_of for alert in report.alerts}
    assert nights["basil"] < nights["lemon"]


def test_a_hardy_plant_is_never_dragged_indoors():
    """A false alert on a lavender teaches people to ignore the real one."""
    report = frost_alerts(NIGHTS, [ROSE], today=date(2026, 10, 20))
    assert report.alerts == ()


def test_indoor_plants_are_never_frost_alerted():
    report = frost_alerts(NIGHTS, [MONSTERA], today=date(2026, 10, 20))
    assert report.alerts == ()
    assert report.unassessable == ()


def test_containers_come_in_and_the_ground_gets_covered():
    """You cannot carry a hedge inside."""
    tender_hedge = FrostSubject(
        specimen_id="hedge", is_outdoor=True, in_container=False, min_temp_c=2.0
    )
    report = frost_alerts(NIGHTS, [LEMON, tender_hedge], today=date(2026, 10, 20))
    actions = {alert.specimen_id: alert.action for alert in report.alerts}
    assert actions == {"lemon": "bring_indoors", "hedge": "cover"}


def test_a_plant_that_cannot_be_judged_is_named_not_dropped():
    """An unanswerable question must not read as a reassuring answer.

    Silently omitting a species with no recorded minimum would put it in the
    same list as the lavender that genuinely needs nothing.
    """
    report = frost_alerts(NIGHTS, [UNKNOWN_SPECIES], today=date(2026, 10, 20))
    assert report.alerts == ()
    assert len(report.unassessable) == 1
    specimen_id, reason = report.unassessable[0]
    assert specimen_id == "mystery"
    assert "minimum temperature" in reason


def test_the_lookahead_is_seventy_two_hours():
    """A freeze five nights out is not today's task."""
    distant = [
        FrostNight(day=date(2026, 10, 20), low_c=14.0),
        FrostNight(day=date(2026, 10, 27), low_c=-5.0),
    ]
    report = frost_alerts(distant, [LEMON], today=date(2026, 10, 20))
    assert report.alerts == ()

    wider = frost_alerts(
        distant, [LEMON], today=date(2026, 10, 20), lookahead_hours=24 * 8
    )
    assert wider.alerts and wider.alerts[0].night_of == date(2026, 10, 27)


def test_an_advisory_is_carried_on_the_alert_and_raises_its_confidence():
    """Corroboration from the NWS is worth saying so about."""
    without = frost_alerts(NIGHTS, [LEMON], today=date(2026, 10, 20))
    with_advisory = frost_alerts(
        NIGHTS, [LEMON], advisories=[ADVISORY], today=date(2026, 10, 20)
    )
    assert without.alerts[0].advisory is None
    assert without.alerts[0].assessment.confidence == "medium"
    assert with_advisory.alerts[0].advisory == ADVISORY.headline
    assert with_advisory.alerts[0].assessment.confidence == "high"


def test_a_heat_advisory_is_not_a_frost_advisory():
    heat = Advisory(
        external_id="x",
        event="Excessive Heat Warning",
        onset=datetime(2026, 10, 23, 2, 0, tzinfo=UTC),
        expires=datetime(2026, 10, 24, 13, 0, tzinfo=UTC),
        headline="It is very hot",
    )
    report = frost_alerts(NIGHTS, [LEMON], advisories=[heat], today=date(2026, 10, 20))
    assert report.alerts[0].advisory is None


def test_an_advisory_extends_the_lookahead_to_its_own_window():
    """An advisory naming a night is a reason to look at that night."""
    nights = [
        FrostNight(day=date(2026, 10, 20), low_c=14.0),
        FrostNight(day=date(2026, 10, 25), low_c=-4.0),
    ]
    late = Advisory(
        external_id="y",
        event="Freeze Warning",
        onset=datetime(2026, 10, 25, 2, 0, tzinfo=UTC),
        expires=datetime(2026, 10, 26, 13, 0, tzinfo=UTC),
        headline="Freeze Warning",
    )
    assert frost_alerts(nights, [LEMON], today=date(2026, 10, 20)).alerts == ()
    stretched = frost_alerts(
        nights, [LEMON], advisories=[late], today=date(2026, 10, 20)
    )
    assert stretched.alerts and stretched.alerts[0].night_of == date(2026, 10, 25)


def test_an_alert_never_states_a_low_above_its_own_threshold():
    """The contract test on the API depends on this, so it is asserted here too."""
    report = frost_alerts(
        NIGHTS, [LEMON, BASIL, ROSE], advisories=[ADVISORY], today=date(2026, 10, 20)
    )
    for alert in report.alerts:
        assert alert.forecast_low_c <= alert.threshold_c


def test_an_uncited_minimum_temperature_degrades_the_alert():
    """The threshold is only as good as the number it is measured against."""
    vague = FrostSubject(
        specimen_id="vague",
        is_outdoor=True,
        in_container=True,
        min_temp_c=2.0,
        min_temp_confidence="unknown",
    )
    alert = frost_alerts(NIGHTS, [vague], today=date(2026, 10, 20)).alerts[0]
    assert alert.assessment.confidence == "low"
    assert {d.code for d in alert.assessment.degradations} == {"min_temp_uncited"}


def test_return_outdoors_needs_three_mild_nights_after_the_last_frost():
    threshold = frost_threshold_c(2.0)
    assert return_outdoors_day(NIGHTS, threshold) == date(2026, 10, 27)


def test_return_outdoors_does_not_count_mild_nights_before_the_freeze():
    """Otherwise a lemon goes back out the evening before the hard night."""
    threshold = frost_threshold_c(2.0)
    nights = [
        FrostNight(day=date(2026, 10, 20), low_c=14.0),
        FrostNight(day=date(2026, 10, 21), low_c=13.0),
        FrostNight(day=date(2026, 10, 22), low_c=12.0),
        FrostNight(day=date(2026, 10, 23), low_c=-2.0),
    ]
    assert return_outdoors_day(nights, threshold) is None


def test_return_outdoors_resets_when_a_cold_night_interrupts_the_run():
    threshold = frost_threshold_c(2.0)
    nights = [
        FrostNight(day=date(2026, 10, 20), low_c=-2.0),
        FrostNight(day=date(2026, 10, 21), low_c=8.0),
        FrostNight(day=date(2026, 10, 22), low_c=8.0),
        FrostNight(day=date(2026, 10, 23), low_c=1.0),
        FrostNight(day=date(2026, 10, 24), low_c=8.0),
        FrostNight(day=date(2026, 10, 25), low_c=8.0),
        FrostNight(day=date(2026, 10, 26), low_c=8.0),
    ]
    assert return_outdoors_day(nights, threshold) == date(2026, 10, 26)


def test_a_plant_that_was_never_at_risk_is_never_invited_back_out():
    assert return_outdoors_day(NIGHTS, frost_threshold_c(-29.0)) is None


def test_no_forecast_at_all_produces_no_alerts_and_no_claims():
    report = frost_alerts([], [LEMON, UNKNOWN_SPECIES])
    assert report.alerts == () and report.unassessable == ()


def test_an_alert_serialises_with_its_confidence():
    alert = frost_alerts(
        NIGHTS, [LEMON], advisories=[ADVISORY], today=date(2026, 10, 20)
    ).alerts[0]
    payload = alert.to_dict()
    assert payload["night_of"] == "2026-10-23"
    assert payload["forecast_low_c"] == -2.0
    assert payload["action"] == "bring_indoors"
    assert payload["confidence"] == "high"
    assert payload["degraded"] is False
