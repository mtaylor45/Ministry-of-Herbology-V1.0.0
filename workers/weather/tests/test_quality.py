"""The confidence arithmetic, and the one caveat that must never exist.

the design makes the water balance the sole authority on outdoor watering, so
the reasons an answer might be wrong are part of the answer. These tests hold
the rules that keep that useful rather than noisy.
"""

from workers.weather.quality import (
    CONFIDENCE_ORDER,
    Degradation,
    assess,
    downgrade,
    et0_fallback,
    et0_missing,
    ingest_stale,
    k_c_category_default,
    k_c_uncited,
    weakest,
)


def test_confidence_only_ever_falls():
    assert downgrade("high") == "medium"
    assert downgrade("medium", 2) == "unknown"
    assert downgrade("unknown") == "unknown"
    assert downgrade("high", 0) == "high"
    assert downgrade("high", -3) == "high", "a negative step must not promote"


def test_an_unrecognised_word_is_treated_as_the_worst_case():
    """A confidence the contract does not define is not evidence of anything."""
    assert weakest("high", "excellent") == "unknown"
    assert downgrade("excellent") == "unknown"


def test_a_chain_is_worth_its_weakest_link():
    assert weakest("high", "medium", "low") == "low"
    assert weakest("high", "high") == "high"
    assert weakest() == "unknown"


def test_the_weakest_cap_wins_and_the_reasons_all_survive():
    """Two doubts do not compound into a third, and neither is dropped."""
    result = assess([et0_fallback(2), k_c_uncited()], base="high")
    assert result.confidence == "unknown"
    assert {d.code for d in result.degradations} == {"et0_fallback", "k_c_uncited"}
    assert result.is_degraded


def test_a_ceiling_never_raises_a_lower_base():
    """``caps_at: medium`` on a ``low`` answer leaves it ``low``."""
    result = assess([et0_fallback(1)], base="low")
    assert result.confidence == "low"


def test_nothing_wrong_means_nothing_to_say():
    result = assess([], base="medium")
    assert result.confidence == "medium"
    assert not result.is_degraded
    assert result.to_dict()["degradations"] == []


def test_reasons_are_ordered_worst_first():
    """The UI shows the first one when it has room for one."""
    result = assess([et0_fallback(1), et0_missing(3), ingest_stale(30)])
    codes = [d.code for d in result.degradations]
    assert codes[0] in {"et0_missing", "ingest_stale"}
    assert codes[-1] == "et0_fallback"


def test_a_category_default_is_capped_at_medium_not_high():
    """a published category default is never a measurement."""
    degradation = k_c_category_default("broadleaf evergreen shrub", "FAO-56 table 12")
    assert degradation.caps_at == "medium"
    assert "not a value measured for this species" in degradation.detail
    assert assess([degradation], base="high").confidence == "medium"


def test_an_uncited_coefficient_drags_the_whole_answer_to_unknown():
    """arithmetic on a number nobody attests is still a guess."""
    assert assess([k_c_uncited()], base="high").confidence == "unknown"


def test_staleness_gets_worse_the_longer_it_lasts():
    assert ingest_stale(8).caps_at == "medium"
    assert ingest_stale(24).caps_at == "low"
    assert ingest_stale(72).caps_at == "low"


def test_every_reason_names_a_confidence_the_contract_allows():
    """the design fixes four levels and the database enforces them."""
    reasons = [
        et0_fallback(1),
        et0_missing(1),
        k_c_uncited(),
        k_c_category_default(None, None),
        ingest_stale(2),
    ]
    for reason in reasons:
        assert reason.caps_at in CONFIDENCE_ORDER
        # Each one is rendered to a reader as-is, so it has to be a sentence.
        assert reason.detail.strip().endswith(".")
        assert len(reason.detail.split()) >= 6


def test_a_missing_soil_sensor_is_not_a_degradation():
    """model-only is the shipping path, not a degraded one.

    There is no constructor for it, and there must not be. A caveat that fires
    on every plant on every day is a caveat people stop reading, and the one
    day it says something real they will not notice either.
    """
    from workers.weather import quality

    names = [name for name in dir(quality) if "sensor" in name.lower()]
    assert names == [], f"a sensor caveat has appeared: {names}"

    from workers.weather.tasks import run_balance

    assert "sensor" not in run_balance.__doc__.lower()


def test_a_reason_serialises_with_everything_the_ui_needs():
    payload = Degradation(code="x", detail="Because.", caps_at="low").to_dict()
    assert payload == {"code": "x", "detail": "Because.", "caps_at": "low"}
