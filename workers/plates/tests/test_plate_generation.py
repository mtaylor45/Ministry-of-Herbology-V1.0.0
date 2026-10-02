"""A generated plate must never be able to pass as a historical illustration.

that make an image *claim* a provenance, and the row must refuse to carry a
credit it did not earn.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from workers.plates.config import PlateSettings
from workers.plates.generation import GenerationUnavailable, HttpPlateGenerator
from workers.plates.mocks.plate_image import plate_png, seed_for
from workers.plates.pipeline import SourcingRun
from workers.plates.storage import MemoryPlateStore
from workers.plates.style import (
    FORBIDDEN_MARKS,
    FORBIDDEN_THEME,
    HOUSE_STYLE,
    prompt_for,
)


def plate_settings(**overrides: Any) -> PlateSettings:
    """Settings built from nothing but what a test asks for.

    ``_env_file=None`` keeps a developer's stray ``.env`` out of the suite. The
    one ``type: ignore`` pydantic-settings' private keyword needs is written
    here rather than at every call site. (There are no ``__init__.py`` files
    under the test trees — see ``pytest.ini`` — so this cannot be imported from
    ``conftest.py``, and each module that needs it carries its own.)
    """
    return PlateSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


PNG = plate_png(seed_for("generated"))
SPECIES = "01890030-0000-7000-8000-000000000001"


def configured(**overrides: object) -> PlateSettings:
    base: dict[str, object] = {
        "generator_endpoint": "https://whatever-the-operator-chose.invalid/images",
        "generator_api_key": "an-operator-supplied-key",
    }
    base.update(overrides)
    return plate_settings(**base)


class StubGeneratorFetcher:
    def __init__(self, image: bytes = PNG, explode: Exception | None = None) -> None:
        self.image = image
        self._explode = explode
        self.calls: list[dict] = []

    async def generate_image(self, *, endpoint, api_key, model, prompt):
        self.calls.append(
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "model": model,
                "prompt": prompt,
            }
        )
        if self._explode:
            raise self._explode
        return self.image


class TestThePromptRefusesTheMarksThatClaimAProvenance:
    def test_every_forbidden_mark_reaches_the_prompt(self) -> None:
        prompt = prompt_for("Monstera deliciosa")
        for mark in FORBIDDEN_MARKS:
            assert mark in prompt

    def test_rule_seven_is_stated_to_the_model_not_only_to_ourselves(self) -> None:
        prompt = prompt_for("Monstera deliciosa")
        for clause in FORBIDDEN_THEME:
            assert clause in prompt

    def test_the_marks_that_matter_most_are_named(self) -> None:
        """A reader who sees "Pl. XIV" has been told this came out of a book."""
        prompt = prompt_for("Monstera deliciosa").lower()
        for mark in ("plate number", "signature", "stamp", "imprint", "foxing"):
            assert mark in prompt

    def test_the_prompt_is_built_only_from_the_declared_constants(self) -> None:
        """A structural guarantee, not a word blacklist: there is no other path
        for a stray reference to enter, so the original-theme rule is checked once, here.
        """
        prompt = prompt_for("Monstera deliciosa")
        remainder = prompt.replace("Monstera deliciosa", "", 1)
        remainder = remainder.replace(HOUSE_STYLE, "", 1)
        for clause in (*FORBIDDEN_MARKS, *FORBIDDEN_THEME):
            remainder = remainder.replace(clause, "", 1)
        assert remainder.strip(" .,") == ""

    def test_the_house_style_is_the_one_s0_wrote(self) -> None:
        assert HOUSE_STYLE.startswith("nineteenth-century botanical plate")
        assert "no text, no border, no signature" in HOUSE_STYLE

    def test_the_prompt_asserts_nothing_about_the_plant_but_its_name(self) -> None:
        """Anything else would be an invented plant fact in picture form."""
        prompt = prompt_for("Monstera deliciosa")
        assert prompt.startswith("Monstera deliciosa.")

    def test_a_cited_habit_may_be_passed_through(self) -> None:
        prompt = prompt_for("Monstera deliciosa", habit="climbing")
        assert prompt.startswith("Monstera deliciosa, climbing.")

    def test_an_empty_name_is_refused_rather_than_drawn(self) -> None:
        with pytest.raises(ValueError, match="picture of nothing"):
            prompt_for("   ")


class TestGenerationIsOffWithoutAnOperatorsChoice:
    async def test_a_fresh_deployment_raises_rather_than_drawing(self) -> None:
        generator = HttpPlateGenerator(StubGeneratorFetcher())
        with pytest.raises(GenerationUnavailable, match="MOH_PLATES_GENERATOR"):
            await generator.generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                MemoryPlateStore(),
                plate_settings(),
            )

    async def test_nothing_is_stored_when_it_is_off(self) -> None:
        store = MemoryPlateStore()
        generator = HttpPlateGenerator(StubGeneratorFetcher())
        with pytest.raises(GenerationUnavailable):
            await generator.generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                store,
                plate_settings(),
            )
        assert len(store) == 0

    async def test_the_endpoint_is_never_asked_when_it_is_off(self) -> None:
        fetcher = StubGeneratorFetcher()
        with pytest.raises(GenerationUnavailable):
            await HttpPlateGenerator(fetcher).generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                MemoryPlateStore(),
                plate_settings(),
            )
        assert fetcher.calls == []


class TestAConfiguredGenerator:
    async def test_it_produces_a_labelled_uncredited_plate(self) -> None:
        store = MemoryPlateStore()
        plate = await HttpPlateGenerator(StubGeneratorFetcher()).generate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            store,
            configured(),
        )
        assert plate.origin == "generated"
        assert plate.license is None
        assert plate.attribution is None
        assert plate.source_id is None
        assert plate.needs_generated_label
        assert len(store) == 1

    async def test_it_records_the_style_that_actually_made_the_image(self) -> None:
        """The frozen `style` column, so "what made this" has an answer."""
        plate = await HttpPlateGenerator(StubGeneratorFetcher()).generate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            MemoryPlateStore(),
            configured(),
        )
        assert plate.style == HOUSE_STYLE

    async def test_it_does_not_approve_what_it_drew(self) -> None:
        plate = await HttpPlateGenerator(StubGeneratorFetcher()).generate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            MemoryPlateStore(),
            configured(),
        )
        assert plate.approved is False
        assert plate.approved_by is None

    async def test_it_sends_the_operators_endpoint_and_model(self) -> None:
        fetcher = StubGeneratorFetcher()
        await HttpPlateGenerator(fetcher).generate(
            SourcingRun("Monstera deliciosa", species_id=SPECIES),
            MemoryPlateStore(),
            configured(generator_model="whatever-they-picked"),
        )
        assert fetcher.calls[0]["model"] == "whatever-they-picked"
        assert "whatever-the-operator-chose.invalid" in fetcher.calls[0]["endpoint"]

    async def test_an_empty_response_is_no_plate_not_an_empty_plate(self) -> None:
        store = MemoryPlateStore()
        with pytest.raises(GenerationUnavailable, match="not a plate"):
            await HttpPlateGenerator(StubGeneratorFetcher(image=b"")).generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                store,
                configured(),
            )
        assert len(store) == 0

    async def test_a_json_error_document_is_never_stored_as_a_picture(self) -> None:
        store = MemoryPlateStore()
        with pytest.raises(GenerationUnavailable, match="not a PNG or a JPEG"):
            await HttpPlateGenerator(
                StubGeneratorFetcher(image=b'{"error":"quota"}')
            ).generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                store,
                configured(),
            )
        assert len(store) == 0

    async def test_a_generator_that_errors_leaves_nothing_behind(self) -> None:
        store = MemoryPlateStore()
        with pytest.raises(GenerationUnavailable, match="Nothing was stored"):
            await HttpPlateGenerator(
                StubGeneratorFetcher(explode=RuntimeError("502 from the provider"))
            ).generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                store,
                configured(),
            )
        assert len(store) == 0

    async def test_the_failure_message_does_not_quote_the_key(self) -> None:
        """A credential in an exception string ends up in a log."""
        try:
            await HttpPlateGenerator(
                StubGeneratorFetcher(explode=RuntimeError("an-operator-supplied-key"))
            ).generate(
                SourcingRun("Monstera deliciosa", species_id=SPECIES),
                MemoryPlateStore(),
                configured(),
            )
        except GenerationUnavailable as exc:
            assert "an-operator-supplied-key" not in str(exc)
        else:  # pragma: no cover
            pytest.fail("expected GenerationUnavailable")


class TestDecodingWhateverTheProviderSent:
    def test_a_base64_images_payload_is_decoded(self) -> None:
        from workers.plates.fetcher import _decode_image_payload

        payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
        assert _decode_image_payload(payload) == PNG

    def test_a_half_understood_payload_becomes_no_plate(self) -> None:
        from workers.plates.fetcher import _decode_image_payload

        assert (
            _decode_image_payload({"data": [{"url": "https://x.invalid/a.png"}]}) == b""
        )
        assert _decode_image_payload({"error": "quota"}) == b""
        assert _decode_image_payload("not json at all") == b""

    def test_undecodable_base64_is_not_stored_as_bytes(self) -> None:
        from workers.plates.fetcher import _decode_image_payload

        assert (
            _decode_image_payload({"data": [{"b64_json": "!!!not base64!!!"}]}) == b""
        )
