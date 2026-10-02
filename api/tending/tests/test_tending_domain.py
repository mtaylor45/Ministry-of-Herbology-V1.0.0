"""The scheduling engine, on dates that are not today.

The whole point of ``tending.domain`` taking its clock as an argument is that
winter, dormancy and a four-month-old water balance can be tested in September.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tending.defaults import Attested, default_rules, derived_rule_id, water_rule
from tending.domain import (
    SUSPENDED,
    Caveat,
    Environment,
    Occurrence,
    Rule,
    Subject,
    anchor_for,
    effective_interval,
    generate,
    ics_uid,
    occurrence_dates,
    resolve_rules,
    season_for,
    task_id,
    task_row,
    water_amount_ml,
)

INDIANAPOLIS = 39.7684
MELBOURNE = -37.8136
TODAY = date(2026, 9, 24)


def plant(**overrides: object) -> Subject:
    base: dict[str, object] = {
        "specimen_id": "01890040-0000-7000-8000-000000000001",
        "display_name": "Gilderoy",
        "has_nickname": True,
        "is_outdoor": False,
        "in_container": True,
        "container_litres": 18.0,
        "acquired_on": date(2024, 3, 14),
    }
    base.update(overrides)
    return Subject(**base)  # type: ignore[arg-type]


def interval_rule(**overrides: object) -> Rule:
    base: dict[str, object] = {
        "id": "rule-1",
        "task_type": "water",
        "strategy": "interval",
        "base_interval_days": 10,
    }
    base.update(overrides)
    return Rule(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------- seasons


@pytest.mark.parametrize(
    ("month", "north", "south"),
    [(1, "winter", "summer"), (4, "spring", "autumn"), (7, "summer", "winter")],
)
def test_the_season_is_the_sites_season_not_the_servers(month, north, south):
    """A southern deployment on a northern calendar dials care back in spring."""
    day = date(2026, month, 15)
    assert season_for(day, INDIANAPOLIS) == north
    assert season_for(day, MELBOURNE) == south


# ------------------------------------------------------------------- modifiers


def test_a_season_modifier_stretches_the_interval():
    rule = interval_rule(modifiers={"season": {"winter": 1.6}})
    assert effective_interval(rule, season="summer", dormant=False) == 10
    assert effective_interval(rule, season="winter", dormant=False) == 16


def test_dormancy_suspends_watering_rather_than_stretching_it():
    """The brief is explicit, and the difference is a watering in January."""
    rule = interval_rule(modifiers={"dormancy": "suspend", "season": {"winter": 1.6}})
    assert effective_interval(rule, season="winter", dormant=True) is SUSPENDED
    assert effective_interval(rule, season="winter", dormant=False) == 16


def test_a_numeric_dormancy_modifier_stretches_instead():
    rule = interval_rule(modifiers={"dormancy": 2})
    assert effective_interval(rule, season="winter", dormant=True) == 20


def test_an_unconfigured_modifier_is_never_invented():
    """The no-invented-plant-facts rule: a multiplier nobody wrote down is a plant fact nobody
    attested."""
    rule = interval_rule(modifiers={})
    for season in ("winter", "spring", "summer", "autumn"):
        assert effective_interval(rule, season=season, dormant=True) == 10


def test_a_nonsense_modifier_is_ignored_rather_than_applied():
    rule = interval_rule(modifiers={"season": {"winter": "a lot"}})
    assert effective_interval(rule, season="winter", dormant=False) == 10


def test_the_humidity_modifier_applies_only_below_its_threshold():
    rule = interval_rule(modifiers={"humidity_low": 0.8, "humidity_low_below_pct": 40})
    assert (
        effective_interval(rule, season="summer", dormant=False, humidity_pct=30) == 8
    )
    assert (
        effective_interval(rule, season="summer", dormant=False, humidity_pct=55) == 10
    )
    # No reading at all is not a dry room.
    assert effective_interval(rule, season="summer", dormant=False) == 10


def test_a_rule_with_no_interval_schedules_nothing():
    rule = interval_rule(base_interval_days=None)
    assert effective_interval(rule, season="summer", dormant=False) is None


# -------------------------------------------------------------------- identity


def test_the_task_id_does_not_move_when_the_due_date_does():
    """The reason this package exists in this shape. A stretched winter watering
    is the same occurrence on a later day, and must update the calendar event
    rather than add one."""
    rule = interval_rule()
    anchor = date(2026, 9, 1)
    assert task_id("plant", rule, anchor, 3) == task_id("plant", rule, anchor, 3)


def test_two_occurrences_of_one_rule_are_different_tasks():
    rule = interval_rule()
    anchor = date(2026, 9, 1)
    assert task_id("plant", rule, anchor, 3) != task_id("plant", rule, anchor, 4)


def test_completion_starts_a_new_cycle_with_new_identities():
    rule = interval_rule()
    before = task_id("plant", rule, date(2026, 9, 1), 1)
    after = task_id("plant", rule, date(2026, 9, 20), 1)
    assert before != after


def test_the_ics_uid_is_the_tasks_and_is_prefixed():
    assert ics_uid("abc").startswith("task-abc@")


def test_the_anchor_is_the_last_time_the_job_was_done():
    subject = plant()
    assert anchor_for(subject, date(2026, 9, 1)) == date(2026, 9, 1)
    assert anchor_for(subject, None) == subject.acquired_on
    assert anchor_for(plant(acquired_on=None), None).year == 2024


# ----------------------------------------------------------------- occurrences


def test_only_the_most_recent_missed_occurrence_is_materialised():
    """A plant acquired in 2022 is one watering behind, not eighty."""
    dates = occurrence_dates(
        date(2022, 11, 2), 21, today=TODAY, until=date(2026, 10, 24)
    )
    past = [day for _, day in dates if day <= TODAY]
    assert len(past) == 1
    assert past[0] > TODAY.replace(month=8)


def test_an_anchor_years_old_still_reaches_this_week():
    """The cap on how many cycles are *emitted* may not cap the search.

    Counting up from cycle one spent the limit in 2022 and served a plant one
    watering dated four years ago and none in the future. Nothing in the fixtures
    reaches this path — every plant on an interval there has a recent anchor —
    until a plant moves indoors and swaps the water balance for an interval,
    which is what an earlier release made possible.
    """
    dates = occurrence_dates(
        date(2022, 1, 1), 2, today=TODAY, until=TODAY + timedelta(days=30)
    )
    past = [day for _, day in dates if day <= TODAY]
    assert len(past) == 1
    assert (TODAY - past[0]).days < 2, past
    assert [day for _, day in dates if day > TODAY], "and the calendar is filled"


def test_a_month_restriction_skips_without_renumbering():
    """Renumbering would shift every later identity and duplicate every event."""
    unrestricted = occurrence_dates(
        date(2026, 1, 1), 30, today=date(2026, 1, 1), until=date(2026, 12, 31)
    )
    restricted = occurrence_dates(
        date(2026, 1, 1),
        30,
        today=date(2026, 1, 1),
        until=date(2026, 12, 31),
        months=(4, 5, 6),
    )
    assert restricted == [pair for pair in unrestricted if pair[1].month in (4, 5, 6)]
    assert restricted and [index for index, _ in restricted] != list(
        range(1, len(restricted) + 1)
    )


def test_generation_is_idempotent():
    subject = plant()
    rules = [interval_rule()]
    args = {"today": TODAY, "horizon_days": 30, "latitude": INDIANAPOLIS}
    first = [o.task_id for o in generate(subject, rules, **args)]
    second = [o.task_id for o in generate(subject, rules, **args)]
    assert first == second and first


def test_a_dormant_plant_is_scheduled_for_nothing():
    subject = plant(dormancy_months=(12, 1, 2))
    rule = interval_rule(modifiers={"dormancy": "suspend"})
    assert (
        generate(
            subject,
            [rule],
            today=date(2026, 1, 10),
            horizon_days=30,
            latitude=INDIANAPOLIS,
        )
        == []
    )


# ------------------------------------------------------- the water balance seam


def _outdoor() -> Subject:
    return plant(specimen_id="outdoor-1", display_name="Sour Bertram", is_outdoor=True)


def test_a_due_water_balance_produces_one_task_not_a_series():
    """Projecting the next crossing is the weather engine's engine and an earlier release's job."""
    occurrences = generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={
            "water": Environment(
                applies=True,
                balance_status="due",
                is_due=True,
                confidence="medium",
                newest_day=TODAY,
            )
        },
    )
    assert len(occurrences) == 1
    assert occurrences[0].due_on == TODAY


def test_a_watering_done_today_settles_the_task_whatever_the_model_says():
    """the design. The fact beats the model, and it beats it on its own.

    This is the duplicate-VEVENT bug in one function. The balance still says
    ``due`` — it is allowed to, the relief is modelled separately and may not be
    modellable at all — but somebody has watered the plant today, and completion
    moves the anchor, and the anchor is half the identity. Regenerating here
    mints a *second* outstanding watering under an id nobody has seen, so the
    plant goes straight back on the round and a new event into every subscribed
    calendar.
    """
    still_thirsty = Environment(
        applies=True,
        balance_status="due",
        is_due=True,
        confidence="medium",
        newest_day=TODAY,
    )
    assert (
        generate(
            _outdoor(),
            [interval_rule(strategy="water_balance")],
            today=TODAY,
            horizon_days=30,
            latitude=INDIANAPOLIS,
            environments={"water": still_thirsty},
            last_completed={"water": TODAY},
        )
        == []
    )
    # Yesterday's watering settles yesterday, not today: a deficit that is still
    # over threshold a day later is a question the model is entitled to ask
    # again, and suppressing it would be this package overruling the engine.
    assert generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={"water": still_thirsty},
        last_completed={"water": TODAY - timedelta(days=1)},
    )


def test_a_watering_done_today_settles_it_without_claiming_the_weather_did():
    """``done`` is not ``satisfied``: a person with a can is not the sky.

    the design again, from the other side. Suppressing the occurrence must not
    be mistaken for the weather engine deciding the weather settled the plant — nothing is
    emitted at all, so nothing can carry a ``satisfied_by``.
    """
    occurrences = generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={
            "water": Environment(
                applies=True,
                balance_status="satisfied",
                satisfied_by="irrigation",
                confidence="medium",
                newest_day=TODAY,
            )
        },
        last_completed={"water": TODAY},
    )
    assert occurrences == []


def test_a_comfortable_plant_gets_no_interval_watering_behind_the_models_back():
    """Two authorities on one plant is one authority too many."""
    assert (
        generate(
            _outdoor(),
            [interval_rule(strategy="water_balance")],
            today=TODAY,
            horizon_days=30,
            latitude=INDIANAPOLIS,
            environments={
                "water": Environment(
                    applies=True, balance_status="ok", newest_day=TODAY
                )
            },
        )
        == []
    )


def test_the_interval_takes_over_when_the_model_has_no_opinion():
    occurrences = generate(
        plant(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={"water": Environment(applies=False)},
    )
    assert occurrences


def test_rain_satisfied_is_carried_through_rather_than_hidden():
    occurrences = generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={
            "water": Environment(
                applies=True,
                balance_status="satisfied",
                satisfied_by="rain",
                confidence="medium",
                newest_day=TODAY,
            )
        },
    )
    assert [(o.status, o.satisfied_by) for o in occurrences] == [("satisfied", "rain")]


def test_es_degradations_arrive_on_the_task_unchanged():
    """a task built on a degraded input must not look like a clean one."""
    caveat = Caveat(code="et0_missing", detail="No ET0 for three days.", caps_at="low")
    occurrences = generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={
            "water": Environment(
                applies=True,
                balance_status="due",
                is_due=True,
                confidence="low",
                degradations=(caveat,),
                newest_day=TODAY,
            )
        },
    )
    row = task_row(occurrences[0])
    assert row["confidence"] == "low"
    assert row["degraded"] is True
    assert row["degradations"][0]["code"] == "et0_missing"
    assert "No ET0" in row["detail"]


def test_a_balance_that_stops_short_of_today_says_so():
    """A series ending in May cannot confidently schedule September."""
    occurrences = generate(
        _outdoor(),
        [interval_rule(strategy="water_balance")],
        today=TODAY,
        horizon_days=30,
        latitude=INDIANAPOLIS,
        environments={
            "water": Environment(
                applies=True,
                balance_status="due",
                is_due=True,
                confidence="high",
                newest_day=date(2026, 5, 30),
            )
        },
    )
    row = task_row(occurrences[0])
    assert row["confidence"] == "low"
    assert any(d["code"] == "balance_not_current" for d in row["degradations"])


# ----------------------------------------------------------------- the original-theme rule / 6


def test_every_generated_task_carries_both_titles():
    for occurrence in generate(
        plant(), [interval_rule()], today=TODAY, horizon_days=30, latitude=INDIANAPOLIS
    ):
        row = task_row(occurrence)
        assert row["title"] and row["plain_title"]
        assert row["title"] != row["plain_title"]


def test_a_specimen_rule_beats_a_species_rule_for_the_same_job():
    species_rule = interval_rule(id="species", species_id="s1", base_interval_days=30)
    own = interval_rule(id="own", specimen_id="p1", base_interval_days=5)
    assert [r.id for r in resolve_rules([species_rule, own])] == ["own"]
    assert [r.id for r in resolve_rules([own, species_rule])] == ["own"]


def test_a_disabled_rule_is_not_resolved():
    assert resolve_rules([interval_rule(enabled=False)]) == []


def test_an_uncited_interval_is_used_and_marked_rather_than_discarded():
    """the design says mark it, which is a different instruction from throw it away."""
    subject = plant()
    rules, reasons = default_rules(subject, [], fallback_interval=9)
    assert not reasons
    assert rules[0].interval_confidence == "unknown"
    assert rules[0].interval_caveats[0].code == "interval_uncited"
    row = task_row(
        generate(subject, rules, today=TODAY, horizon_days=30, latitude=INDIANAPOLIS)[0]
    )
    assert row["confidence"] == "unknown"
    assert "no citation" in (row["detail"] or "")


def test_a_cited_interval_keeps_its_citations_confidence():
    rules, reasons = default_rules(
        plant(),
        [
            {
                "field": "water_interval_days",
                "value": 9,
                "confidence": "medium",
                "source_id": "src-1",
            }
        ],
    )
    assert not reasons
    assert rules[0].interval_confidence == "medium"
    assert rules[0].interval_caveats == ()


def test_no_interval_anywhere_means_no_rule_and_a_stated_reason():
    """Named, never silently dropped."""
    rules, reasons = default_rules(plant(), [], fallback_interval=None)
    assert rules == []
    assert reasons and "No watering interval" in reasons[0]


def test_an_outdoor_plant_still_gets_a_rule_with_no_interval():
    """The water balance is its authority; the interval is only the fallback."""
    rule, reason = water_rule(_outdoor(), None)
    assert reason is None
    assert rule is not None and rule.strategy == "water_balance"


def test_a_derived_rule_keeps_its_id_across_restarts():
    assert derived_rule_id("p1", "water") == derived_rule_id("p1", "water")


def test_the_watering_amount_comes_from_the_pot_not_from_the_plant():
    """A fact about a container needs no citation; one about a species does."""
    assert water_amount_ml(plant(container_litres=18)) == 450
    assert water_amount_ml(plant(in_container=False, container_litres=None)) is None
    assert water_amount_ml(plant(container_litres=1000)) == 2000


def test_an_attested_value_knows_whether_it_is_cited():
    assert Attested(9, "medium", "src").is_cited
    assert not Attested(9, "unknown", None).is_cited


def test_a_timed_task_is_not_an_all_day_event():
    occurrence = Occurrence(
        rule=interval_rule(task_type="bring_indoors"),
        subject=plant(),
        index=1,
        anchor=date(2026, 9, 1),
        due_on=TODAY,
    )
    row = task_row(occurrence)
    assert row["all_day"] is False
    assert row["priority"] == "urgent"
    assert row["due_at"] == datetime(2026, 9, 24, 9, tzinfo=UTC)
