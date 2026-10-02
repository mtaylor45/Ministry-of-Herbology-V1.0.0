"""Ranking and confidence — the part that decides what the user is told.

Nothing here may invent a name. Confidence may only ever fall.
"""

from workers.botany.connectors.base import ConnectorResult, TaxonRecord
from workers.botany.names import parse_name
from workers.botany.resolve import TaxonResolver, rank_candidates
from workers.botany.sources import build_source


def record(name, kind, **kwargs):
    return TaxonRecord(accepted_name=name, source_kind=kind, **kwargs)


def result(kind, *records, error=None):
    return ConnectorResult(
        kind=kind,
        records=tuple(records),
        sources=(build_source(kind, f"https://{kind}.invalid/search", {"stub": True}),),
        error=error,
    )


class FakeConnector:
    def __init__(self, kind, records=(), error=None, raises=None):
        self.kind = kind
        self._records = records
        self._error = error
        self._raises = raises

    async def resolve(self, parsed):
        if self._raises:
            raise self._raises
        return result(self.kind, *self._records, error=self._error)


# --------------------------------------------------------------- ranking


def test_two_sources_agreeing_outrank_one_source_alone():
    parsed = parse_name("Monstera deliciosa")
    candidates = rank_candidates(
        parsed,
        [
            result("powo", record("Monstera deliciosa", "powo", powo_id="ipni:1")),
            result("gbif", record("Monstera deliciosa", "gbif", gbif_key="2868241")),
            result("gbif", record("Monstera adansonii", "gbif", gbif_key="1")),
        ],
    )
    assert candidates[0].accepted_name == "Monstera deliciosa"
    assert candidates[0].score > candidates[1].score
    # One candidate, both identifiers: the merge keeps what each source knew.
    assert candidates[0].powo_id == "ipni:1"
    assert candidates[0].gbif_key == "2868241"


def test_kew_wins_the_citation_when_both_sources_answer():
    candidates = rank_candidates(
        parse_name("Monstera deliciosa"),
        [
            result("gbif", record("Monstera deliciosa", "gbif")),
            result("powo", record("Monstera deliciosa", "powo")),
        ],
    )
    assert candidates[0].source["kind"] == "powo"
    assert candidates[0].confidence == "high"


def test_nothing_found_is_an_empty_list_not_a_plausible_suggestion():
    assert (
        rank_candidates(
            parse_name("zzqqx frobnicata"), [result("powo"), result("gbif")]
        )
        == ()
    )


def test_a_cultivar_travels_with_every_candidate():
    candidates = rank_candidates(
        parse_name("Lavandula angustifolia 'Hidcote'"),
        [result("powo", record("Lavandula angustifolia", "powo"))],
    )
    assert candidates[0].cultivar == "Hidcote"
    assert candidates[0].accepted_name == "Lavandula angustifolia"


def test_one_taxon_spelled_two_ways_is_one_candidate():
    candidates = rank_candidates(
        parse_name("Citrus x limon"),
        [
            result("powo", record("Citrus × limon", "powo")),
            result("gbif", record("Citrus limon", "gbif", gbif_key="7647136")),
        ],
    )
    assert len(candidates) == 1
    assert candidates[0].gbif_key == "7647136"


# ------------------------------------------------------------ confidence


def test_a_fuzzy_match_is_trusted_less_than_an_exact_one():
    exact = rank_candidates(
        parse_name("Monstera deliciosa"),
        [result("gbif", record("Monstera deliciosa", "gbif"))],
    )
    fuzzy = rank_candidates(
        parse_name("Monstra deliciosa"),
        [
            result(
                "gbif",
                record(
                    "Monstera deliciosa", "gbif", match_kind="fuzzy", source_score=0.85
                ),
            )
        ],
    )
    assert exact[0].confidence == "high"
    assert fuzzy[0].confidence == "medium"


