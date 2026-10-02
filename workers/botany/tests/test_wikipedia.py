"""Wikipedia parsing: prose, and nothing that looks like a number."""

from workers.botany.connectors.base import SpeciesRef
from workers.botany.connectors.wikipedia import (
    page_title,
    page_url,
    parse_summary,
    wikidata_id,
)

MONSTERA = SpeciesRef(accepted_name="Monstera deliciosa")


def test_the_lead_extract_becomes_the_compendium_summary(payload):
    (fact,) = parse_summary(
        payload("wikipedia/summary__monstera-deliciosa.json"), MONSTERA
    )
    assert fact.field == "summary"
    assert fact.value.startswith("Monstera deliciosa")
    assert fact.source_kind == "wikipedia"


def test_the_summary_is_quoted_not_paraphrased(payload):
    raw = payload("wikipedia/summary__monstera-deliciosa.json")
    (fact,) = parse_summary(raw, MONSTERA)
    assert fact.value == raw["extract"].strip()
    assert fact.raw == raw["extract"]


def test_wikipedia_never_reports_a_care_value(payload):
    """It is prose. A number read out of a sentence is an invented number."""
    facts = parse_summary(
        payload("wikipedia/summary__monstera-deliciosa.json"), MONSTERA
    )
    assert {f.field for f in facts} == {"summary"}


def test_the_wikidata_id_comes_free_with_the_summary(payload):
    assert (
        wikidata_id(payload("wikipedia/summary__monstera-deliciosa.json")) == "Q161077"
    )
    assert wikidata_id({"wikibase_item": "not-an-item"}) is None
    assert wikidata_id({}) is None


def test_the_citation_points_at_the_article(payload):
    url = page_url(payload("wikipedia/summary__monstera-deliciosa.json"))
    assert url == "https://en.wikipedia.org/wiki/Monstera_deliciosa"
    assert page_url({}) is None


def test_a_stub_is_not_worth_a_compendium_entry():
    assert (
        parse_summary(
            {"type": "standard", "extract": "Foo is a species of plant."}, MONSTERA
        )
        == ()
    )


def test_a_disambiguation_page_is_not_about_this_plant():
    assert (
        parse_summary({"type": "disambiguation", "extract": "x" * 300}, MONSTERA) == ()
    )
    assert parse_summary({"type": "no-extract"}, MONSTERA) == ()
    assert parse_summary({}, MONSTERA) == ()


def test_the_title_is_the_accepted_name():
    assert page_title(MONSTERA) == "Monstera_deliciosa"
