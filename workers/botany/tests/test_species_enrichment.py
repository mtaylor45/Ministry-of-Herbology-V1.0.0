"""an earlier release acceptance: a resolved species in, a cited care profile out.

End to end through the real connectors and parsers, with the network replaced
by ``mocks/recorded/``. The releases's exit criterion is that a new plant
auto-fills summary and care *with sources* in under 60 seconds; what is checked
here is everything that makes that true and testable offline — the values, the
citations, the honesty about gaps, and the number of calls it takes.
"""

import pytest

from workers.botany.connectors.base import SpeciesRef
from workers.botany.enricher import SpeciesEnricher
from workers.botany.factory import build_enrichment_connectors
from workers.botany.mocks import build_mock_enrichment_connectors


@pytest.fixture
def enricher():
    return SpeciesEnricher(build_enrichment_connectors())


@pytest.fixture
def enrich(enricher, run):
    def _enrich(name: str):
        return run(enricher.enrich(SpeciesRef(accepted_name=name)))

    return _enrich


def values(enrichment):
    return {cv.field: cv for cv in enrichment.care_values}


def test_a_new_plant_auto_fills_its_summary_from_a_cited_source(enrich):
    enrichment = enrich("Monstera deliciosa")
    summary = values(enrichment)["summary"]
    assert summary.value.startswith("Monstera deliciosa")
    source = enrichment.source_by_id(summary.source_id)
    assert source.kind == "wikipedia"
    assert source.url == "https://en.wikipedia.org/wiki/Monstera_deliciosa"
    assert source.license == "CC BY-SA 4.0"


def test_common_names_arrive_from_wikidata_with_their_citation(enrich):
    enrichment = enrich("Monstera deliciosa")
    names = values(enrichment)["common_names"]
    assert "Swiss Cheese plant" in names.value
    assert enrichment.source_by_id(names.source_id).kind == "wikidata"


def test_a_measured_care_profile_is_published_with_high_confidence(enrich):
    """USDA has real characteristics for this one, so the values are real."""
    enrichment = enrich("Abies balsamea")
    reported = values(enrichment)
    assert reported["min_temp_c"].value == -41.7
    assert reported["min_temp_c"].unit == "C"
    assert reported["min_temp_c"].confidence == "high"
    assert reported["soil_ph_min"].value == 4.0
    assert reported["light_label"].value == "full_sun"
    assert enrichment.source_by_id(reported["min_temp_c"].source_id).kind == "usda"
    assert enrichment.columns["min_temp_c"] == -41.7


def test_the_coverage_gap_shows_up_as_unknown_rather_than_a_plausible_number(enrich):
    """the design predicted it, the design made it load-bearing, the design renders it.

    USDA publishes measured characteristics for very few plants, and for none
    of the fixture species. That must surface honestly.
    """
    enrichment = enrich("Monstera deliciosa")
    for field in ("water_k_c", "min_temp_c", "water_interval_days", "light_label"):
        row = values(enrichment)[field]
        assert row.value is None, f"{field} was filled in from nowhere"
        assert row.confidence == "unknown"
        assert row.source_id is None
    assert "water_k_c" in enrichment.unknown_fields


def test_no_source_ever_yields_a_water_coefficient_out_of_thin_air(enrich):
    """The engine's own fallback is the engine's assumption, not a plant fact."""
    for name in ("Monstera deliciosa", "Abies balsamea", "Rosa gallica"):
        assert values(enrich(name))["water_k_c"].value is None


def test_every_published_value_has_a_source_and_every_source_a_payload(enrich):
    for name in ("Monstera deliciosa", "Abies balsamea"):
        enrichment = enrich(name)
        for care_value in enrichment.care_values:
            if care_value.confidence == "unknown":
                assert care_value.source_id is None
                continue
            source = enrichment.source_by_id(care_value.source_id)
            assert source is not None, care_value
            assert source.url and source.license
            assert source.to_row()[
                "payload"
            ], "a citation with no payload cannot be audited"


def test_a_cited_care_value_matches_the_contract_schema(enrich, spec):
    jsonschema = pytest.importorskip("jsonschema")
    schema = {
        **spec["components"]["schemas"]["CareValue"],
        "components": spec["components"],
    }
    cited = [r for r in enrich("Abies balsamea").to_care_value_dicts() if r["source"]]
    assert cited
    for row in cited:
        jsonschema.validate(row, schema)


