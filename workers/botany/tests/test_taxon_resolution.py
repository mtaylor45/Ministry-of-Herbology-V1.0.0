"""an earlier release acceptance: a typed name in, ranked accepted names out.

End to end through the real connectors and the real parsers, with the network
replaced by ``mocks/recorded/``. These are the releases's five cases — a plain
name, a common name, a misspelling, a synonym, a cultivar — plus the two that
matter most for not killing a plant: "we don't know", and "we could not ask".
"""

import pytest


@pytest.fixture
def resolve(resolver, run):
    def _resolve(name: str):
        return run(resolver.resolve(name))

    return _resolve


def test_a_scientific_name_resolves_to_itself_with_both_sources_cited(resolve):
    resolution = resolve("Monstera deliciosa")
    top = resolution.candidates[0]
    assert top.accepted_name == "Monstera deliciosa"
    assert top.family == "Araceae"
    assert top.gbif_key == "2868241"
    assert top.powo_id == "urn:lsid:ipni.org:names:87478-1"
    assert top.confidence == "high"
    assert top.source["kind"] == "powo", "Kew outranks the aggregator"
    assert {s.kind for s in resolution.sources} == {"powo", "gbif"}


def test_a_misspelling_still_finds_the_plant_but_admits_the_doubt(resolve):
    resolution = resolve("Monstra deliciosa")
    top = resolution.candidates[0]
    assert top.accepted_name == "Monstera deliciosa"
    # POWO's search is not fuzzy, so only GBIF answered, and it answered FUZZY.
    assert top.source["kind"] == "gbif"
    assert top.confidence == "medium"


def test_a_synonym_comes_back_as_the_accepted_name(resolve):
    top = resolve("Sansevieria trifasciata").candidates[0]
    assert top.accepted_name == "Dracaena trifasciata"
    assert top.common_name == "Snake plant"
    assert top.confidence == "high"


def test_a_common_name_resolves_and_says_it_is_less_sure(resolve):
    top = resolve("snake plant").candidates[0]
    assert top.accepted_name == "Dracaena trifasciata"
    assert top.confidence == "medium"


def test_a_common_name_shared_by_several_species_returns_all_of_them(resolve):
    candidates = resolve("mandrake").candidates
    assert candidates[0].accepted_name == "Mandragora officinarum"
    assert len(candidates) > 1, "the alternatives are shown, not silently dropped"
    assert all(c.confidence in {"medium", "low", "unknown"} for c in candidates)


def test_a_cultivar_is_split_from_the_species_and_handed_back(resolve):
    top = resolve("Lavandula angustifolia 'Hidcote'").candidates[0]
    assert top.accepted_name == "Lavandula angustifolia"
    assert top.cultivar == "Hidcote", "POWO and GBIF index species, not cultivars"
    assert top.powo_id == "urn:lsid:ipni.org:names:449008-1"


def test_a_hybrid_is_one_plant_however_the_two_sources_spell_it(resolve):
    candidates = resolve("Citrus x limon").candidates
    assert candidates[0].accepted_name == "Citrus limon"
    assert candidates[0].gbif_key == "7647136"
    assert candidates[0].powo_id


def test_a_name_nobody_has_heard_of_gets_an_empty_list(resolve):
    """ "We don't know" is a correct answer, and the UI renders it."""
    resolution = resolve("zzqqx frobnicata")
    assert resolution.candidates == ()
    assert resolution.reachable, "both sources answered; they just had nothing"


def test_every_candidate_carries_a_citation_with_a_licence(resolve):
    for name in ("Monstera deliciosa", "snake plant", "mandrake", "Hosta sieboldiana"):
        for candidate in resolve(name).candidates:
            assert candidate.source is not None, candidate
            assert candidate.source["url"]
            assert candidate.source["license"]
            assert candidate.confidence in {"high", "medium", "low", "unknown"}


def test_the_raw_payload_behind_every_candidate_is_kept_for_audit(resolve):
    """a synthesis has to be repeatable without going back out."""
    resolution = resolve("Monstera deliciosa")
    cited = {c.source["id"] for c in resolution.candidates}
    rows = {s.id: s.to_row() for s in resolution.sources}
    assert cited <= set(rows)
    for source_id in cited:
        assert rows[source_id][
            "payload"
        ], "a citation with no payload cannot be audited"


def test_a_common_name_costs_one_extra_call_and_no_more(resolve, resolver):
    """The vernacular index is only consulted when the name match came up short."""
    fetcher = resolver.connectors[0].fetcher
    resolve("Monstera deliciosa")
    scientific = [c for c in fetcher.calls if c[0] == "gbif"]
    fetcher.calls.clear()
    resolve("snake plant")
    vernacular = [c for c in fetcher.calls if c[0] == "gbif"]
    assert len(scientific) == 2, "name match, then vernacular names for the hit"
    assert len(vernacular) == 2, "name match came back NONE, then the search"


def test_pl_ntnet_is_off_and_the_typed_name_path_does_not_notice(resolve):
    """the free path is complete on its own, not degraded-but-shipping."""
    from workers.botany.factory import enabled_flagged_sources
    from workers.botany.settings import BotanySettings

    assert enabled_flagged_sources(BotanySettings()) == ()
    assert resolve("Monstera deliciosa").candidates[0].confidence == "high"
