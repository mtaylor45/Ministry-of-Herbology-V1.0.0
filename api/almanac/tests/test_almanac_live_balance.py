"""The database-backed water balance answers with the same doubt — the design.

The design decision's complaint, in one sentence: *the live path is quieter about its own
uncertainty than the mock.* The mock runs the engine and knows why it is
unsure; production read a deficit out of a table that stored none of it and
reported a flat ``medium``.

With ``confidence``, ``degraded`` and ``degradations`` now written (see
``workers/weather/tests/test_balance_certainty_store``), this is the read that
has to hand them back. No database: ``balance_from_rows`` is pure and takes
rows, for the same reason every statement in ``workers/weather/store.py`` is
built by a pure function.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

from almanac.service import balance_from_rows, live_water_balance

SPECIMEN = "01890040-0000-7000-8000-000000000004"
TODAY = date(2026, 7, 7)

CATEGORY_DEFAULT = {
    "code": "k_c_category_default",
    "detail": "The water coefficient is a published default for the tree category.",
    "caps_at": "medium",
}


def row(
    day: date,
    deficit: float,
    *,
    precip: float = 0.0,
    confidence: str | None = "medium",
    degradations: list[dict[str, str]] | None = None,
    threshold: float = 19.68,
    irrigation: float = 0.0,
    override: float | None = None,
) -> dict[str, object]:
    """One ``water_balance`` row as ``water_balance_history_sql`` selects it."""
    return {
        "day": day,
        "deficit_mm": deficit,
        "capacity_mm": 32.8,
        "threshold_mm": threshold,
        "et0_mm": 4.5,
        "k_c": 0.9,
        "precip_mm": precip,
        "irrigation_mm": irrigation,
        "cover_factor": 1.0,
        "sensor_override_pct": override,
        "confidence": confidence,
        "degraded": bool(degradations),
        # asyncpg hands a jsonb column back as text unless a codec is set.
        "degradations": json.dumps(degradations or []),
    }


def test_the_recorded_reasons_come_back_out_verbatim():
    """Not recomputed, not summarised — the caveat the reader saw is the record."""
    payload = balance_from_rows(
        SPECIMEN,
        [row(TODAY, 27.0, confidence="medium", degradations=[CATEGORY_DEFAULT])],
        today=TODAY,
    )
    assert payload is not None
    assert payload["confidence"] == "medium"
    assert payload["degraded"] is True
    assert payload["degradations"] == [CATEGORY_DEFAULT]


def test_a_row_that_never_said_reads_as_unknown_not_as_medium():
    """an empty column means "it did not say", never "it was certain".

    A row written before migration 004, or by a worker that skipped the
    columns, is the case this guards. Reading it as ``medium`` is the exact
    laundering the design was written to stop, one table further down.
    """
    payload = balance_from_rows(
        SPECIMEN, [row(TODAY, 27.0, confidence=None)], today=TODAY
    )
    assert payload is not None
    assert payload["confidence"] == "unknown"
    assert payload["degraded"] is True
    assert [entry["code"] for entry in payload["degradations"]] == [
        "certainty_not_recorded"
    ]


def test_a_stale_row_says_the_deficit_stopped_advancing():
    """Under the design nothing else would ever notice that it had."""
    payload = balance_from_rows(SPECIMEN, [row(date(2026, 7, 4), 27.0)], today=TODAY)
    assert payload is not None
    reasons = {entry["code"]: entry for entry in payload["degradations"]}
    assert "ingest_stale" in reasons
    assert "72 hours old" in reasons["ingest_stale"]["detail"]
    assert payload["confidence"] == "low"


def test_a_current_undegraded_row_keeps_what_it_was_worth():
    payload = balance_from_rows(SPECIMEN, [row(TODAY, 27.0)], today=TODAY)
    assert payload is not None
    assert payload == payload | {"confidence": "medium", "degraded": False}
    assert payload["degradations"] == []


# ------------------------------------------------- what the table cannot store


def test_rain_that_cleared_a_watering_survives_the_round_trip():
    """``water_balance`` has no ``status`` column, so it is replayed, not read.

    Two consecutive rows are enough: the plant owed a watering yesterday, rain
    reached the soil, and it does not owe one now. That is ``satisfied``, and
    the plan is explicit that it must stay visible rather than vanish.
    """
    payload = balance_from_rows(
        SPECIMEN,
        [
            row(date(2026, 7, 6), 27.0),
            row(TODAY, 0.0, precip=38.0),
        ],
        today=TODAY,
    )
    assert payload is not None
    assert payload["status"] == "satisfied"
    assert payload["satisfied_by"] == "rain"
    assert [day["status"] for day in payload["days"]] == ["due", "satisfied"]


def test_a_watering_logged_by_hand_is_attributed_to_the_person():
    payload = balance_from_rows(
        SPECIMEN,
        [row(date(2026, 7, 6), 27.0), row(TODAY, 0.0, irrigation=30.0)],
        today=TODAY,
    )
    assert payload is not None
    assert (payload["status"], payload["satisfied_by"]) == ("satisfied", "irrigation")


def test_the_unrecorded_parts_of_a_day_are_left_out_rather_than_invented():
    """``et0_method`` is not stored, and a ``hargreaves`` nobody wrote down is a
    fact about provenance invented on the way out. None of these is required by
    the contract; columns for them are the maintainers' call and are raised in the PR.
    """
    payload = balance_from_rows(SPECIMEN, [row(TODAY, 27.0)], today=TODAY)
    assert payload is not None
    day = payload["days"][0]
    for absent in ("et0_method", "reference_et0_mm", "gross_precip_mm", "is_forecast"):
        assert absent not in day


def test_a_probe_outranks_the_model_here_as_everywhere():
    """No hardware drives this today; the seam stays exercised."""
    payload = balance_from_rows(SPECIMEN, [row(TODAY, 2.0, override=12.0)], today=TODAY)
    assert payload is not None
    assert payload["is_due"] is True and payload["sensor_override_pct"] == 12.0


def test_an_indoor_specimen_is_told_this_engine_does_not_apply_to_it():
    payload = balance_from_rows(
        SPECIMEN, [row(TODAY, 27.0)], is_outdoor=False, today=TODAY
    )
    assert payload is not None
    assert payload["applies"] is False
    assert "interval rule" in payload["note"]


def test_a_specimen_with_no_stored_rows_is_none_not_a_zero_deficit():
    """A plant nothing has computed for is not a plant that needs nothing."""
    assert balance_from_rows(SPECIMEN, [], today=TODAY) is None


# ------------------------------------------------------------ the async wrapper


class _Connection:
    """The slice of an asyncpg connection the read uses."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.calls.append((sql, args))
        return self.rows


