"""Wikidata parsing: statements, in one language, with the ids to check them."""

from workers.botany.connectors.base import SpeciesRef
from workers.botany.connectors.wikidata import (
    _claims,
    common_names,
    parse_entity,
    parse_labels,
    range_item_ids,
)

MONSTERA = SpeciesRef(accepted_name="Monstera deliciosa")


def fields(facts):
    return {f.field: f.value for f in facts}


def test_english_common_names_are_read_and_others_are_not(payload):
    values = fields(parse_entity(payload("wikidata/entity__q161077.json"), MONSTERA))
    assert "Swiss Cheese plant" in values["common_names"]
    # The same entity carries Gatenplant, 龜背芋 and Cerimán. A Compendium in
    # mixed languages is worse than none.
    assert all(name.isascii() for name in values["common_names"])


def test_the_identifiers_that_let_kew_check_the_encyclopaedia(payload):
    values = fields(parse_entity(payload("wikidata/entity__q161077.json"), MONSTERA))
    assert values["gbif_key"] == "2868241"
    assert values["powo_id"] == "urn:lsid:ipni.org:names:87478-1"
    assert values["wikidata_id"] == "Q161077"


def test_a_deprecated_statement_is_one_wikidata_no_longer_stands_behind():
    claims = {
        "P1843": [
            {
                "rank": "deprecated",
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"language": "en", "text": "wrong name"}},
                },
            },
            {
                "rank": "normal",
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"language": "en", "text": "right name"}},
                },
            },
        ]
    }
    assert common_names(claims) == ["right name"]


def test_a_statement_with_no_value_is_not_a_value():
    claims = {"P1843": [{"mainsnak": {"snaktype": "novalue"}}]}
    assert common_names(claims) == []


def test_an_absent_entity_yields_nothing(payload):
    assert parse_entity({"entities": {"Q1": {"missing": ""}}}, MONSTERA) == ()
    assert parse_entity({}, MONSTERA) == ()


def test_a_range_is_read_as_items_then_turned_into_names():
    claims = {
        "P2341": [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"entity-type": "item", "id": "Q96"}},
                }
            },
        ]
    }
    assert range_item_ids(claims) == ["Q96"]
    labels = {"entities": {"Q96": {"labels": {"en": {"value": "Mexico"}}}}}
    assert parse_labels(labels, ["Q96"]) == ["Mexico"]
    assert parse_labels({}, ["Q96"]) == []


def test_monstera_states_no_native_range_and_none_is_invented(payload):
    """Wikidata simply has no P2341 here, and synthesis must leave it unknown."""
    _, claims = _claims(payload("wikidata/entity__q161077.json"))
    assert range_item_ids(claims) == []
    assert "native_range" not in fields(
        parse_entity(payload("wikidata/entity__q161077.json"), MONSTERA)
    )
