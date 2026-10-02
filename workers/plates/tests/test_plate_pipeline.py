"""The coverage target must not be able to lower a bar.

approved plate"*, and these are the tests that make the three ways of cheating
it fail: auto-approving, reusing another species' plate, and calling a
generated plate sourced.
"""

from __future__ import annotations

from typing import Any

import pytest

from workers.plates.config import PlateSettings
from workers.plates.domain import Plate
from workers.plates.generation import GenerationUnavailable
from workers.plates.mocks.plate_image import plate_png, seed_for
from workers.plates.pipeline import (
    PlateOutcome,
    SourcingRun,
    source_or_generate,
    source_plate,
)
from workers.plates.sources import PlateCandidate
from workers.plates.storage import MemoryPlateStore


def plate_settings(**overrides: Any) -> PlateSettings:
    """Settings built from nothing but what a test asks for.

    ``_env_file=None`` keeps a developer's stray ``.env`` out of the suite. The
    one ``type: ignore`` pydantic-settings' private keyword needs is written
    here rather than at every call site. (There are no ``__init__.py`` files
    under the test trees — see ``pytest.ini`` — so this cannot be imported from
    ``conftest.py``, and each module that needs it carries its own.)
    """
    return PlateSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


#: A real PNG, from mock mode's own encoder — see `mocks/plate_image.py` for
#: why the suite does not pass sentinels around.
PNG = plate_png(seed_for("a test plate"))
SPECIES = "01890030-0000-7000-8000-000000000001"


def settings(**overrides: object) -> PlateSettings:
    return plate_settings(image_dir=None, **overrides)


class StubSource:
    def __init__(
        self,
        kind: str,
        candidates: list[PlateCandidate] | None = None,
        *,
        available: bool = True,
        reason: str | None = None,
        explode: Exception | None = None,
    ) -> None:
        self.kind = kind
        self._candidates = candidates or []
        self._available = available
        self._reason = reason
        self._explode = explode
        self.searched = 0

    def is_available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str | None:
        return self._reason

    async def search(self, name: str, limit: int) -> list[PlateCandidate]:
        self.searched += 1
        if self._explode:
            raise self._explode
        return self._candidates


class StubFetcher:
    def __init__(self, image: bytes = PNG, explode: Exception | None = None) -> None:
        self.image = image
        self._explode = explode
        self.fetched: list[str] = []

    async def get_json(self, kind, url, params=None):
        return {}

    async def get_bytes(self, kind, url):
        self.fetched.append(url)
        if self._explode:
            raise self._explode
        return self.image


def licensed(url: str = "https://example.invalid/a.png") -> PlateCandidate:
    return PlateCandidate(
        source_kind="wikimedia_commons",
        image_url=url,
        title="A plate",
        license_raw="Public domain",
        attribution="A library that stated the licence",
    )


def unlicensed() -> PlateCandidate:
    return PlateCandidate(
        source_kind="wikimedia_commons",
        image_url="https://example.invalid/b.png",
        title="A plate with no stated licence",
    )


class TestAnOutcomeSpeaksEitherWay:
    def test_an_outcome_carrying_both_is_refused(self) -> None:
        plate = Plate(id="p", origin="generated", image_key="p.png", species_id=SPECIES)
        with pytest.raises(ValueError, match="never both"):
            PlateOutcome(kind="generated", plate=plate, reason="also a reason")

    def test_an_outcome_carrying_neither_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never both"):
            PlateOutcome(kind="no_candidate")

    def test_an_invented_outcome_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not an outcome"):
            PlateOutcome(kind="probably_fine", reason="x")


