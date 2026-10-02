"""What a catalogue is allowed to tell us, and what it must not be able to imply.

a payload shaped like the documented API response.
"""

from __future__ import annotations

import pytest

from workers.plates.sources import (
    IMPLEMENTED_SOURCES,
    PUBLIC_DOMAIN_SOURCES,
    BiodiversityHeritageLibrarySource,
    PlateCandidate,
    WikimediaCommonsSource,
    parse_bhl,
    parse_commons,
)
from workers.plates.tasks import build_sources


class StubFetcher:
    """Records what was asked and answers with a payload the test chose."""

    def __init__(self, payload: object = None, image: bytes = b"") -> None:
        self.payload = payload
        self.image = image
        self.json_calls: list[tuple[str, str, dict]] = []

    async def get_json(self, kind, url, params=None):
        self.json_calls.append((kind, url, dict(params or {})))
        return self.payload

    async def get_bytes(self, kind, url):
        return self.image


def commons_payload(**extmetadata: object) -> dict:
    return {
        "query": {
            "pages": {
                "1234": {
                    "title": "File:A plate of something.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.example.invalid/a.jpg",
                            "descriptionurl": "https://commons.example.invalid/a",
                            "extmetadata": extmetadata,
                        }
                    ],
                }
            }
        }
    }


class TestTheRoster:
    """Properties, not a literal.

    The earlier version of this class asserted the exact tuple, which made the design
    §6's reorder look like a regression rather than the decision it was. These
    assert what the roster has to be *true of*, so the next source added has to
    satisfy the rules rather than edit a copy of the answer.
    """

    def test_the_first_source_needs_no_credential(self) -> None:
        """the roster is ordered by what a deployment can use.

        A roster whose first entry needs a key nobody has read as though a
        keyed BHL were the normal state. It is the exception.
        """
        first = build_sources(StubFetcher())[0]
        assert first.kind == PUBLIC_DOMAIN_SOURCES[0]
        assert first.is_available()
        assert first.unavailable_reason() is None

    def test_every_declared_source_is_built(self) -> None:
        """A roster entry nothing implements is a claim about coverage."""
        assert set(IMPLEMENTED_SOURCES) == set(PUBLIC_DOMAIN_SOURCES)
        assert [s.kind for s in build_sources(StubFetcher())] == list(
            PUBLIC_DOMAIN_SOURCES
        )

    def test_a_source_that_cannot_state_a_licence_is_not_on_it(self) -> None:
        """the design. It comes back by design decision if it ever publishes licences."""
        assert "plantillustrations_org" not in PUBLIC_DOMAIN_SOURCES

    def test_every_source_can_say_whether_it_is_available(self) -> None:
        """An unavailable source is skipped with its reason, never silently."""
        for source in build_sources(StubFetcher()):
            assert source.is_available() or source.unavailable_reason()


class TestCommonsParsing:
    def test_a_licensed_file_becomes_a_usable_candidate(self) -> None:
        payload = commons_payload(
            LicenseShortName={"value": "Public domain"},
            Artist={"value": "A nineteenth-century lithographer"},
        )
        [candidate] = parse_commons(payload)
        assert candidate.source_kind == "wikimedia_commons"
        assert candidate.image_url == "https://upload.example.invalid/a.jpg"
        assert candidate.license == "public domain"
        assert candidate.is_usable
        assert candidate.rejection() is None

    def test_html_in_the_credit_is_stripped_not_pasted_into_a_caption(self) -> None:
        payload = commons_payload(
            LicenseShortName={"value": "CC0"},
            Artist={"value": '<a href="/wiki/User:X" title="x">Some Scanner</a>'},
        )
        [candidate] = parse_commons(payload)
        assert candidate.attribution == "Some Scanner"

    def test_a_file_with_no_licence_is_kept_as_a_rejection_not_dropped(self) -> None:
        """Dropping it here would turn "we refused one" into "there were none"."""
        [candidate] = parse_commons(commons_payload(Artist={"value": "Somebody"}))
        assert candidate.license_raw is None
        assert not candidate.is_usable
        assert "unsupported claim" in (candidate.rejection() or "")

    def test_a_licence_we_do_not_show_is_quoted_back_in_the_rejection(self) -> None:
        payload = commons_payload(LicenseShortName={"value": "CC BY-NC 4.0"})
        [candidate] = parse_commons(payload)
        rejection = candidate.rejection() or ""
        assert "CC BY-NC 4.0" in rejection
        assert "will not record or display" in rejection

    def test_an_empty_payload_yields_nothing_and_does_not_explode(self) -> None:
        assert parse_commons({}) == []
        assert parse_commons(None) == []
        assert parse_commons({"query": {"pages": {}}}) == []

    def test_a_record_with_no_image_url_is_rejected_for_that_reason(self) -> None:
        payload = {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:x.jpg",
                        "imageinfo": [
                            {"extmetadata": {"LicenseShortName": {"value": "CC0"}}}
                        ],
                    }
                }
            }
        }
        [candidate] = parse_commons(payload)
        assert "no image to fetch" in (candidate.rejection() or "")


