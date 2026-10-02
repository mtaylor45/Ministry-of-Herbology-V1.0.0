"""A plate may not claim what it did not earn.

module in this package is allowed to be wrong in a way that costs a picture,
and these are the ones where being wrong means the book shows a reader a
fabricated historical artefact and calls it a plate.
"""

from __future__ import annotations

import pytest

from workers.plates.domain import (
    ACCEPTABLE_LICENCES,
    Plate,
    ProvenanceError,
    is_usable_licence,
    normalise_licence,
)

SPECIES = "01890030-0000-7000-8000-00000000000a"
MEMBER = "01890050-0000-7000-8000-00000000000b"


def sourced(**overrides: object) -> Plate:
    """A well-formed public-domain plate, for tests that break one thing."""
    kwargs: dict[str, object] = {
        "id": "plate-1",
        "origin": "public_domain",
        "image_key": "plate-1.png",
        "species_id": SPECIES,
        "license": "public domain",
        "attribution": "A plate held by a library that stated the licence",
    }
    kwargs.update(overrides)
    return Plate(**kwargs)  # type: ignore[arg-type]


class TestAGeneratedPlateEarnsNoCredit:
    def test_a_generated_plate_may_not_carry_a_licence(self) -> None:
        with pytest.raises(ProvenanceError, match="has no licence"):
            Plate(
                id="p",
                origin="generated",
                image_key="p.png",
                species_id=SPECIES,
                license="public domain",
            )

    def test_a_generated_plate_may_not_carry_an_attribution(self) -> None:
        """The field a reader reads as a credit is the field that must stay empty."""
        with pytest.raises(ProvenanceError, match="no botanical attribution"):
            Plate(
                id="p",
                origin="generated",
                image_key="p.png",
                species_id=SPECIES,
                attribution="after Köhler",
            )

    def test_a_generated_plate_cites_no_source_row(self) -> None:
        with pytest.raises(ProvenanceError, match="cites no source"):
            Plate(
                id="p",
                origin="generated",
                image_key="p.png",
                species_id=SPECIES,
                source_id="01890020-0000-7000-8000-000000000004",
            )

    def test_a_generated_plate_is_well_formed_with_its_fields_empty(self) -> None:
        plate = Plate(
            id="p",
            origin="generated",
            image_key="p.png",
            species_id=SPECIES,
            style="nineteenth-century botanical plate",
        )
        assert plate.license is None
        assert plate.attribution is None
        assert plate.source_id is None

    def test_a_generated_plate_demands_the_label_reach_the_reader(self) -> None:
        """the design rule, in this release's place: on the plate, not behind a tooltip."""
        generated = Plate(
            id="p", origin="generated", image_key="p.png", species_id=SPECIES
        )
        assert generated.is_generated
        assert generated.needs_generated_label

    def test_a_sourced_plate_does_not_wear_the_generated_label(self) -> None:
        assert not sourced().needs_generated_label


class TestAnUnsupportedPublicDomainClaimIsRefused:
    def test_public_domain_with_no_licence_is_not_storable(self) -> None:
        with pytest.raises(ProvenanceError, match="unsupported claim"):
            sourced(license=None)

    def test_public_domain_with_an_empty_licence_is_not_storable(self) -> None:
        with pytest.raises(ProvenanceError, match="unsupported claim"):
            sourced(license="")

    def test_a_licence_this_deployment_will_not_show_is_refused(self) -> None:
        """Not downgraded, not shown with a caveat. Refused."""
        with pytest.raises(ProvenanceError, match="not a licence"):
            sourced(license="all rights reserved")

    def test_the_refusal_names_what_would_have_been_acceptable(self) -> None:
        with pytest.raises(ProvenanceError) as caught:
            sourced(license="cc by-nc")
        for licence in ACCEPTABLE_LICENCES:
            assert licence in str(caught.value)

    def test_a_user_upload_may_have_no_licence(self) -> None:
        """An operator's own photograph is theirs; nobody has to cite it."""
        plate = Plate(
            id="p", origin="user_upload", image_key="p.png", specimen_id=SPECIES
        )
        assert plate.license is None


