"""Cited care synthesis: what gets published, and what it is worth."""

import pytest

from workers.botany.connectors.base import ConnectorResult, FactRecord, SpeciesRef
from workers.botany.enrichment import ALWAYS_REPORT, CareValue, pick, synthesise
from workers.botany.sources import build_source

FIR = SpeciesRef(accepted_name="Abies balsamea")


def fact(field, value, kind, **kwargs):
    return FactRecord(field=field, value=value, source_kind=kind, **kwargs)


def result(kind, *facts):
    return ConnectorResult(
        kind=kind,
        facts=tuple(facts),
        sources=(build_source(kind, f"https://{kind}.invalid/x", {"stub": kind}),),
    )


def values(enrichment):
    return {cv.field: cv for cv in enrichment.care_values}


# ------------------------------------------------------------------ picking


def test_the_precedence_table_decides_between_two_sources():
    best, confidence = pick(
        "min_temp_c",
        [fact("min_temp_c", -5.0, "wikipedia"), fact("min_temp_c", -41.7, "usda")],
    )
    assert best.source_kind == "usda"
    assert confidence == "high"


def test_a_field_nobody_stated_is_unknown_and_has_no_value():
    assert pick("water_k_c", []) == (None, "unknown")


def test_two_trusted_sources_disagreeing_lowers_confidence_rather_than_averaging():
    _, agreeing = pick(
        "soil_ph_min",
        [fact("soil_ph_min", 5.5, "usda"), fact("soil_ph_min", 5.5, "gbif")],
    )
    _, disagreeing = pick(
        "soil_ph_min",
        [fact("soil_ph_min", 5.5, "usda"), fact("soil_ph_min", 7.0, "gbif")],
    )
    assert agreeing == "high"
    assert disagreeing == "medium"


def test_an_encyclopaedia_disagreeing_does_not_undermine_a_measurement():
    """``choose()`` only counts a contradiction from a source of rank 3 or
    better. Wikidata differing from a USDA measurement is Wikidata being
    wrong, and lowering USDA's confidence for it would be the tail wagging
    the dog — the precedence table exists to settle exactly this."""
    _, confidence = pick(
        "soil_ph_min",
        [fact("soil_ph_min", 5.5, "usda"), fact("soil_ph_min", 7.0, "wikidata")],
    )
    assert confidence == "high"


def test_a_toxicity_claim_outranks_a_denial_whatever_the_table_says():
    """Under-reporting is the dangerous direction."""
    best, confidence = pick(
        "toxic_to_pets",
        [fact("toxic_to_pets", False, "usda"), fact("toxic_to_pets", True, "perenual")],
    )
    assert best.value is True
    assert best.source_kind == "perenual", "the citation must support the claim"
    assert confidence == "low", "and record that the sources disagree"


def test_agreeing_toxicity_sources_are_not_penalised():
    best, confidence = pick(
        "toxic_to_pets",
        [fact("toxic_to_pets", True, "usda"), fact("toxic_to_pets", True, "perenual")],
    )
    assert best.value is True
    assert confidence == "high"


def test_the_safety_rule_does_not_leak_into_other_fields():
    best, _ = pick(
        "soil_ph_min",
        [fact("soil_ph_min", 0, "usda"), fact("soil_ph_min", 9, "perenual")],
    )
    assert best.source_kind == "usda", "precedence, not whichever number is larger"


# ------------------------------------------------------------- care values


def test_a_value_with_no_source_may_only_be_unknown():
    with pytest.raises(ValueError):
        CareValue(field="water_k_c", value=0.6, confidence="high")
    CareValue(field="water_k_c", value=None, confidence="unknown")
    CareValue(field="water_k_c", value=0.6, confidence="high", is_user_override=True)


def test_a_care_value_renders_in_the_contracts_shape():
    row = CareValue(
        field="min_temp_c", value=-41.7, confidence="high", source_id="s1", unit="C"
    )
    out = row.to_dict({"id": "s1", "kind": "usda"})
    assert out["field"] == "min_temp_c"
    assert out["unit"] == "C"
    assert out["source"]["kind"] == "usda"
    assert out["is_user_override"] is False


# --------------------------------------------------------------- synthesis


def test_every_published_value_carries_the_citation_it_came_from():
    enrichment = synthesise(
        FIR, [result("usda", fact("min_temp_c", -41.7, "usda", unit="C"))]
    )
    row = values(enrichment)["min_temp_c"]
    assert row.confidence == "high"
    source = enrichment.source_by_id(row.source_id)
    assert source is not None and source.kind == "usda"
    assert source.to_row()["payload"] == {"stub": "usda"}


def test_the_fields_that_move_plants_are_reported_even_when_nobody_knows():
    """nothing measures the soil, so an unknown must be visible."""
    enrichment = synthesise(FIR, [result("usda")])
    reported = values(enrichment)
    for field in ALWAYS_REPORT:
        assert reported[field].value is None
        assert reported[field].confidence == "unknown"
        assert reported[field].source_id is None
    assert "water_k_c" in enrichment.unknown_fields


def test_an_unknown_field_writes_no_column():
    """A column left alone keeps whatever a user put there; None would erase it."""
    enrichment = synthesise(FIR, [result("usda")])
    assert enrichment.columns == {}


def test_a_sourced_field_writes_its_column():
    enrichment = synthesise(FIR, [result("usda", fact("min_temp_c", -41.7, "usda"))])
    assert enrichment.columns["min_temp_c"] == -41.7


def test_units_come_from_the_fact_or_from_the_field():
    enrichment = synthesise(FIR, [result("usda", fact("min_temp_c", -41.7, "usda"))])
    assert values(enrichment)["min_temp_c"].unit == "C"


def test_prose_is_cited_like_a_number_is():
    enrichment = synthesise(
        FIR, [result("wikipedia", fact("summary", "A fir.", "wikipedia"))]
    )
    row = values(enrichment)["summary"]
    assert enrichment.source_by_id(row.source_id).kind == "wikipedia"


def test_identifiers_fill_gaps_but_never_overwrite_what_resolution_settled():
    known = SpeciesRef(accepted_name="Abies balsamea", gbif_key="2685484")
    enrichment = synthesise(
        known, [result("wikidata", fact("gbif_key", "999", "wikidata"))]
    )
    assert "gbif_key" not in enrichment.columns

    unknown = synthesise(FIR, [result("wikidata", fact("gbif_key", "999", "wikidata"))])
    assert unknown.columns["gbif_key"] == "999"


def test_every_source_failing_is_a_failed_enrichment_not_an_empty_one():
    failed = synthesise(FIR, [ConnectorResult(kind="usda", error="usda: HTTP 503")])
    assert failed.state == "failed"
    assert failed.errors == {"usda": "usda: HTTP 503"}
    assert all(cv.confidence == "unknown" for cv in failed.care_values)


def test_one_source_answering_is_a_complete_enrichment():
    partial = synthesise(
        FIR,
        [
            result("usda", fact("min_temp_c", -41.7, "usda")),
            ConnectorResult(kind="wikipedia", error="down"),
        ],
    )
    assert partial.state == "complete"
    assert partial.errors == {"wikipedia": "down"}


def test_the_care_value_list_resolves_each_citation():
    enrichment = synthesise(FIR, [result("usda", fact("min_temp_c", -41.7, "usda"))])
    rows = {r["field"]: r for r in enrichment.to_care_value_dicts()}
    assert rows["min_temp_c"]["source"]["kind"] == "usda"
    assert rows["water_k_c"]["source"] is None
    assert rows["water_k_c"]["confidence"] == "unknown"