def test_an_uncited_care_value_says_source_null_which_the_schema_has_no_room_for(
    enrich,
):
    """Flagged for the maintainers — `CareValue.source` is `$ref: SourceRef` with
    no null variant, so `"source": null` does not validate.

    the design requires exactly that row to exist: "A value with no source must be
    `confidence: unknown`", and the UI renders it. The already-merged
    `GET /species/{id}/care-values` returns `"source": None` for the uncited
    fixture rows too, and the test suite's mock-stack test asserts it. So the shape is
    settled everywhere except in the schema.

    Requesting: `source: { oneOf: [{ $ref: SourceRef }, { type: 'null' }] }`.
    Until then this test pins the behaviour rather than papering over it by
    dropping the key, because a client that sees no `source` key and a client
    that sees `source: null` should not have to handle two spellings of "we
    don't know".
    """
    rows = {r["field"]: r for r in enrich("Monstera deliciosa").to_care_value_dicts()}
    assert rows["water_k_c"]["source"] is None
    assert rows["water_k_c"]["confidence"] == "unknown"
    assert rows["water_k_c"]["value"] is None


def test_enrichment_is_a_handful_of_calls_not_a_crawl(run):
    """The 60-second exit criterion is a call budget, and this is the budget."""
    connectors = build_mock_enrichment_connectors()
    fetcher = connectors[0].fetcher
    run(SpeciesEnricher(connectors).enrich(SpeciesRef(accepted_name="Abies balsamea")))
    by_kind: dict[str, int] = {}
    for kind, _url, _params in fetcher.calls:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    assert sum(by_kind.values()) <= 5, by_kind
    assert by_kind["wikipedia"] == 1
    assert by_kind["usda"] == 2, "search, then characteristics"


def test_wikidata_is_handed_the_id_rather_than_searching_again(run):
    connectors = build_mock_enrichment_connectors()
    fetcher = connectors[0].fetcher
    run(
        SpeciesEnricher(connectors).enrich(
            SpeciesRef(accepted_name="Monstera deliciosa")
        )
    )
    wikidata_calls = [
        params for kind, _url, params in fetcher.calls if kind == "wikidata"
    ]
    assert wikidata_calls[0].get("ids") == "Q161077"
    assert "titles" not in wikidata_calls[0]


def test_a_source_that_is_down_does_not_become_a_fact_about_the_plant(run):
    class Down:
        kind = "usda"

        async def enrich(self, species):
            raise TimeoutError("usda unreachable")

    connectors = [Down(), *build_mock_enrichment_connectors()[1:]]
    enrichment = run(
        SpeciesEnricher(connectors).enrich(SpeciesRef(accepted_name="Abies balsamea"))
    )
    assert "usda" in enrichment.errors
    assert enrichment.state == "complete", "others answered"
    assert values(enrichment)["min_temp_c"].confidence == "unknown"
    assert values(enrichment)["min_temp_c"].value is None


def test_every_source_being_down_is_a_failed_enrichment(run):
    class Down:
        def __init__(self, kind):
            self.kind = kind

        async def enrich(self, species):
            raise ConnectionError(f"{self.kind} unreachable")

    enrichment = run(
        SpeciesEnricher([Down("usda"), Down("wikidata"), Down("wikipedia")]).enrich(
            SpeciesRef(accepted_name="Abies balsamea")
        )
    )
    assert enrichment.state == "failed"
    assert set(enrichment.errors) == {"usda", "wikidata", "wikipedia"}
    assert enrichment.columns == {}


def test_the_job_returns_rows_ready_to_persist(run):
    from workers.botany.tasks import enrich_species

    out = run(enrich_species({}, "species-1", "Abies balsamea"))
    assert out["enrichment_state"] == "complete"
    assert out["columns"]["min_temp_c"] == -41.7
    assert any(
        r["field"] == "min_temp_c" and r["source"]["kind"] == "usda"
        for r in out["care_values"]
    )
    assert all("payload" in s for s in out["sources"])


def test_the_job_will_not_guess_a_species_from_an_id_alone(run):
    from workers.botany.tasks import enrich_species

    out = run(enrich_species({}, "species-1", "   "))
    assert out["enrichment_state"] == "failed"
    assert out["care_values"] == []