class TestSourcing:
    async def test_the_first_clearly_licensed_image_wins(self) -> None:
        store = MemoryPlateStore()
        source = StubSource("wikimedia_commons", [licensed()])
        outcome = await source_plate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            [source],
            StubFetcher(),
            store,
            settings(),
        )
        assert outcome.kind == "sourced"
        assert outcome.plate is not None
        assert outcome.plate.origin == "public_domain"
        assert outcome.plate.license == "public domain"
        assert outcome.plate.species_id == SPECIES
        assert len(store) == 1

    async def test_a_sourced_plate_is_not_approved(self) -> None:
        """The pipeline has nobody to put in `approved_by`, so it cannot."""
        outcome = await source_plate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.plate is not None
        assert outcome.plate.approved is False
        assert outcome.plate.approved_by is None

    async def test_an_unlicensed_candidate_is_skipped_and_the_reason_kept(self) -> None:
        store = MemoryPlateStore()
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [unlicensed()])],
            StubFetcher(),
            store,
            settings(),
        )
        assert outcome.kind == "unlicensed_candidate"
        assert not outcome.has_plate
        assert len(store) == 0, "nothing unlicensed reaches the volume"
        assert any("unsupported claim" in r for r in outcome.rejections)

    async def test_an_unlicensed_candidate_is_not_relabelled_as_generated(self) -> None:
        """Relabelling a found image would be a second lie about one picture."""
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [unlicensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.kind != "generated"
        assert outcome.plate is None

    async def test_a_licensed_candidate_after_an_unlicensed_one_still_wins(
        self,
    ) -> None:
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [unlicensed(), licensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.kind == "sourced"
        assert len(outcome.rejections) == 1

    async def test_sources_are_tried_in_the_order_given(self) -> None:
        first = StubSource("biodiversity_heritage_library", [licensed("first")])
        second = StubSource("wikimedia_commons", [licensed("second")])
        fetcher = StubFetcher()
        await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [first, second],
            fetcher,
            MemoryPlateStore(),
            settings(),
        )
        assert fetcher.fetched == ["first"]
        assert second.searched == 0

    async def test_an_unavailable_source_is_recorded_not_silently_passed(self) -> None:
        skipped = StubSource(
            "biodiversity_heritage_library",
            available=False,
            reason="BHL needs a key; set MOH_PLATES_BHL_API_KEY.",
        )
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [skipped],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.kind == "no_candidate"
        assert any("MOH_PLATES_BHL_API_KEY" in s for s in outcome.skipped_sources)
        assert skipped.searched == 0

    async def test_a_catalogue_that_is_down_is_not_a_reason_to_generate(self) -> None:
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", explode=RuntimeError("502"))],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert not outcome.has_plate
        assert any("not a reason to generate" in r for r in outcome.rejections)

    async def test_an_image_past_the_byte_bound_is_refused(self) -> None:
        store = MemoryPlateStore()
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(image=PNG + b"x" * 5000),
            store,
            settings(max_image_bytes=512),
        )
        assert not outcome.has_plate
        assert len(store) == 0
        assert any("bound" in r for r in outcome.rejections)

    async def test_bytes_that_are_not_an_image_never_reach_the_volume(self) -> None:
        store = MemoryPlateStore()
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(image=b'{"error": "not found"}'),
            store,
            settings(),
        )
        assert not outcome.has_plate
        assert len(store) == 0

    async def test_a_truncated_download_is_one_rejection_not_a_dead_run(self) -> None:
        """It used to raise straight out of here, killing a twelve-species run."""
        store = MemoryPlateStore()
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed(), licensed("good")])],
            StubFetcher(image=PNG[:12]),
            store,
            settings(),
        )
        assert not outcome.has_plate
        assert len(store) == 0
        assert any("truncated or corrupt" in r for r in outcome.rejections)

    async def test_an_image_that_cannot_be_fetched_is_recorded(self) -> None:
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(explode=TimeoutError("took too long")),
            MemoryPlateStore(),
            settings(),
        )
        assert not outcome.has_plate
        assert any("could not be fetched" in r for r in outcome.rejections)

    async def test_an_empty_roster_says_nobody_was_asked(self) -> None:
        outcome = await source_plate(
            SourcingRun("Something", species_id=SPECIES),
            [],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.kind == "no_candidate"
        assert outcome.reason is not None
        assert "Something" in outcome.reason


class TestTheGeneratedFallback:
    async def test_with_no_generator_the_answer_is_no_plate(self) -> None:
        """Not a placeholder. Not a reused plate. No plate."""
        outcome = await source_or_generate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [])],
            StubFetcher(),
            MemoryPlateStore(),
            generator=None,
            settings=settings(),
        )
        assert outcome.kind == "generation_unavailable"
        assert outcome.plate is None
        assert outcome.reason is not None
        assert "MOH_PLATES_GENERATOR_ENDPOINT" in outcome.reason

    async def test_a_configured_generator_is_not_asked_when_sourcing_worked(
        self,
    ) -> None:
        class Loud:
            async def generate(self, run, store, settings=None):
                raise AssertionError("sourcing succeeded; nothing should generate")

        outcome = await source_or_generate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            generator=Loud(),
            settings=settings(
                generator_endpoint="https://example.invalid/i",
                generator_api_key="k",
            ),
        )
        assert outcome.kind == "sourced"

    async def test_a_generated_plate_is_marked_generated_and_uncredited(self) -> None:
        class Drawing:
            async def generate(self, run, store, settings=None):
                return Plate(
                    id="01890060-0000-7000-8000-00000000000f",
                    origin="generated",
                    image_key="01890060-0000-7000-8000-00000000000f.png",
                    species_id=run.species_id,
                    style="a house style",
                )

        outcome = await source_or_generate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [])],
            StubFetcher(),
            MemoryPlateStore(),
            generator=Drawing(),
            settings=settings(
                generator_endpoint="https://example.invalid/i",
                generator_api_key="k",
            ),
        )
        assert outcome.kind == "generated"
        assert outcome.plate is not None
        assert outcome.plate.origin == "generated"
        assert outcome.plate.license is None
        assert outcome.plate.attribution is None
        assert outcome.plate.needs_generated_label
        assert outcome.plate.approved is False

    async def test_a_generator_that_fails_leaves_the_species_with_no_plate(
        self,
    ) -> None:
        class Failing:
            async def generate(self, run, store, settings=None):
                raise GenerationUnavailable("The generator returned nothing.")

        outcome = await source_or_generate(
            SourcingRun("Something", species_id=SPECIES),
            [StubSource("wikimedia_commons", [])],
            StubFetcher(),
            MemoryPlateStore(),
            generator=Failing(),
            settings=settings(
                generator_endpoint="https://example.invalid/i",
                generator_api_key="k",
            ),
        )
        assert outcome.kind == "generation_unavailable"
        assert outcome.plate is None

    async def test_the_sourcing_reason_survives_into_the_generation_reason(
        self,
    ) -> None:
        """A reader gets "nothing was found AND nothing can be drawn", not half of it."""
        outcome = await source_or_generate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            [StubSource("wikimedia_commons", [unlicensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            generator=None,
            settings=settings(),
        )
        assert outcome.reason is not None
        assert "licence" in outcome.reason
        assert "no image generator" in outcome.reason.lower()
        assert any("unsupported claim" in r for r in outcome.rejections)


class TestItCannotBorrowAnotherPlantsPicture:
    async def test_a_run_produces_a_plate_for_the_species_it_was_given(self) -> None:
        other = "01890030-0000-7000-8000-00000000000b"
        outcome = await source_plate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            [StubSource("wikimedia_commons", [licensed()])],
            StubFetcher(),
            MemoryPlateStore(),
            settings(),
        )
        assert outcome.plate is not None
        assert outcome.plate.species_id == SPECIES
        assert outcome.plate.species_id != other
