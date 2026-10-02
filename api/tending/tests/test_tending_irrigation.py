"""The irrigation term: the design, both halves, and the marks on the model.

§1 is in ``test_tending_domain.py``, where the scheduling engine is tested — a
watering somebody did settles the task, and that needs no arithmetic at all.

This module is §2: the deficit relief, which is modelled, and the marks that
say so. The arithmetic itself belongs to the weather engine and is tested in
``workers/weather/tests/``; what is tested here is the conversion this package
owns, the degradation it ships with, and the fact that the degradation's
ceiling actually lands on the answer instead of being a warning nobody applied.
"""

from __future__ import annotations

from datetime import date

from tending.domain import Caveat
from tending.environment import (
    AVAILABLE_WATER_FRACTION,
    IRRIGATION_UNCITED,
    Waterings,
    _irrigation_series,
    from_water_balance,
    irrigation_mm,
)

#: A 25 litre pot, which is what the fixtures give the lemon on the porch.
POT_LITRES = 25.0
CAPACITY_MM = 21.75
#: What the design calls ``refill_ml``: the volume that relieves the whole buffer.
REFILL_ML = POT_LITRES * 1000.0 * AVAILABLE_WATER_FRACTION


def balance(**overrides: object) -> dict:
    payload: dict = {
        "capacity_mm": CAPACITY_MM,
        "confidence": "medium",
        "degradations": [],
        "days": [
            {"day": "2026-05-29", "deficit_mm": 20.0},
            {"day": "2026-05-30", "deficit_mm": 21.75},
        ],
        "applies": True,
        "status": "due",
        "is_due": True,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- the conversion


def test_a_watering_that_would_refill_the_buffer_relieves_the_buffer():
    """the design equation, at both ends of its range."""
    whole = irrigation_mm(
        REFILL_ML, capacity_mm=CAPACITY_MM, container_litres=POT_LITRES
    )
    assert whole == CAPACITY_MM

    half = irrigation_mm(
        REFILL_ML / 2, capacity_mm=CAPACITY_MM, container_litres=POT_LITRES
    )
    assert half is not None and abs(half - CAPACITY_MM / 2) < 1e-9


def test_over_watering_is_not_credited_beyond_the_buffer():
    """The water that leaves the drainage holes was never available.

    This function is allowed to return more than the buffer — the clamp lives
    in ``step_deficit``, where the deficit cannot go below zero — but the
    *bound* has to be in the right direction, so a reader can trust that
    over-watering never buys credit for a future dry spell.
    """
    lots = irrigation_mm(
        REFILL_ML * 10, capacity_mm=CAPACITY_MM, container_litres=POT_LITRES
    )
    assert lots is not None and lots > CAPACITY_MM


def test_an_open_ground_plant_gets_no_conversion_rather_than_a_guessed_one():
    """No container, no ``refill_ml``, no defensible number. The no-invented-plant-facts rule."""
    assert (
        irrigation_mm(5000.0, capacity_mm=60.0, container_litres=None) is None
    ), "a plant in the ground was given an invented pot volume"
    assert irrigation_mm(5000.0, capacity_mm=60.0, container_litres=0.0) is None


# ------------------------------------------------- what the degradation says


def test_a_modelled_irrigation_term_is_marked_and_capped_at_unknown():
    logged = Waterings(by_day={date(2026, 5, 30): 500.0}, container_litres=POT_LITRES)
    applied, caveats = _irrigation_series(logged, balance())

    assert applied, "a watering with a pot and a volume must reach the engine"
    assert [caveat.code for caveat in caveats] == [IRRIGATION_UNCITED]
    assert caveats[0].caps_at == "unknown"
    detail = caveats[0].detail
    assert detail.strip() and detail[0].isupper() and detail.endswith(".")
    # nothing measures the soil, so nothing may imply it did.
    assert "not a measurement" in detail
    assert "nothing here has measured the soil" in detail.lower()


def test_the_amount_is_converted_on_the_day_it_was_poured():
    logged = Waterings(by_day={date(2026, 5, 30): 500.0}, container_litres=POT_LITRES)
    applied, _ = _irrigation_series(logged, balance())

    expected = CAPACITY_MM * (500.0 / REFILL_ML)
    assert set(applied) == {date(2026, 5, 30)}
    assert abs(applied[date(2026, 5, 30)] - expected) < 1e-9


def test_two_waterings_on_one_day_are_one_day_of_relief():
    logged = Waterings(
        by_day={date(2026, 5, 29): 250.0, date(2026, 5, 30): 250.0},
        container_litres=POT_LITRES,
    )
    applied, _ = _irrigation_series(logged, balance())
    assert set(applied) == {date(2026, 5, 29), date(2026, 5, 30)}


def test_a_watering_after_the_records_end_is_counted_on_the_last_day_and_says_so():
    """The replay's last deficit is what the app calls "now"."""
    logged = Waterings(by_day={date(2026, 9, 30): 500.0}, container_litres=POT_LITRES)
    applied, caveats = _irrigation_series(logged, balance())

    assert set(applied) == {date(2026, 5, 30)}, "the relief was dropped in silence"
    assert "after the last day the weather records reach" in caveats[0].detail


def test_an_open_ground_watering_omits_the_term_and_names_the_omission():
    logged = Waterings(by_day={date(2026, 5, 30): 5000.0}, container_litres=None)
    applied, caveats = _irrigation_series(logged, balance(capacity_mm=60.0))

    assert applied == {}, "an open-ground plant was given a guessed conversion"
    assert [caveat.code for caveat in caveats] == [IRRIGATION_UNCITED]
    assert caveats[0].caps_at == "unknown"
    assert "not in a container" in caveats[0].detail
    assert "drier than the plant is" in caveats[0].detail


def test_a_watering_with_no_volume_logged_says_it_could_not_be_counted():
    logged = Waterings(by_day={date(2026, 5, 30): 0.0}, container_litres=POT_LITRES)
    applied, caveats = _irrigation_series(logged, balance())

    assert applied == {}
    assert "without saying how much" in caveats[0].detail


# --------------------------------------------------------------- the ceiling


def test_the_added_caveat_lowers_the_ceiling_it_claims_to():
    """``caps_at`` is a ceiling, and a ceiling has to be applied.

    E folds its own degradations into the ``confidence`` it reports, so a
    caveat this package adds afterwards would otherwise be a warning printed
    beside an answer that never took any notice of it.
    """
    environment = from_water_balance(
        balance(confidence="medium"),
        added=(Caveat(code=IRRIGATION_UNCITED, detail="x", caps_at="unknown"),),
    )
    assert environment.confidence == "unknown"


def test_es_own_degradations_survive_beside_the_added_one():
    payload = balance(
        confidence="low",
        degradations=[{"code": "et0_fallback", "detail": "d", "caps_at": "low"}],
    )
    environment = from_water_balance(
        payload,
        added=(Caveat(code=IRRIGATION_UNCITED, detail="x", caps_at="unknown"),),
    )
    codes = [caveat.code for caveat in environment.degradations]
    assert codes == ["et0_fallback", IRRIGATION_UNCITED]
    assert environment.confidence == "unknown"


def test_a_ceiling_never_flatters_a_worse_answer():
    """``caps_at`` is a ceiling, not an assignment."""
    environment = from_water_balance(
        balance(confidence="unknown"),
        added=(Caveat(code=IRRIGATION_UNCITED, detail="x", caps_at="medium"),),
    )
    assert environment.confidence == "unknown"


def test_an_unwatered_plant_carries_no_irrigation_caveat_at_all():
    """The mark rides on the term. No watering, no term, nothing to mark."""
    environment = from_water_balance(balance())
    assert [caveat.code for caveat in environment.degradations] == []
    assert environment.confidence == "medium"


# ---------------------------------------------------- through the whole app


def test_a_logged_watering_reaches_the_deficit_and_the_task_says_it_is_modelled(
    client,
):
    """The seam, end to end over HTTP: the design as a person meets it.

    Asked for on the day *after* the watering, because §1 settles the task on
    the day of it — so a task that appears here at all is one the model built
    with the irrigation term in the deficit, and it has to say so.
    """
    from datetime import timedelta

    lemon = "01890040-0000-7000-8000-000000000005"
    keeper = "01890050-0000-7000-8000-000000000001"
    today = date.today()

    rounds = client.get(
        "/api/v1/tending/rounds", params={"on": today.isoformat()}
    ).json()
    task = next(
        row
        for row in rounds["due"]
        if row["specimen"]["id"] == lemon and row["task_type"] == "water"
    )
    assert task["confidence"] != "unknown", "nothing to prove if it started here"

    completed = client.post(
        f"/api/v1/tending/tasks/{task['id']}/complete",
        json={"completed_by": keeper, "amount_ml": 500},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"

    tomorrow = (today + timedelta(days=1)).isoformat()
    after = client.get("/api/v1/tending/rounds", params={"on": tomorrow}).json()
    next_task = next(
        row
        for row in after["due"]
        if row["specimen"]["id"] == lemon and row["task_type"] == "water"
    )
    assert next_task["confidence"] == "unknown"
    assert next_task["degraded"] is True
    assert IRRIGATION_UNCITED in {row["code"] for row in next_task["degradations"]}