def test_a_common_name_match_is_trusted_less_than_a_scientific_one():
    candidates = rank_candidates(
        parse_name("snake plant"),
        [
            result(
                "gbif", record("Dracaena trifasciata", "gbif", match_kind="vernacular")
            )
        ],
    )
    assert candidates[0].confidence == "medium"


def test_two_trusted_sources_disagreeing_lowers_confidence_rather_than_averaging():
    """say so by lowering the confidence — do not split the difference."""
    candidates = rank_candidates(
        parse_name("Lavandula angustifolia"),
        [
            result("powo", record("Lavandula angustifolia", "powo")),
            result("gbif", record("Lavandula latifolia", "gbif")),
        ],
    )
    assert candidates[0].accepted_name == "Lavandula angustifolia"
    assert candidates[0].confidence == "medium"
    assert {c.accepted_name for c in candidates} == {
        "Lavandula angustifolia",
        "Lavandula latifolia",
    }, "the disagreement is shown, not hidden"


def test_a_runner_up_is_never_as_confident_as_the_pick():
    candidates = rank_candidates(
        parse_name("Monstera deliciosa"),
        [
            result(
                "gbif",
                record("Monstera deliciosa", "gbif"),
                record("Monstera adansonii", "gbif", source_score=0.7),
            )
        ],
    )
    assert candidates[0].confidence == "high"
    assert candidates[1].confidence in {"medium", "low"}


def test_an_ambiguous_common_name_lands_lower_still():
    candidates = rank_candidates(
        parse_name("mandrake"),
        [
            result(
                "gbif",
                record(
                    "Mandragora officinarum",
                    "gbif",
                    match_kind="vernacular",
                    source_score=0.9,
                ),
                record(
                    "Mandragora autumnalis",
                    "gbif",
                    match_kind="vernacular",
                    source_score=0.89,
                ),
            )
        ],
    )
    assert candidates[0].confidence == "low"


def test_weak_candidates_are_dropped_rather_than_padded_out():
    candidates = rank_candidates(
        parse_name("Monstera deliciosa"),
        [
            result(
                "gbif",
                record("Monstera deliciosa", "gbif"),
                record(
                    "Something else", "gbif", match_kind="partial", source_score=0.2
                ),
            )
        ],
    )
    assert [c.accepted_name for c in candidates] == ["Monstera deliciosa"]


# ------------------------------------------------------------- resolving


def test_a_source_that_is_down_is_recorded_as_down_not_as_silence(run):
    resolver = TaxonResolver(
        [
            FakeConnector("powo", error="powo: HTTP 503"),
            FakeConnector("gbif", [record("Monstera deliciosa", "gbif")]),
        ]
    )
    resolution = run(resolver.resolve("Monstera deliciosa"))
    assert resolution.errors == {"powo": "powo: HTTP 503"}
    assert resolution.reachable, "one source answered"
    assert resolution.candidates[0].accepted_name == "Monstera deliciosa"


def test_every_source_down_is_not_an_answer_about_the_plant(run):
    resolver = TaxonResolver(
        [
            FakeConnector("powo", raises=RuntimeError("boom")),
            FakeConnector("gbif", error="gbif: timeout"),
        ]
    )
    resolution = run(resolver.resolve("Monstera deliciosa"))
    assert resolution.candidates == ()
    assert not resolution.reachable
    assert set(resolution.errors) == {"powo", "gbif"}


def test_an_empty_query_asks_nobody(run):
    resolver = TaxonResolver(
        [FakeConnector("gbif", raises=AssertionError("asked anyway"))]
    )
    resolution = run(resolver.resolve("   "))
    assert resolution.candidates == ()


def test_every_call_made_is_kept_with_its_payload_for_the_source_table(run):
    resolver = TaxonResolver(
        [FakeConnector("gbif", [record("Monstera deliciosa", "gbif")])]
    )
    resolution = run(resolver.resolve("Monstera deliciosa"))
    assert [s.kind for s in resolution.sources] == ["gbif"]
    assert resolution.sources[0].to_row()["payload"] == {"stub": True}
