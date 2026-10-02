"""Reading a typed name. All of this is pure string work."""

from workers.botany.names import (
    fold,
    merge_key,
    parse_name,
    similarity,
    strip_authorship,
)


def test_a_plain_binomial_survives_intact():
    parsed = parse_name("Monstera deliciosa")
    assert parsed.scientific == "Monstera deliciosa"
    assert parsed.cultivar is None
    assert parsed.looks_scientific


def test_case_and_stray_whitespace_are_normalised():
    assert parse_name("  monstera   DELICIOSA ").scientific == "Monstera deliciosa"


def test_a_quoted_cultivar_is_split_off_the_species():
    parsed = parse_name("Lavandula angustifolia 'Hidcote'")
    assert parsed.scientific == "Lavandula angustifolia"
    assert parsed.cultivar == "Hidcote"


def test_smart_quotes_and_cv_are_cultivars_too():
    assert parse_name("Hosta sieboldiana ‘Elegans’").cultivar == "Elegans"
    assert parse_name("Sansevieria trifasciata cv. Laurentii").cultivar == "Laurentii"


def test_authorship_is_dropped_but_the_epithet_is_not():
    assert strip_authorship("Monstera deliciosa Liebm.") == "Monstera deliciosa"
    assert strip_authorship("Hosta sieboldiana (Hook.) Engl.") == "Hosta sieboldiana"
    assert strip_authorship("Citrus × limon (L.) Osbeck") == "Citrus × limon"
    assert strip_authorship("Rosa gallica") == "Rosa gallica"


def test_authorship_stripping_never_empties_the_name():
    assert strip_authorship("L.") == "L."


def test_the_hybrid_marker_is_recognised_however_it_is_typed():
    for typed in ("Citrus x limon", "Citrus X limon", "Citrus × limon"):
        parsed = parse_name(typed)
        assert parsed.is_hybrid
        assert parsed.rank_hint == "hybrid"


def test_one_plant_spelled_three_ways_shares_a_merge_key():
    keys = {merge_key(n) for n in ("Citrus × limon", "Citrus x limon", "Citrus limon")}
    assert keys == {"citrus limon"}


def test_folding_ignores_case_and_accents():
    assert fold("Bolsós Vigo") == fold("bolsos vigo")


def test_an_infraspecific_marker_sets_the_rank_hint():
    assert parse_name("Monstera deliciosa var. borsigiana").rank_hint == "variety"
    assert (
        parse_name("Sansevieria trifasciata subsp. sikawae").rank_hint == "subspecies"
    )


def test_a_capitalised_single_word_is_a_genus_but_a_lowercase_one_is_not():
    assert parse_name("Hosta").rank_hint == "genus"
    # "mandrake" is a nickname; only a source gets to say what rank it is.
    assert parse_name("mandrake").rank_hint == "species"


def test_a_two_word_common_name_is_indistinguishable_from_a_binomial():
    """A documented limit, not an accident.

    Nothing in the string says whether ``snake plant`` is Latin, so the shape
    heuristic guesses "binomial" and the connectors try both lookups: the name
    match, which GBIF answers ``NONE`` to, and then the vernacular search, which
    answers properly. What must survive is the text the user typed.
    """
    parsed = parse_name("snake plant")
    assert parsed.text == "snake plant"
    assert fold(parsed.lookup) == "snake plant"


def test_an_empty_name_parses_to_nothing_rather_than_crashing():
    parsed = parse_name("   ")
    assert parsed.text == ""
    assert parsed.scientific is None


def test_similarity_is_symmetric_and_catches_a_typo():
    assert similarity("Monstra deliciosa", "Monstera deliciosa") > 0.9
    assert similarity("a", "b") == similarity("b", "a")
    assert similarity("Rosa gallica", "Rosa gallica") == 1.0