class TestBhlParsing:
    def test_age_is_never_turned_into_a_licence(self) -> None:
        """BHL's corpus is old. "Old" is a conclusion, and this parser draws none."""
        payload = {
            "Result": [
                {
                    "Title": "A flora of somewhere",
                    "PublicationDate": "1887",
                    "Authors": "An author",
                    "Pages": [{"FullSizeImageUrl": "https://bhl.example.invalid/1"}],
                }
            ]
        }
        [candidate] = parse_bhl(payload)
        assert candidate.license_raw is None
        assert not candidate.is_usable
        assert "unsupported claim" in (candidate.rejection() or "")

    def test_a_stated_rights_field_is_recorded(self) -> None:
        payload = {
            "Result": [
                {
                    "Title": "A flora of somewhere",
                    "Rights": "Public domain",
                    "Authors": "An author",
                    "Pages": [{"FullSizeImageUrl": "https://bhl.example.invalid/1"}],
                }
            ]
        }
        [candidate] = parse_bhl(payload)
        assert candidate.license == "public domain"
        assert candidate.attribution is not None
        assert "An author" in candidate.attribution

    def test_an_empty_result_yields_nothing(self) -> None:
        assert parse_bhl({"Result": []}) == []
        assert parse_bhl({}) == []


class TestCommonsConnector:
    async def test_it_asks_commons_for_botanical_illustrations(self) -> None:
        fetcher = StubFetcher(commons_payload(LicenseShortName={"value": "CC0"}))
        source = WikimediaCommonsSource(fetcher)
        candidates = await source.search("Monstera deliciosa", 6)
        assert len(candidates) == 1
        _kind, _url, params = fetcher.json_calls[0]
        assert "Monstera deliciosa" in params["gsrsearch"]
        assert "Botanical illustrations" in params["gsrsearch"]
        assert params["gsrlimit"] == "6"

    def test_it_needs_no_credential(self) -> None:
        """The one source a fresh deployment can actually reach."""
        source = WikimediaCommonsSource(StubFetcher())
        assert source.is_available()
        assert source.unavailable_reason() is None


class TestBhlConnector:
    def test_with_no_key_it_reports_itself_unavailable(self) -> None:
        source = BiodiversityHeritageLibrarySource(StubFetcher(), None)
        assert not source.is_available()
        reason = source.unavailable_reason() or ""
        assert "MOH_PLATES_BHL_API_KEY" in reason

    async def test_with_no_key_it_asks_nothing_rather_than_failing(self) -> None:
        fetcher = StubFetcher({"Result": []})
        source = BiodiversityHeritageLibrarySource(fetcher, None)
        assert await source.search("Monstera deliciosa", 6) == []
        assert fetcher.json_calls == []

    async def test_with_a_key_it_sends_the_key_and_asks(self) -> None:
        fetcher = StubFetcher({"Result": []})
        source = BiodiversityHeritageLibrarySource(fetcher, "operator-supplied")
        await source.search("Monstera deliciosa", 3)
        _kind, _url, params = fetcher.json_calls[0]
        assert params["apikey"] == "operator-supplied"
        assert params["searchterm"] == "Monstera deliciosa"

    def test_with_a_key_it_has_no_reason_to_give(self) -> None:
        source = BiodiversityHeritageLibrarySource(StubFetcher(), "k")
        assert source.is_available()
        assert source.unavailable_reason() is None


class TestCandidateLicensing:
    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "unknown",
            "CC BY-NC",
            # The one a looser matcher would wave through as "cc by".
            "CC BY-NC-SA 4.0",
            "All rights reserved",
            # A real Commons tag nobody whitelisted. Costs a plate on purpose.
            "PD-old-100",
        ],
    )
    def test_nothing_unlicensed_is_ever_usable(self, raw: str | None) -> None:
        candidate = PlateCandidate(
            source_kind="wikimedia_commons",
            image_url="https://example.invalid/a.png",
            license_raw=raw,
        )
        assert not candidate.is_usable
        assert candidate.license is None
        assert candidate.rejection() is not None

    @pytest.mark.parametrize(
        ("raw", "stored"),
        [
            ("Public domain", "public domain"),
            ("CC0", "cc0"),
            ("cc by", "cc by"),
            # The spelling Commons actually uses. Rejecting this for want of a
            # version suffix would have thrown away most of the licensed plates
            # on Commons, so the version is recognised and kept.
            ("CC BY-SA 4.0 ", "cc by-sa 4.0"),
            ("CC BY 3.0", "cc by 3.0"),
        ],
    )
    def test_the_licence_families_pass_and_keep_their_version(
        self, raw: str, stored: str
    ) -> None:
        candidate = PlateCandidate(
            source_kind="wikimedia_commons",
            image_url="https://example.invalid/a.png",
            license_raw=raw,
        )
        assert candidate.is_usable
        assert candidate.license == stored
