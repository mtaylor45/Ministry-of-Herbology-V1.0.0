"""What a stored ``water_balance`` row remembers — the weather engine, the design.

the design put ``confidence``, ``degraded`` and ``degradations`` on the water
balance *response*. Migration 004 gave the table somewhere to keep them and the design assigned the
writing to the weather engine,. Until it was written, a deployment on
Postgres served a deficit stripped of the doubt the fixture-backed one carried:
the live path quieter about its own uncertainty than the mock, which is the
wrong way round and is the same shape as every other bug this project has had.

These tests are about the write. ``api/almanac/tests/test_almanac_live_balance``
is about the read that has to hand it back.
"""

from __future__ import annotations

import json
from datetime import date

from workers.weather.quality import Assessment, Degradation
from workers.weather.store import (
    WATER_BALANCE_COLUMNS,
    upsert_water_balance_sql,
    water_balance_history_sql,
    water_balance_row,
)
from workers.weather.tasks import WaterCoefficient, day_status


class _Series:
    """The slice of ``BalanceSeries`` the row builder reads."""

    def __init__(self, assessment: Assessment) -> None:
        self.deficit_mm = 27.0
        self.capacity_mm = 32.8
        self.threshold_mm = 19.68
        self.k_c = WaterCoefficient(value=0.9, confidence="medium")
        self.assessment = assessment


class _Day:
    demand_mm = 4.5
    precip_mm = 0.0
    irrigation_mm = 0.0


def _row(assessment: Assessment) -> dict[str, object]:
    return water_balance_row(
        day=date(2026, 7, 6),
        specimen_id="spec",
        series=_Series(assessment),
        last=_Day(),
        cover_factor=1.0,
        sensor_override_pct=None,
    )


def test_a_written_row_carries_the_confidence_the_engine_computed():
    reason = Degradation(
        code="k_c_category_default",
        detail="a published default for the fruit-tree category",
        caps_at="medium",
    )
    row = _row(Assessment(confidence="medium", degradations=(reason,)))

    assert row["confidence"] == "medium"
    assert row["degraded"] is True
    assert json.loads(str(row["degradations"])) == [reason.to_dict()]


def test_an_undegraded_row_says_so_rather_than_saying_nothing():
    """``degraded: false`` with an empty list is a claim; a NULL is a shrug."""
    row = _row(Assessment(confidence="medium"))
    assert row["degraded"] is False
    assert json.loads(str(row["degradations"])) == []


def test_the_reasons_are_bound_as_json_not_as_an_array():
    """asyncpg binds a Python list as a Postgres array, which ``jsonb`` refuses.

    The cast is on the placeholder rather than left to inference, so the column
    this lands in is decided here and not by whatever the driver guesses.
    """
    sql, params = upsert_water_balance_sql(_row(Assessment(confidence="low")))
    index = WATER_BALANCE_COLUMNS.index("degradations")
    assert f"${index + 1}::jsonb" in sql
    assert isinstance(params[index], str)


def test_the_upsert_refreshes_the_certainty_of_a_day_recomputed():
    """A day re-run with better inputs must not keep yesterday's caveats."""
    sql, _ = upsert_water_balance_sql(_row(Assessment(confidence="medium")))
    for column in ("confidence", "degraded", "degradations"):
        assert f"{column} = EXCLUDED.{column}" in sql
    assert "ON CONFLICT (specimen_id, day) DO UPDATE" in sql


def test_a_row_without_the_certainty_columns_still_binds():
    """Migration 004 defaults them, and a default reads as "it did not say"."""
    sql, params = upsert_water_balance_sql(
        {"day": date(2026, 6, 1), "specimen_id": "spec", "deficit_mm": 4.0}
    )
    assert "computed_at = now()" in sql
    assert params[WATER_BALANCE_COLUMNS.index("confidence")] is None


def test_the_history_read_selects_what_the_write_stored():
    """A column written and never selected is a column that does not exist."""
    sql, _ = water_balance_history_sql("spec", date(2026, 5, 18))
    for column in ("confidence", "degraded", "degradations"):
        assert column in sql


def test_the_satisfied_rule_is_one_function_both_paths_call():
    """``day_status`` is public so the live read replays it, not a copy of it.

    The table keeps no ``status`` column (raised with the maintainers), so a database-backed
    read has to work it out — and the one place that decides what "satisfied"
    means must stay one place.
    """
    assert day_status(was_due=True, now_due=False, rain_mm=38.0, irrigation_mm=0.0) == (
        "satisfied",
        "rain",
    )
    assert day_status(was_due=True, now_due=False, rain_mm=0.0, irrigation_mm=2.0) == (
        "satisfied",
        "irrigation",
    )
    assert day_status(
        was_due=False, now_due=False, rain_mm=38.0, irrigation_mm=0.0
    ) == (
        "ok",
        None,
    ), "rain on a plant that owed nothing settles nothing"
    assert day_status(was_due=True, now_due=False, rain_mm=0.0, irrigation_mm=0.0) == (
        "ok",
        None,
    ), "a covered plant sees no rain, so nothing satisfied it"


# ------------------------------------------------- the no-invented-plant-facts rule, at the
# coefficient


def test_a_source_id_that_resolves_to_nothing_is_not_a_citation():
    """The no-invented-plant-facts rule. The raw id used to be shown as the citation and read as
    cited.

    Two failures in one: a uuid where a reader expects a title — the defect the design fixed one
    layer out — and a value that kept whatever confidence it
    claimed because ``source`` was not ``None``. Contract 1.4.0 made the
    unsourced state sayable (``CareValue.source`` is nullable, the design), and
    this is what saying it looks like here.
    """
    dangling = WaterCoefficient.from_care_value(
        {"value": 0.9, "confidence": "high", "source_id": "01890000-dead-beef"},
        None,  # no such row in species/sources.json
    )
    assert dangling.source is None
    assert dangling.confidence == "unknown"
    assert [reason.code for reason in dangling.degradations()] == ["k_c_uncited"]


def test_a_resolved_source_is_cited_by_its_title():
    cited = WaterCoefficient.from_care_value(
        {"value": 0.9, "confidence": "high", "source_id": "s1"},
        {"id": "s1", "title": "FAO-56 Table 12", "kind": "publication"},
    )
    assert cited.source == "FAO-56 Table 12"
    assert cited.confidence == "high"
    assert cited.degradations() == []


def test_a_household_override_needs_no_outside_source():
    """The stated exception: somebody attesting to a number is not nobody.

    ``CareValue``'s own description carries it — *a value with no source must
    carry confidence unknown unless it is a user override*.
    """
    override = WaterCoefficient.from_care_value(
        {"value": 0.75, "confidence": "medium", "is_user_override": True}, None
    )
    assert override.confidence == "medium"
