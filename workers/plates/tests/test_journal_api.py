"""The three contracted journal routes, and the two escalated ones.

builds against and what the releases demo is driven through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workers.plates.coverage import REASON_KINDS
from workers.plates.fixture_repository import (
    MOCK_ATTRIBUTION,
    OUTCOMES,
    reset_fixture_repository,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def fixture_species() -> list[dict]:
    """Read the fixtures rather than pinning a value out of them."""
    with (REPO_ROOT / "fixtures" / "species" / "species.json").open() as handle:
        return list(json.load(handle))


def fixture_specimens() -> list[dict]:
    with (REPO_ROOT / "fixtures" / "specimens" / "specimens.json").open() as handle:
        return list(json.load(handle))


def fixture_members() -> list[dict]:
    with (REPO_ROOT / "fixtures" / "members" / "members.json").open() as handle:
        return list(json.load(handle))


@pytest.fixture
def api():
    from app.main import app

    reset_fixture_repository()
    with TestClient(app) as client:
        yield client
    reset_fixture_repository()


class TestListingPlates:
    def test_the_journal_answers_at_all(self, api) -> None:
        """Retiring the 404 the journal README called "the honest state"."""
        response = api.get("/api/v1/journal/plates")
        assert response.status_code == 200
        assert response.json()

    def test_every_plate_carries_the_contracted_fields(self, api) -> None:
        for plate in api.get("/api/v1/journal/plates").json():
            assert plate["id"] and plate["image_url"]
            assert plate["origin"] in {"public_domain", "generated", "user_upload"}
            assert isinstance(plate["approved"], bool)

    def test_coverage_is_partial_on_purpose(self, api) -> None:
        """A mock where everything has a plate ships the absent state untested."""
        plates = api.get("/api/v1/journal/plates").json()
        with_plates = {p["species_id"] for p in plates}
        assert 0 < len(with_plates) < len(fixture_species())

    def test_the_approved_filter_narrows_and_does_not_invent(self, api) -> None:
        everything = api.get("/api/v1/journal/plates").json()
        approved = api.get("/api/v1/journal/plates", params={"approved": True}).json()
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()
        assert len(approved) + len(waiting) == len(everything)
        assert all(p["approved"] for p in approved)
        assert not any(p["approved"] for p in waiting)

    def test_some_plates_are_waiting_so_that_state_is_real(self, api) -> None:
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()
        assert waiting, "'awaiting approval' must be a state somebody has seen"

    def test_every_outcome_in_the_rotation_is_represented(self, api) -> None:
        plates = api.get("/api/v1/journal/plates").json()
        origins = {p["origin"] for p in plates}
        assert "public_domain" in origins
        assert "generated" in origins
        assert len(OUTCOMES) == 5


class TestWhatAPlateMayClaimOverHttp:
    def test_a_generated_plate_is_marked_and_uncredited_on_the_wire(self, api) -> None:
        """The field a developer sees. The visible label is `web/src/routes/journal/`."""
        plates = api.get("/api/v1/journal/plates").json()
        generated = [p for p in plates if p["origin"] == "generated"]
        assert generated
        for plate in generated:
            assert plate["license"] is None
            assert plate["attribution"] is None

    def test_a_public_domain_plate_always_carries_a_licence(self, api) -> None:
        """The schema's CHECK, asserted on the wire and not just in the DDL."""
        plates = api.get("/api/v1/journal/plates").json()
        sourced = [p for p in plates if p["origin"] == "public_domain"]
        assert sourced
        for plate in sourced:
            assert plate["license"], plate

    def test_no_mock_plate_credits_a_real_work_or_library(self, api) -> None:
        """A drawn stand-in under a real credit would be the forged artefact."""
        plates = api.get("/api/v1/journal/plates").json()
        credits = {p["attribution"] for p in plates if p["attribution"]}
        assert credits == {MOCK_ATTRIBUTION}
        for credit in credits:
            assert "not a scanned plate" in credit