def test_the_live_read_asks_for_the_window_the_endpoint_publishes():
    """Deliberately not ``pytest-asyncio``: there is no root pytest config, so
    ``asyncio_mode`` is whatever the caller's rootdir happens to say, and a
    suite should not depend on where it was invoked from."""
    connection = _Connection([row(TODAY, 27.0)])
    payload = asyncio.run(live_water_balance(connection, SPECIMEN, today=TODAY))

    assert payload is not None and payload["confidence"] == "medium"
    sql, args = connection.calls[0]
    assert "FROM water_balance" in sql
    assert args == (SPECIMEN, date(2026, 6, 24)), "14 days, ending today"


def test_a_stored_high_is_still_only_a_model_s_opinion():
    """nothing measures the soil, so nothing here earns ``high``.

    The engine applies this ceiling before it writes. This is for the row it
    did not write — a hand-edited one, or one from a future writer that forgot.
    """
    payload = balance_from_rows(
        SPECIMEN, [row(TODAY, 27.0, confidence="high")], today=TODAY
    )
    assert payload is not None
    assert payload["confidence"] == "medium"


# ------------------------------------------------- the two paths, side by side


def test_the_stored_row_reads_back_with_the_certainty_the_mock_serves():
    """§4 in one assertion: the live path is no longer the quieter one.

    The engine is run the way a deployment runs it — once a day, over the days
    up to that day. Each run's answer is serialised the way the fixture-backed
    endpoint serves it *and* written the way the worker writes it, then read
    back the way a Postgres deployment reads it. The certainty has to match.

    The coefficient here is uncited on purpose: an undegraded row
    would pass this test by having nothing to lose on the way through.
    """
    from workers.weather.store import water_balance_row
    from workers.weather.tasks import DayWeather, WaterCoefficient, run_balance

    from almanac.service import serialise_balance

    weather = [
        DayWeather(day=date(2026, 7, 4), precip_mm=0.0, et0_mm=5.0),
        DayWeather(day=date(2026, 7, 5), precip_mm=0.0, et0_mm=5.0),
        DayWeather(day=date(2026, 7, 6), precip_mm=0.0, et0_mm=5.0),
        DayWeather(day=date(2026, 7, 7), precip_mm=38.0, et0_mm=1.2),
    ]

    def replay(through: int):
        return run_balance(
            weather[:through],
            k_c=WaterCoefficient(value=None, confidence="unknown"),
            capacity=12.4,
            cover_factor=1.0,
            latitude=42.0,
        )

    def stored(through: int) -> dict[str, object]:
        """The row the nightly job would have written on that day."""
        series = replay(through)
        return water_balance_row(
            day=series.days[-1].day,
            specimen_id=SPECIMEN,
            series=series,
            last=series.days[-1],
            cover_factor=1.0,
            sensor_override_pct=None,
        )

    today = replay(len(weather))
    served = serialise_balance(SPECIMEN, today)
    read_back = balance_from_rows(
        SPECIMEN,
        [stored(3), stored(4)],
        today=weather[-1].day,
    )

    assert read_back is not None
    for field in ("confidence", "degraded", "degradations"):
        assert read_back[field] == served[field], field
    assert served["confidence"] == "unknown", "an uncited coefficient"
    assert [entry["code"] for entry in served["degradations"]] == ["k_c_uncited"]

    # And the state, which the table keeps no column for, is recovered too.
    assert (
        (read_back["status"], read_back["satisfied_by"])
        == (served["status"], served["satisfied_by"])
        == ("satisfied", "rain")
    )
    assert read_back["deficit_mm"] == served["deficit_mm"] == 0.0
