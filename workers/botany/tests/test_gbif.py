"""GBIF parsing, against payloads recorded from the live API."""

from workers.botany.connectors.gbif import (
    needs_vernacular_lookup,
    parse_match,
    parse_search,
    parse_vernacular_names,
)
from workers.botany.names import parse_name


def test_an_exact_match_carries_the_key_the_family_and_the_rank(payload):
    (record,) = parse_match(
        payload("gbif/match__monstera-deliciosa.json"), parse_name("Monstera deliciosa")
    )
    assert record.accepted_name == "Monstera deliciosa"
    assert record.gbif_key == "2868241"
    assert record.family == "Araceae"
    assert record.rank == "species"
    assert record.status == "accepted"
    assert record.match_kind == "exact"
    assert record.source_kind == "gbif"


def test_a_misspelling_matches_fuzzily_and_says_so(payload):
    (record,) = parse_match(
        payload("gbif/match__monstra-deliciosa.json"), parse_name("Monstra deliciosa")
    )
    assert record.accepted_name == "Monstera deliciosa"
    assert record.match_kind == "fuzzy"
    # GBIF's own confidence drops from 99 to 85, and we keep its number.
    assert 0.8 <= record.source_score < 0.9


def test_a_synonym_resolves_to_the_accepted_name(payload):
    (record,) = parse_match(
        payload("gbif/match__sansevieria-trifasciata.json"),
        parse_name("Sansevieria trifasciata"),
    )
    assert record.matched_name == "Sansevieria trifasciata"
    assert record.accepted_name == "Dracaena trifasciata"
    assert record.is_synonym
    assert record.gbif_key == "11041822"


def test_no_match_yields_no_records_rather_than_a_guess(payload):
    assert (
        parse_match(
            payload("gbif/match__zzqqx-frobnicata.json"), parse_name("zzqqx frobnicata")
        )
        == ()
    )
    assert (
        parse_match(payload("gbif/match__snake-plant.json"), parse_name("snake plant"))
        == ()
    )


def test_alternatives_are_kept_but_ranked_below_the_pick(payload):
    records = parse_match(
        payload("gbif/match__lavandula-angustifolia.json"),
        parse_name("Lavandula angustifolia"),
    )
    assert len(records) > 1
    assert records[0].accepted_name == "Lavandula angustifolia"
    assert all(records[0].source_score >= r.source_score for r in records[1:])


def test_a_common_name_is_answered_by_the_search_index(payload):
    records = parse_search(
        payload("gbif/search__snake-plant.json"), parse_name("snake plant")
    )
    assert records
    assert records[0].accepted_name == "Dracaena trifasciata"
    assert records[0].match_kind == "vernacular"
    assert records[0].common_name == "Snake plant"


def test_a_shared_common_name_returns_every_species_that_answers_to_it(payload):
    records = parse_search(
        payload("gbif/search__mandrake.json"), parse_name("mandrake")
    )
    names = [r.accepted_name for r in records]
    assert "Mandragora officinarum" in names
    assert len({n for n in names}) > 1, "several species answer to 'mandrake'"
    best = max(records, key=lambda r: r.source_score)
    assert best.accepted_name == "Mandragora officinarum"


def test_an_empty_search_returns_nothing(payload):
    assert (
        parse_search(
            payload("gbif/search__zzqqx-frobnicata.json"),
            parse_name("zzqqx frobnicata"),
        )
        == ()
    )


def test_a_scientific_query_gets_the_checklists_first_english_name(payload):
    name = parse_vernacular_names(
        payload("gbif/vernacular__2868241.json"), parse_name("Monstera deliciosa")
    )
    # Not "monstera", which is merely the vernacular that looks most like Latin.
    assert name == "Ceriman"


def test_a_packed_vernacular_string_is_split_on_commas(payload):
    name = parse_vernacular_names(
        payload("gbif/vernacular__11041822.json"), parse_name("snake plant")
    )
    assert name == "Snake plant"


def test_the_vernacular_lookup_is_only_made_when_nothing_has_a_common_name(payload):
    from_match = parse_match(
        payload("gbif/match__monstera-deliciosa.json"), parse_name("Monstera deliciosa")
    )
    from_search = parse_search(
        payload("gbif/search__snake-plant.json"), parse_name("snake plant")
    )
    assert needs_vernacular_lookup(from_match)
    assert not needs_vernacular_lookup(from_search)
    assert not needs_vernacular_lookup(())