class TestServingTheBytes:
    def test_a_plate_serves_a_real_image(self, api) -> None:
        plate = api.get("/api/v1/journal/plates").json()[0]
        response = api.get(plate["image_url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_a_thumbnail_is_smaller_than_the_plate(self, api) -> None:
        plate = next(
            p for p in api.get("/api/v1/journal/plates").json() if p["thumb_url"]
        )
        full = api.get(plate["image_url"]).content
        thumb = api.get(plate["thumb_url"]).content
        assert 0 < len(thumb) < len(full)

    def test_an_unknown_plate_is_a_404_not_a_stand_in(self, api) -> None:
        response = api.get(
            "/api/v1/journal/plates/01890060-0000-7000-8000-0000000000ff/image"
        )
        assert response.status_code == 404

    def test_an_unknown_variant_is_refused_rather_than_ignored(self, api) -> None:
        plate = api.get("/api/v1/journal/plates").json()[0]
        response = api.get(plate["image_url"], params={"variant": "enormous"})
        assert response.status_code == 422


class TestApproval:
    def test_a_member_can_approve_a_waiting_plate(self, api) -> None:
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()[
            0
        ]
        keeper = fixture_members()[0]["id"]
        response = api.post(
            f"/api/v1/journal/plates/{waiting['id']}/approve",
            json={"member_id": keeper},
        )
        assert response.status_code == 200
        assert response.json()["approved"] is True

    def test_an_approval_with_no_member_is_refused(self, api) -> None:
        """The whole point of the field: a decision with an author."""
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()[
            0
        ]
        response = api.post(f"/api/v1/journal/plates/{waiting['id']}/approve", json={})
        assert response.status_code == 422

    def test_an_approval_by_a_member_nobody_knows_is_refused(self, api) -> None:
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()[
            0
        ]
        response = api.post(
            f"/api/v1/journal/plates/{waiting['id']}/approve",
            json={"member_id": "01890050-0000-7000-8000-0000000000ff"},
        )
        assert response.status_code == 422

    def test_approving_an_unknown_plate_is_a_404(self, api) -> None:
        response = api.post(
            "/api/v1/journal/plates/01890060-0000-7000-8000-0000000000ff/approve",
            json={"member_id": fixture_members()[0]["id"]},
        )
        assert response.status_code == 404

    def test_approval_moves_the_plate_between_the_two_filters(self, api) -> None:
        waiting = api.get("/api/v1/journal/plates", params={"approved": False}).json()
        before = len(waiting)
        api.post(
            f"/api/v1/journal/plates/{waiting[0]['id']}/approve",
            json={"member_id": fixture_members()[0]["id"]},
        )
        after = api.get("/api/v1/journal/plates", params={"approved": False}).json()
        assert len(after) == before - 1


class TestFieldNotes:
    def test_a_specimen_lists_its_notes(self, api) -> None:
        specimen = fixture_specimens()[0]["id"]
        response = api.get(f"/api/v1/journal/{specimen}/notes")
        assert response.status_code == 200
        assert response.json()

    def test_a_seeded_note_says_who_wrote_it(self, api) -> None:
        specimen = fixture_specimens()[0]["id"]
        [note] = api.get(f"/api/v1/journal/{specimen}/notes").json()
        assert note["written_by"]["name"]

    def test_a_specimen_with_no_notes_answers_an_empty_list(self, api) -> None:
        specimen = fixture_specimens()[-1]["id"]
        assert api.get(f"/api/v1/journal/{specimen}/notes").json() == []

    def test_an_unknown_specimen_is_a_404(self, api) -> None:
        response = api.get("/api/v1/journal/01890040-0000-7000-8000-0000000000ff/notes")
        assert response.status_code == 404

    def test_a_note_can_be_written_and_comes_back(self, api) -> None:
        specimen = fixture_specimens()[1]["id"]
        response = api.post(
            f"/api/v1/journal/{specimen}/notes",
            json={"body": "Two new fronds since Tuesday."},
        )
        assert response.status_code == 201
        assert response.json()["body"] == "Two new fronds since Tuesday."
        assert api.get(f"/api/v1/journal/{specimen}/notes").json()

    def test_a_note_written_with_no_member_omits_the_author(self, api) -> None:
        """`FieldNote.written_by` is a bare $ref: null would break the contract."""
        specimen = fixture_specimens()[1]["id"]
        note = api.post(
            f"/api/v1/journal/{specimen}/notes", json={"body": "Anonymous."}
        ).json()
        assert "written_by" not in note

    def test_a_note_written_with_a_member_records_them(self, api) -> None:
        specimen = fixture_specimens()[1]["id"]
        keeper = fixture_members()[0]
        note = api.post(
            f"/api/v1/journal/{specimen}/notes",
            json={"body": "Repotted.", "member_id": keeper["id"]},
        ).json()
        assert note["written_by"]["id"] == keeper["id"]
        assert note["written_by"]["name"] == keeper["name"]

    def test_an_empty_note_is_refused(self, api) -> None:
        specimen = fixture_specimens()[1]["id"]
        response = api.post(f"/api/v1/journal/{specimen}/notes", json={"body": "   "})
        assert response.status_code == 422

    def test_a_note_for_an_unknown_specimen_is_a_404(self, api) -> None:
        response = api.post(
            "/api/v1/journal/01890040-0000-7000-8000-0000000000ff/notes",
            json={"body": "Nobody's plant."},
        )
        assert response.status_code == 404

    def test_a_note_by_an_unknown_member_is_refused(self, api) -> None:
        specimen = fixture_specimens()[1]["id"]
        response = api.post(
            f"/api/v1/journal/{specimen}/notes",
            json={"body": "x", "member_id": "01890050-0000-7000-8000-0000000000ff"},
        )
        assert response.status_code == 422


class TestTheMockKeepsNoSecretCoverage:
    def test_the_species_with_no_plate_have_a_stated_reason(self, api) -> None:
        """the design shape: the absence has to be able to speak."""
        from workers.plates.fixture_repository import fixture_repository

        repo = fixture_repository()
        plates = api.get("/api/v1/journal/plates").json()
        covered = {p["species_id"] for p in plates}
        missing = [s for s in fixture_species() if str(s["id"]) not in covered]
        assert missing
        for species in missing:
            assert repo.absence_reason(str(species["id"]))


class TestLiveModeHasNowhereToKeepPlatesUntilToldWhere:
    """The #46 pattern at the router: a 503 that names the variable.

    Mock mode never reaches this — it holds its own in-memory store, which is
    what lets the stack come up with no volume attached. These exercise the
    path a real deployment takes before an operator has mounted anything.
    """

    def test_the_store_refuses_rather_than_writing_into_a_container_layer(
        self, monkeypatch
    ) -> None:
        from workers.plates import config as plate_config
        from workers.plates.router import plate_store
        from workers.plates.storage import PlateStoreUnconfigured

        monkeypatch.delenv("MOH_PLATES_IMAGE_DIR", raising=False)
        plate_config.get_plate_settings.cache_clear()
        monkeypatch.setattr(
            plate_config, "get_plate_settings", lambda: plate_config.PlateSettings()
        )
        with pytest.raises(PlateStoreUnconfigured, match="MOH_PLATES_IMAGE_DIR"):
            plate_store()

    def test_the_refusal_says_where_the_volume_has_to_be_mounted(self) -> None:
        from workers.plates.router import _nowhere_to_keep_plates

        message = _nowhere_to_keep_plates()
        assert "MOH_PLATES_IMAGE_DIR" in message
        assert "survives a redeploy" in message

    def test_an_operator_who_names_a_directory_gets_a_filesystem_store(
        self, tmp_path, monkeypatch
    ) -> None:
        from workers.plates import config as plate_config
        from workers.plates.router import plate_store
        from workers.plates.storage import FilesystemPlateStore

        monkeypatch.setenv("MOH_PLATES_IMAGE_DIR", str(tmp_path))
        plate_config.get_plate_settings.cache_clear()
        store = plate_store()
        assert isinstance(store, FilesystemPlateStore)
        assert store.root == tmp_path


class TestTheWorkerNeverApproves:
    def test_the_job_reports_approved_false_rather_than_staying_silent(self) -> None:
        """A caller reading this dict must not mistake silence for approval."""
        from workers.plates.pipeline import PlateOutcome
        from workers.plates.tasks import _record

        outcome = PlateOutcome(kind="no_candidate", reason="Nothing was found.")
        assert _record({}, outcome, "Monstera deliciosa")["approved"] is False

    def test_the_roster_is_built_in_the_declared_order(self) -> None:
        """Commons first — the source a deployment can use."""
        from workers.plates.sources import PUBLIC_DOMAIN_SOURCES
        from workers.plates.tasks import build_sources

        kinds = [source.kind for source in build_sources(object())]
        assert kinds == list(PUBLIC_DOMAIN_SOURCES)
        assert kinds[0] == "wikimedia_commons"


class TestCoverageAgreesWithTheBookItFeeds:
    """The five counts must mean what `coverageSentence()` says they mean.

    The book view computes its own counts client-side from `/journal/plates`
    and `/specimens` (`web/src/routes/journal/plates.ts`). This route computes
    them server-side. Two implementations of one idea is two places to drift,
    and the drift would show up as a sentence above the book that disagrees
    with the page count under it.

    So these restate the book's rule independently — match a plate to a plant
    by specimen id first and species id second, never by anything else; count
    **plants**, not plates — and assert the route agrees.
    """

    @staticmethod
    def plate_for(specimen: dict, plates: list[dict]) -> dict | None:
        """The book's `buildPages()` rule, restated rather than imported."""
        own = next(
            (p for p in plates if p["specimen_id"] == specimen["id"]),
            None,
        )
        if own:
            return own
        species = (specimen.get("species") or {}).get("id")
        if not species:
            return None
        return next((p for p in plates if p["species_id"] == species), None)

    def test_the_counts_match_what_the_book_would_compute(self, api) -> None:
        plates = api.get("/api/v1/journal/plates").json()
        specimens = api.get("/api/v1/specimens", params={"limit": 200}).json()["items"]
        served = api.get("/api/v1/journal/coverage").json()

        paired = [(s, self.plate_for(s, plates)) for s in specimens]
        assert served["total"] == len(specimens)
        assert served["approved"] == sum(1 for _s, p in paired if p and p["approved"])
        assert served["waiting"] == sum(
            1 for _s, p in paired if p and not p["approved"]
        )
        assert served["absent"] == sum(1 for _s, p in paired if p is None)

    def test_generated_counts_plants_not_plates(self, api) -> None:
        """Two plants sharing one drawn plate are two plants shown a drawn picture.

        This is the count most likely to be got wrong, because counting the
        plates is the easier thing to write and reads correctly in isolation.
        """
        plates = api.get("/api/v1/journal/plates").json()
        specimens = api.get("/api/v1/specimens", params={"limit": 200}).json()["items"]
        served = api.get("/api/v1/journal/coverage").json()

        by_plant = sum(
            1
            for s in specimens
            if (p := self.plate_for(s, plates)) and p["origin"] == "generated"
        )
        by_plate = sum(1 for p in plates if p["origin"] == "generated")
        assert served["generated"] == by_plant
        assert by_plant != by_plate, (
            "the fixtures must keep a species with two specimens sharing one "
            "generated plate, or this test cannot tell the two counts apart"
        )

    def test_the_three_states_sum_to_the_total(self, api) -> None:
        served = api.get("/api/v1/journal/coverage").json()
        assert (
            served["approved"] + served["waiting"] + served["absent"]
            == served["total"]
            == len(served["specimens"])
        )

    def test_every_entry_names_its_plant(self, api) -> None:
        """`PlateCoverageEntry.specimen` is a required bare `$ref`."""
        for entry in api.get("/api/v1/journal/coverage").json()["specimens"]:
            assert entry["specimen"]["id"]
            assert entry["specimen"]["display_name"]

    def test_a_blank_leaf_always_says_which_case_it_is(self, api) -> None:
        absent = [
            e
            for e in api.get("/api/v1/journal/coverage").json()["specimens"]
            if e["state"] == "absent"
        ]
        assert absent, "mock mode keeps blank leaves on purpose"
        for entry in absent:
            assert entry["reason_kind"] in REASON_KINDS
            assert entry["reason"]
            assert entry["plate_id"] is None

    def test_a_leaf_with_a_plate_carries_no_reason(self, api) -> None:
        for entry in api.get("/api/v1/journal/coverage").json()["specimens"]:
            if entry["state"] == "absent":
                continue
            assert entry["plate_id"]
            assert entry["reason_kind"] is None
            assert entry["reason"] is None

    def test_the_entries_are_in_register_order(self, api) -> None:
        specimens = api.get("/api/v1/specimens", params={"limit": 200}).json()["items"]
        served = api.get("/api/v1/journal/coverage").json()["specimens"]
        assert [e["specimen"]["id"] for e in served] == [s["id"] for s in specimens]
