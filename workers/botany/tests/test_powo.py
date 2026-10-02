"""POWO parsing. See mocks/recorded/PROVENANCE.md for where these payloads came from."""

from workers.botany.connectors.powo import parse_search, parse_taxon, powo_id, taxon_url
from workers.botany.names import parse_name


def test_an_accepted_name_carries_its_ipni_identifier(payload):
    (record,) = parse_search(
        payload("powo/search__monstera-deliciosa.json"),
        parse_name("Monstera deliciosa"),
    )
    assert record.accepted_name == "Monstera deliciosa"
    assert record.powo_id == "urn:lsid:ipni.org:names:87478-1"
    assert record.authorship == "Liebm."
    assert record.family == "Araceae"
    assert record.status == "accepted"
    assert record.source_kind == "powo"


def test_a_synonym_is_reported_under_kews_accepted_name(payload):
    (record,) = parse_search(
        payload("powo/search__sansevieria-trifasciata.json"),
        parse_name("Sansevieria trifasciata"),
    )
    assert record.matched_name == "Sansevieria trifasciata"
    assert record.accepted_name == "Dracaena trifasciata"
    assert record.is_synonym
    # The identifier follows the accepted name, not the name that was typed.
    assert record.powo_id == "urn:lsid:ipni.org:names:77164235-1"


def test_powo_says_nothing_about_a_common_name_or_a_misspelling(payload):
    assert (
        parse_search(
            payload("powo/search__snake-plant.json"), parse_name("snake plant")
        )
        == ()
    )
    assert (
        parse_search(
            payload("powo/search__monstra-deliciosa.json"),
            parse_name("Monstra deliciosa"),
        )
        == ()
    )


def test_the_hybrid_marker_does_not_make_the_match_look_fuzzy(payload):
    (record,) = parse_search(
        payload("powo/search__citrus-limon.json"), parse_name("Citrus x limon")
    )
    assert record.match_kind == "exact"
    assert record.accepted_name == "Citrus limon"


def test_an_identifier_can_be_read_out_of_the_taxon_url_alone():
    entry = {"url": "/taxon/urn:lsid:ipni.org:names:87478-1"}
    assert powo_id(entry) == "urn:lsid:ipni.org:names:87478-1"
    assert (
        taxon_url(entry)
        == "https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:87478-1"
    )
    assert powo_id({"url": "/taxon/nonsense"}) is None
    assert taxon_url({}) is None


def test_a_name_kew_does_not_accept_is_not_quietly_replaced():
    """No ``synonymOf``, no accepted name: we report what it said and score it down."""
    record = parse_taxon(
        {
            "name": "Lavandula angustifolia",
            "author": "Moench",
            "accepted": False,
            "rank": "Species",
            "fqId": "urn:lsid:ipni.org:names:449009-1",
        },
        parse_name("Lavandula angustifolia"),
    )
    assert record is not None
    assert record.accepted_name == "Lavandula angustifolia"
    assert record.status == "unknown"
    assert record.source_score < 1.0


def test_a_taxon_record_reads_its_family_out_of_the_classification():
    record = parse_taxon(
        {
            "name": "Monstera deliciosa",
            "accepted": True,
            "rank": "Species",
            "fqId": "urn:lsid:ipni.org:names:87478-1",
            "classification": {"family": "Araceae", "genus": "Monstera"},
        },
        parse_name("Monstera deliciosa"),
    )
    assert record is not None
    assert record.family == "Araceae"
    assert record.genus == "Monstera"


def test_an_empty_taxon_payload_is_not_a_record():
    assert parse_taxon({}, parse_name("Monstera deliciosa")) is None
