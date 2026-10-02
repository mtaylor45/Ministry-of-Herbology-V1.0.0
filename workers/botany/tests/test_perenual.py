"""Perenual: off by default, and proved to be off.

The payloads here are about ``Testus exampleii``, a plant that does not exist.
The shape is what these tests check; a recording of real Perenual data would be
neither free nor openly licensed to commit.
"""

import pytest

from workers.botany.connectors.base import SpeciesRef
from workers.botany.connectors.perenual import (
    PerenualConnector,
    _first_match,
    _without_key,
    parse_details,
)
from workers.botany.factory import build_enrichment_connectors, enabled_flagged_sources
from workers.botany.settings import BotanySettings

FICTION = SpeciesRef(accepted_name="Testus exampleii")


def test_it_is_off_unless_a_key_is_configured():
    assert enabled_flagged_sources(BotanySettings()) == ()
    assert BotanySettings().enable_perenual is False
    assert BotanySettings(perenual_api_key="k").enable_perenual is True


def test_the_free_path_is_built_without_it():
    kinds = [
        c.kind for c in build_enrichment_connectors(BotanySettings(mock_mode=False))
    ]
    assert "perenual" not in kinds
    assert kinds == ["usda", "wikidata", "wikipedia"], "the design complete free path"


def test_it_joins_the_free_path_when_a_key_is_configured():
    settings = BotanySettings(mock_mode=False, perenual_api_key="test-key")
    kinds = [c.kind for c in build_enrichment_connectors(settings)]
    assert (
        kinds[-1] == "perenual"
    ), "and last, because SOURCE_RANK puts it below the rest"


def test_constructing_it_without_a_key_is_a_bug_not_a_401():
    with pytest.raises(ValueError):
        PerenualConnector(fetcher=None, api_key="")


def test_the_api_key_never_reaches_a_citation():
    assert _without_key("https://perenual.com/api/species-list?key=secret&q=x") == (
        "https://perenual.com/api/species-list?key=REDACTED&q=x"
    )


def test_it_reads_the_fields_perenual_states():
    facts = {
        f.field: f.value
        for f in parse_details(
            {
                "sunlight": ["full sun"],
                "poisonous_to_pets": 1,
                "poisonous_to_humans": 0,
                "description": "A plant that does not exist.",
            },
            FICTION,
        )
    }
    assert facts["light_label"] == "full_sun"
    assert facts["toxic_to_pets"] is True
    assert facts["toxic_to_children"] is False
    assert facts["summary"] == "A plant that does not exist."


def test_a_watering_category_stays_a_category():
    """Frequent/Average/Minimum is not an interval in days, and never becomes one."""
    facts = parse_details({"watering": "Frequent", "growth_rate": "High"}, FICTION)
    assert {f.field for f in facts} == set()


def test_the_match_has_to_be_the_species_we_asked_about():
    payload = {
        "data": [
            {"id": 1, "scientific_name": ["Something else"]},
            {"id": 2, "scientific_name": ["Testus exampleii"]},
        ]
    }
    assert _first_match(payload, FICTION)["id"] == 2
    assert _first_match({"data": []}, FICTION) is None
    assert _first_match({}, FICTION) is None
