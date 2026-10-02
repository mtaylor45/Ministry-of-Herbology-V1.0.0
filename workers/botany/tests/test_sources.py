"""Source rows: the citation, and the payload it was read from."""

from datetime import UTC, datetime

from workers.botany.sources import SourceCache, build_source, source_id_for

WHEN = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_the_raw_payload_is_kept_so_a_synthesis_can_be_redone():
    record = build_source(
        "gbif", "https://api.gbif.org/v1/species/match", {"usageKey": 1}
    )
    assert record.to_row()["payload"] == {"usageKey": 1}


def test_a_citation_does_not_carry_the_payload_to_the_client():
    record = build_source(
        "powo", "https://powo.science.kew.org/api/2/search", {"big": "blob"}
    )
    assert "payload" not in record.to_ref()


def test_the_licence_and_title_come_from_the_frozen_fixtures_vocabulary():
    record = build_source(
        "powo", "https://example.invalid", {}, title_suffix="Monstera"
    )
    assert record.title == "Plants of the World Online — Monstera"
    assert record.license == "CC BY 4.0"
    assert build_source("wikidata", None, {}).license == "CC0"


def test_a_source_we_have_no_licence_for_says_so_rather_than_guessing():
    assert build_source("plantnet", "https://example.invalid", {}).license is None
    assert build_source("nonesuch", "https://example.invalid", {}).license is None


def test_a_replayed_payload_is_labelled_as_a_recording():
    record = build_source("gbif", "https://example.invalid", {}, is_mock=True)
    assert record.title.endswith("(recorded)")


def test_the_same_url_gets_the_same_id_in_every_process():
    url = "https://api.gbif.org/v1/species/match?name=Monstera"
    assert source_id_for("gbif", url) == source_id_for("gbif", url)
    assert source_id_for("gbif", url) != source_id_for("powo", url)


def test_retrieved_at_is_serialised_as_utc():
    record = build_source("gbif", "https://example.invalid", {}, retrieved_at=WHEN)
    assert record.to_ref()["retrieved_at"].endswith("+00:00")


def test_the_cache_returns_a_payload_until_it_goes_stale():
    cache = SourceCache(ttl_s=60)
    record = build_source("gbif", "https://example.invalid", {"a": 1})
    key = cache.key("gbif", "https://example.invalid", {"name": "Monstera"})
    cache.put(key, record, now=1000.0)
    assert cache.get(key, now=1030.0) is record
    assert cache.get(key, now=1100.0) is None
    assert len(cache) == 0


def test_cache_keys_separate_different_queries():
    cache = SourceCache()
    assert cache.key("gbif", "u", {"q": "a"}) != cache.key("gbif", "u", {"q": "b"})
    assert cache.key("gbif", "u", {"q": "a"}) == cache.key("gbif", "u", {"q": "a"})
