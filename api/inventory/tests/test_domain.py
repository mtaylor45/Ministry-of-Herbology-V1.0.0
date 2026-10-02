"""The invariants, on their own, without HTTP or storage in the way."""

from __future__ import annotations

import pytest

from inventory.domain import (
    LOCATION_KINDS,
    SPECIMEN_STATUSES,
    SUN_EXPOSURES,
    display_name,
    is_group_for,
    is_outdoor_for,
    normalise_sun_exposure,
    search_haystack,
)


def test_a_specimen_is_outdoors_exactly_when_its_location_is():
    assert is_outdoor_for({"is_outdoor": True}) is True
    assert is_outdoor_for({"is_outdoor": False}) is False


def test_a_specimen_with_no_location_is_treated_as_indoors():
    """The frost guard must never act on a plant whose exposure nobody stated."""
    assert is_outdoor_for(None) is False
    assert is_outdoor_for({}) is False


def test_a_count_above_one_makes_a_group():
    """A lavender hedge is one specimen with a count, tended once."""
    assert is_group_for(1) is False
    assert is_group_for(2) is True
    assert is_group_for(40) is True


def test_display_name_prefers_nickname_then_common_name_then_accepted_name():
    species = {
        "accepted_name": "Monstera deliciosa",
        "common_names": ["swiss cheese plant"],
    }
    assert display_name("Gilderoy", species) == "Gilderoy"
    assert display_name(None, species) == "Swiss cheese plant"
    assert (
        display_name(None, {"accepted_name": "Monstera deliciosa"})
        == "Monstera deliciosa"
    )
    assert display_name(None, None) == "Unnamed specimen"


def test_search_covers_the_species_as_well_as_the_display_name():
    species = {"accepted_name": "Lavandula angustifolia", "common_names": ["lavender"]}
    hay = search_haystack("The Hedge", species)
    assert "the hedge" in hay
    assert "lavandula" in hay
    assert "lavender" in hay


@pytest.mark.parametrize("given", [None, "", "dappled", "FULL_SUN"])
def test_an_unstated_sun_exposure_becomes_unknown_not_null(given):
    assert normalise_sun_exposure(given) == "unknown"
    assert normalise_sun_exposure("part_shade") == "part_shade"


def test_the_enums_match_the_frozen_contract(spec):
    """Three copies of an enum drift; this notices before the UI does."""
    schemas = spec["components"]["schemas"]
    assert set(SUN_EXPOSURES) == set(schemas["SunExposure"]["enum"])
    assert set(SPECIMEN_STATUSES) == set(schemas["SpecimenStatus"]["enum"])
    assert set(LOCATION_KINDS) == set(schemas["Location"]["properties"]["kind"]["enum"])
