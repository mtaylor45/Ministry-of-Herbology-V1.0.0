"""The offline stand-ins: recordings first, frozen fixtures second."""

import json

from workers.botany.mocks import RecordedFetcher, build_mock_connectors
from workers.botany.mocks.fetcher import RECORDED_ON, recording_name, slug


def test_a_query_maps_to_a_filename_the_same_way_every_time():
    assert slug("Monstera deliciosa") == "monstera-deliciosa"
    assert slug("Citrus × limon") == "citrus-limon"
    assert slug("  ") == "empty"


def test_each_endpoint_knows_which_recording_answers_it():
    gbif = "https://api.gbif.org/v1"
    assert recording_name(
        "gbif", f"{gbif}/species/match", {"name": "Monstera deliciosa"}
    ) == ("gbif/match__monstera-deliciosa.json")
    assert recording_name("gbif", f"{gbif}/species/search", {"q": "snake plant"}) == (
        "gbif/search__snake-plant.json"
    )
    assert recording_name("gbif", f"{gbif}/species/2868241/vernacularNames", {}) == (
        "gbif/vernacular__2868241.json"
    )
    assert recording_name(
        "powo", "https://powo.science.kew.org/api/2/search", {"q": "Hosta"}
    ) == ("powo/search__hosta.json")
    assert recording_name("gbif", f"{gbif}/occurrence/search", {}) is None


def test_a_recording_is_cited_with_the_date_it_was_recorded(run, recorded_dir):
    fetcher = RecordedFetcher()
    result = run(
        fetcher.get_json(
            "gbif",
            "https://api.gbif.org/v1/species/match",
            {"name": "Monstera deliciosa"},
        )
    )
    assert result.is_mock
    assert result.retrieved_at == RECORDED_ON
    assert (
        RECORDED_ON.date().isoformat() in (recorded_dir / "PROVENANCE.md").read_text()
    )


def test_a_name_with_no_recording_falls_back_to_the_frozen_fixtures(run):
    """The build-against-mocks rule: the mock tells the same story as every other parts of the
    project's."""
    fetcher = RecordedFetcher()
    result = run(
        fetcher.get_json(
            "gbif",
            "https://api.gbif.org/v1/species/match",
            {"name": "Ocimum basilicum"},
        )
    )
    assert result.payload["canonicalName"] == "Ocimum basilicum"
    assert result.payload["family"] == "Lamiaceae"
    assert result.payload["_synthetic"]["from"] == "fixtures/species/species.json"


def test_a_fixture_derived_payload_can_never_pass_for_a_fetched_one(run):
    fetcher = RecordedFetcher()
    for name in ("Ocimum basilicum", "utter nonsense"):
        result = run(
            fetcher.get_json(
                "gbif", "https://api.gbif.org/v1/species/match", {"name": name}
            )
        )
        assert "_synthetic" in result.payload


def test_powo_says_nothing_it_was_not_recorded_saying(run):
    fetcher = RecordedFetcher()
    result = run(
        fetcher.get_json(
            "powo",
            "https://powo.science.kew.org/api/2/search",
            {"q": "Ocimum basilicum"},
        )
    )
    assert result.payload["results"] == []


def test_a_fixture_species_still_resolves_end_to_end(run):
    from workers.botany.resolve import TaxonResolver

    resolution = run(TaxonResolver(build_mock_connectors()).resolve("Rosa gallica"))
    assert resolution.candidates[0].accepted_name == "Rosa gallica"
    assert resolution.candidates[0].family == "Rosaceae"
    # The fixtures carry no GBIF key, and one is not conjured to fill the hole.
    assert resolution.candidates[0].gbif_key is None


def test_every_recording_is_valid_json_and_declared_in_provenance(recorded_dir):
    provenance = (recorded_dir / "PROVENANCE.md").read_text()
    files = sorted(recorded_dir.rglob("*.json"))
    assert len(files) >= 20
    for path in files:
        json.loads(path.read_text())
        assert (
            path.name in provenance
        ), f"{path.name} is not accounted for in PROVENANCE.md"


def test_every_powo_stand_in_declares_that_it_is_one(recorded_dir):
    for path in sorted((recorded_dir / "powo").glob("*.json")):
        payload = json.loads(path.read_text())
        assert payload["_provenance"]["content_source"].startswith(
            "https://www.ipni.org"
        )
