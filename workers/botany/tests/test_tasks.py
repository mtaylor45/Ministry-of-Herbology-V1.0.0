"""The precedence table and the confidence arithmetic every other module shares."""

from workers.botany.tasks import (
    CONFIDENCE_ORDER,
    SOURCE_RANK,
    SourcedValue,
    WorkerSettings,
    choose,
    downgrade,
    resolve_taxon,
)


def value(kind, val="Monstera deliciosa"):
    return SourcedValue(field="accepted_name", value=val, source_kind=kind)


def test_the_precedence_order_is_the_one_the_brief_states():
    order = sorted(
        ("user", "powo", "gbif", "usda", "perenual", "wikidata", "wikipedia"),
        key=lambda k: SOURCE_RANK[k],
    )
    assert order == [
        "user",
        "powo",
        "gbif",
        "usda",
        "perenual",
        "wikidata",
        "wikipedia",
    ]
    assert SOURCE_RANK["other"] > max(SOURCE_RANK[k] for k in ("wikipedia", "wikidata"))


def test_nothing_sourced_is_unknown_and_not_a_guess():
    assert choose([]) == (None, "unknown")


def test_kew_outranks_the_aggregator():
    best, confidence = choose([value("gbif"), value("powo")])
    assert best.source_kind == "powo"
    assert confidence == "high"


def test_a_user_override_wins_outright():
    best, _ = choose([value("powo"), value("user", "Monstera adansonii")])
    assert best.source_kind == "user"


def test_two_trusted_sources_disagreeing_lowers_the_confidence():
    _, agreeing = choose([value("powo"), value("gbif")])
    _, disagreeing = choose([value("powo"), value("gbif", "Monstera adansonii")])
    assert agreeing == "high"
    assert disagreeing == "medium"


def test_an_unlisted_source_is_trusted_least():
    _, confidence = choose([value("nonesuch")])
    assert confidence == "low"


def test_confidence_only_ever_falls():
    assert CONFIDENCE_ORDER == ("high", "medium", "low", "unknown")
    assert downgrade("high") == "medium"
    assert downgrade("high", 2) == "low"
    assert downgrade("high", 99) == "unknown"
    assert downgrade("unknown") == "unknown"
    assert downgrade("high", 0) == "high"
    assert downgrade("nonsense") == "unknown"


def test_the_job_returns_contract_shaped_dictionaries(run):
    rows = run(resolve_taxon({}, "Monstera deliciosa"))
    assert isinstance(rows, list)
    assert rows[0]["accepted_name"] == "Monstera deliciosa"
    assert set(rows[0]) >= {"accepted_name", "confidence", "score", "source"}


def test_the_job_uses_a_resolver_handed_to_it(run):
    class StubResolver:
        def __init__(self):
            self.asked = []

        async def resolve(self, name):
            self.asked.append(name)

            class _Resolution:
                @staticmethod
                def to_list():
                    return [{"accepted_name": "Stub", "confidence": "unknown"}]

            return _Resolution()

    stub = StubResolver()
    assert (
        run(resolve_taxon({"resolver": stub}, "whatever"))[0]["accepted_name"] == "Stub"
    )
    assert stub.asked == ["whatever"]


def test_the_worker_still_registers_both_jobs():
    assert resolve_taxon in WorkerSettings.functions
    assert len(WorkerSettings.functions) == 2
