"""USDA parsing: the frost threshold, and the honesty about not having one."""

from workers.botany.connectors.base import SpeciesRef
from workers.botany.connectors.usda import (
    clean_name,
    fahrenheit_to_celsius,
    parse_characteristics,
    pick_plant,
)

FIR = SpeciesRef(accepted_name="Abies balsamea")


def fields(facts):
    return {f.field: f for f in facts}


def test_the_minimum_temperature_arrives_in_celsius_with_the_fahrenheit_kept(payload):
    fact = fields(
        parse_characteristics(payload("usda/characteristics__15309.json"), FIR)
    )["min_temp_c"]
    assert fact.value == -41.7
    assert fact.raw == "-43", "what USDA said, for an auditor to check the conversion"
    assert fact.unit == "C"
    assert "-43" in fact.note


def test_the_conversion_is_the_ordinary_one():
    assert fahrenheit_to_celsius(32) == 0.0
    assert fahrenheit_to_celsius(212) == 100.0
    assert fahrenheit_to_celsius(-43) == -41.7


def test_the_soil_ph_range_is_read_from_the_two_fields(payload):
    values = fields(
        parse_characteristics(payload("usda/characteristics__15309.json"), FIR)
    )
    assert values["soil_ph_min"].value == 4.0
    assert values["soil_ph_max"].value == 6.0


def test_shade_tolerance_is_read_as_an_outdoor_light_level(payload):
    fact = fields(
        parse_characteristics(payload("usda/characteristics__15309.json"), FIR)
    )["light_label"]
    # Low shade tolerance means the plant wants sun.
    assert fact.value == "full_sun"
    assert fact.raw == "Low"


def test_a_toxicity_rating_sets_both_flags_and_says_it_cannot_tell_them_apart(payload):
    values = fields(
        parse_characteristics(payload("usda/characteristics__15309.json"), FIR)
    )
    assert values["toxic_to_pets"].value is False
    assert values["toxic_to_children"].value is False
    assert "does not distinguish pets from children" in values["toxicity_note"].value


def test_any_toxicity_above_none_is_reported_as_toxic_to_both():
    """Under-reporting is the dangerous direction for a safety flag."""
    for level in ("Slight", "Moderate", "Severe"):
        values = fields(
            parse_characteristics(
                [
                    {
                        "PlantCharacteristicName": "Toxicity",
                        "PlantCharacteristicValue": level,
                    }
                ],
                FIR,
            )
        )
        assert values["toxic_to_pets"].value is True, level
        assert values["toxic_to_children"].value is True, level
        assert level in values["toxicity_note"].value


def test_moisture_use_is_never_turned_into_a_water_coefficient():
    """An adjective is not a crop coefficient."""
    facts = parse_characteristics(
        [
            {
                "PlantCharacteristicName": "Moisture Use",
                "PlantCharacteristicValue": "Medium",
            }
        ],
        FIR,
    )
    assert "water_k_c" not in {f.field for f in facts}
    assert "water_interval_days" not in {f.field for f in facts}


def test_no_characteristics_is_an_answer_not_a_gap_to_fill(payload):
    """Every fixture species returns this. It must yield nothing at all."""
    assert parse_characteristics(payload("usda/characteristics__16378.json"), FIR) == ()
    assert parse_characteristics([], FIR) == ()
    assert parse_characteristics(None, FIR) == ()


def test_an_unreadable_number_is_skipped_rather_than_guessed():
    facts = parse_characteristics(
        [
            {
                "PlantCharacteristicName": "Temperature, Minimum (°F)",
                "PlantCharacteristicValue": "",
            }
        ],
        FIR,
    )
    assert facts == ()


def test_the_search_hit_has_to_be_the_species_we_asked_about(payload):
    found = payload("usda/search__abies-balsamea.json")
    assert pick_plant(found, FIR)["Symbol"] == "ABBA"
    assert pick_plant(found, SpeciesRef(accepted_name="Monstera deliciosa")) is None


def test_a_database_artifact_record_is_not_this_species(payload):
    """USDA's Citrus limon hit is flagged 'database artifact'; citing it would
    attach a source that was talking about something else."""
    assert (
        pick_plant(
            payload("usda/search__citrus-limon.json"),
            SpeciesRef(accepted_name="Citrus limon"),
        )
        is None
    )


def test_names_arrive_wrapped_in_markup_and_authorship():
    assert clean_name("<i>Rosa gallica</i> L.") == "Rosa gallica"
    assert clean_name(None) == ""