class TestApprovalIsSomebodysAct:
    def test_a_plate_is_born_unapproved(self) -> None:
        plate = sourced()
        assert plate.approved is False
        assert plate.approved_by is None

    def test_approved_with_nobody_attached_is_refused(self) -> None:
        with pytest.raises(ProvenanceError, match="names who approved it"):
            sourced(approved=True)

    def test_an_approver_with_the_flag_unset_is_refused(self) -> None:
        with pytest.raises(ProvenanceError, match="half-recorded"):
            sourced(approved_by=MEMBER)

    def test_approve_records_the_member_and_the_flag_together(self) -> None:
        plate = sourced().approve(MEMBER)
        assert plate.approved is True
        assert plate.approved_by == MEMBER

    def test_approve_refuses_an_empty_approver(self) -> None:
        """The shape a pipeline would reach for if it wanted to approve."""
        with pytest.raises(ProvenanceError, match="somebody's act"):
            sourced().approve("")

    def test_unapprove_withdraws_the_name_with_the_flag(self) -> None:
        plate = sourced().approve(MEMBER).unapprove()
        assert plate.approved is False
        assert plate.approved_by is None

    def test_approval_does_not_mutate_the_plate_it_came_from(self) -> None:
        before = sourced()
        before.approve(MEMBER)
        assert before.approved is False


class TestAPlateHasToBelongToSomething:
    def test_a_plate_naming_neither_species_nor_specimen_is_refused(self) -> None:
        with pytest.raises(ProvenanceError, match="names neither"):
            Plate(id="p", origin="generated", image_key="p.png")

    def test_a_specimen_plate_needs_no_species(self) -> None:
        plate = Plate(
            id="p", origin="generated", image_key="p.png", specimen_id="spec-1"
        )
        assert plate.species_id is None

    def test_a_plate_with_no_image_is_refused(self) -> None:
        with pytest.raises(ProvenanceError, match="not a plate"):
            sourced(image_key="")

    def test_an_origin_outside_the_contract_is_refused(self) -> None:
        with pytest.raises(ProvenanceError, match="not one of the contract"):
            sourced(origin="scanned_by_hand")


class TestLicenceSpelling:
    @pytest.mark.parametrize("licence", ["public domain", "CC0", " cc by ", "CC BY-SA"])
    def test_usable_licences_survive_case_and_whitespace(self, licence: str) -> None:
        assert is_usable_licence(licence)

    @pytest.mark.parametrize(
        "licence", [None, "", "   ", "unknown", "cc by-nc", "courtesy of the library"]
    )
    def test_everything_else_is_not_a_licence(self, licence: str | None) -> None:
        assert not is_usable_licence(licence)

    def test_normalise_gives_one_spelling_so_one_book_has_one_label(self) -> None:
        assert normalise_licence("  Public Domain ") == "public domain"
        assert normalise_licence("CC BY") == "cc by"

    def test_a_version_is_kept_because_it_is_part_of_the_licence(self) -> None:
        assert normalise_licence("CC BY-SA 4.0") == "cc by-sa 4.0"
        assert normalise_licence("cc0 1.0") == "cc0 1.0"

    def test_a_non_commercial_clause_is_never_shortened_into_a_free_one(self) -> None:
        """The anchored pattern's whole job: "CC BY-NC" must not become "cc by"."""
        assert normalise_licence("CC BY-NC") is None
        assert normalise_licence("CC BY-NC-SA 4.0") is None
        assert normalise_licence("CC BY-ND") is None

    def test_a_versioned_licence_is_storable_on_a_plate(self) -> None:
        assert sourced(license="CC BY-SA 4.0").license == "CC BY-SA 4.0"

    def test_normalise_refuses_rather_than_guessing(self) -> None:
        assert normalise_licence("all rights reserved") is None
        assert normalise_licence(None) is None
