"""Where a plate might already exist, and what a catalogue is allowed to tell us.

Three parts, the same shape the botany worker settled for taxon connectors in
`workers/botany/connectors/base.py`:

1. a **fetcher**, the only thing that touches the network, so every parser is
   testable against a recorded payload;
2. **pure parse functions** over a payload, returning :class:`PlateCandidate`s;
3. **connectors** binding the two.

A connector never decides what to publish. It reports what a catalogue said,
including when what the catalogue said was *nothing about the licence* — and
`pipeline.py` is the single place that turns candidates into plates or into a
named absence.

## The licence is the whole job

A catalogue search result is a claim by a stranger. Most of the fields on a
candidate below are decoration; ``license_raw`` is the only one the pipeline
is allowed to act on, and a candidate whose licence is missing, empty or
unrecognised is **discarded**. Not downgraded to `generated`, not stored with a
caveat, not approved-pending-review. Discarded, and the species is reported as
having no plate (`domain.py`, the no-invented-plant-facts rule).

## The roster, ordered by what a deployment can use

an earlier release found that the earlier roster's shape oversold what a default deployment would
find, and the design and §7 settled both halves:

* **Wikimedia Commons** — a public API, no credential, and `extmetadata`
  carries a per-file licence short name. **First on the roster**, because it is
  the one source a fresh deployment can actually use.
* **Biodiversity Heritage Library** — API v3 requires a key. the design says
  nothing may depend on a service the operator did not choose, so BHL is asked
  only when ``MOH_PLATES_BHL_API_KEY`` is set, and reports itself unavailable
  with its reason otherwise. Second, because a keyed BHL is the exception and
  the roster should not read as though it were the rule.
* **plantillustrations.org** — **off the roster**. No API, and no
  per-image licence statement this code could record, so every plate from it
  would be an `origin: public_domain` row with no `license` — precisely the
  unsupported claim §2 of `domain.py` refuses to store. A roster entry that can
  never produce a storable plate is a claim about coverage. It returns by design decision
  if it ever publishes per-image licences.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .domain import normalise_licence

#: Tried in order, and **the order is what a deployment can actually use**
#:. Wikimedia Commons needs no credential, so it is first; BHL
#: follows and is asked only when keyed. The earlier skeleton had BHL first, which
#: made a keyed BHL look like the normal state when it is the exception.
#:
#: The order plates are *preferred* in has not changed: the first clearly
#: licensed image still wins. What changed is the order sources are *tried* in,
#: which now matches the order they are available in.
PUBLIC_DOMAIN_SOURCES: tuple[str, ...] = (
    "wikimedia_commons",
    "biodiversity_heritage_library",
)

#: Every entry on the roster is implemented. ``plantillustrations_org`` was on
#: it and left by no API and no per-image licence statement,
#: so a roster entry that can never produce a storable plate is a claim about
#: coverage. The two names are kept separate because the distinction — declared
#: versus built — is one the next source will need again.
IMPLEMENTED_SOURCES: tuple[str, ...] = PUBLIC_DOMAIN_SOURCES

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
BHL_API = "https://www.biodiversitylibrary.org/api3"


@dataclass(frozen=True, slots=True)
class PlateCandidate:
    """What one catalogue offered, before anything has been fetched or stored.

    ``license_raw`` is what the catalogue said, verbatim and unnormalised, so a
    rejection can quote it back. :attr:`license` is the normalised form, or
    ``None`` when the catalogue's answer is not a licence this deployment shows.
    """

    source_kind: str
    image_url: str
    title: str | None = None
    license_raw: str | None = None
    attribution: str | None = None
    page_url: str | None = None

    @property
    def license(self) -> str | None:
        """The canonical licence, or ``None`` if this candidate cannot be stored."""
        return normalise_licence(self.license_raw)

    @property
    def is_usable(self) -> bool:
        return bool(self.image_url) and self.license is not None

    def rejection(self) -> str | None:
        """Why this candidate cannot become a plate, in a sentence, or ``None``.

        Written for a worker log and for the operator-facing coverage report,
        so it quotes the catalogue rather than summarising it.
        """
        if not self.image_url:
            return f"{self.source_kind} returned a record with no image to fetch."
        if self.license_raw is None:
            return (
                f"{self.source_kind} stated no licence for {self.title or 'this image'}, "
                "so recording it as public domain would be an unsupported claim."
            )
        if self.license is None:
            return (
                f"{self.source_kind} gave the licence as {self.license_raw!r}, which "
                "this deployment will not record or display."
            )
        return None


@runtime_checkable
class PlateFetcher(Protocol):
    """The only thing in this package allowed to touch the network."""

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> Any: ...

    async def get_bytes(self, kind: str, url: str) -> bytes: ...


@runtime_checkable
class PlateSource(Protocol):
    """One catalogue, asked about one plant."""

    kind: str

    def is_available(self) -> bool: ...

    def unavailable_reason(self) -> str | None: ...

    async def search(self, name: str, limit: int) -> Sequence[PlateCandidate]: ...


# --------------------------------------------------------------- parsing


def parse_commons(payload: Any) -> list[PlateCandidate]:
    """Candidates out of a Commons ``action=query&prop=imageinfo`` payload.

    Commons puts the licence in ``imageinfo[].extmetadata.LicenseShortName``
    and the credit in ``Artist``. Both are optional, and a file with neither is
    still returned by search — which is the case this parser must not smooth
    over, so a missing licence becomes ``license_raw=None`` and travels to the
    pipeline as a rejection rather than being dropped silently here.
    """
    pages = ((payload or {}).get("query") or {}).get("pages") or {}
    entries = pages.values() if isinstance(pages, dict) else pages
    out: list[PlateCandidate] = []
    for page in entries:
        if not isinstance(page, dict):
            continue
        for info in page.get("imageinfo") or []:
            if not isinstance(info, dict):
                continue
            meta = info.get("extmetadata") or {}
            out.append(
                PlateCandidate(
                    source_kind="wikimedia_commons",
                    image_url=str(info.get("url") or ""),
                    title=page.get("title"),
                    license_raw=_meta_value(meta, "LicenseShortName"),
                    attribution=_strip_markup(_meta_value(meta, "Artist")),
                    page_url=info.get("descriptionurl"),
                )
            )
    return out


def parse_bhl(payload: Any) -> list[PlateCandidate]:
    """Candidates out of a BHL ``op=GetPageMetadata`` / search payload.

    BHL's corpus is scanned pre-1923 literature, so its items are in the public
    domain by age — but *by age* is a conclusion, not a statement, and this
    parser does not draw it. It records what the ``Rights`` or ``License``
    field says; where BHL says nothing, the candidate arrives unlicensed and
    the pipeline refuses it. Guessing "it is old, therefore public domain"
    here is exactly the invented citation the no-invented-plant-facts rule exists to stop.
    """
    results = (payload or {}).get("Result") or []
    if isinstance(results, dict):
        results = [results]
    out: list[PlateCandidate] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        for image in item.get("Pages") or [item]:
            if not isinstance(image, dict):
                continue
            url = image.get("ItemThumbUrl") or image.get("FullSizeImageUrl") or ""
            out.append(
                PlateCandidate(
                    source_kind="biodiversity_heritage_library",
                    image_url=str(url),
                    title=item.get("Title") or image.get("PageTypes"),
                    license_raw=item.get("Rights") or item.get("License"),
                    attribution=_bhl_attribution(item),
                    page_url=image.get("ItemTextUrl") or item.get("ItemUrl"),
                )
            )
    return out


def _meta_value(meta: Mapping[str, Any], key: str) -> str | None:
    entry = meta.get(key)
    if isinstance(entry, Mapping):
        value = entry.get("value")
        return str(value) if value not in (None, "") else None
    return str(entry) if entry not in (None, "") else None


def _strip_markup(value: str | None) -> str | None:
    """Commons' ``Artist`` is HTML. A credit with a stray anchor in it is still
    a credit, but it is not one anybody should paste into a caption."""
    if value is None:
        return None
    out: list[str] = []
    depth = 0
    for character in value:
        if character == "<":
            depth += 1
        elif character == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(character)
    cleaned = " ".join("".join(out).split())
    return cleaned or None


def _bhl_attribution(item: Mapping[str, Any]) -> str | None:
    parts = [
        str(item[key])
        for key in ("Authors", "Title", "PublisherName", "PublicationDate")
        if item.get(key)
    ]
    return ", ".join(parts) or None


# ------------------------------------------------------------ connectors


class WikimediaCommonsSource:
    """Commons, which a fresh deployment can reach with no credential."""

    kind = "wikimedia_commons"

    def __init__(self, fetcher: PlateFetcher) -> None:
        self._fetcher = fetcher

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None

    async def search(self, name: str, limit: int) -> list[PlateCandidate]:
        payload = await self._fetcher.get_json(
            self.kind,
            COMMONS_API,
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                # Commons' own category for the historical plates this book
                # wants. A search of all of Commons returns photographs, which
                # are not what the house style is a style *of*.
                "gsrsearch": f'{name} incategory:"Botanical illustrations"',
                "gsrnamespace": "6",
                "gsrlimit": str(limit),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
            },
        )
        return parse_commons(payload)


class BiodiversityHeritageLibrarySource:
    """BHL, which needs a key the operator supplies or does not.

    nothing may depend on a service the operator did not choose. With
    no key this source reports itself unavailable and the pipeline moves on —
    it does not fail, and it does not become a reason to generate.
    """

    kind = "biodiversity_heritage_library"

    def __init__(self, fetcher: PlateFetcher, api_key: str | None) -> None:
        self._fetcher = fetcher
        self._api_key = api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    def unavailable_reason(self) -> str | None:
        if self._api_key:
            return None
        return (
            "The Biodiversity Heritage Library's API needs a key, so this "
            "deployment is not asking it. Set MOH_PLATES_BHL_API_KEY to a key "
            "you requested from BHL to include it (the design — the repository "
            "carries the name, never a value)."
        )

    async def search(self, name: str, limit: int) -> list[PlateCandidate]:
        if not self._api_key:
            return []
        payload = await self._fetcher.get_json(
            self.kind,
            BHL_API,
            {
                "op": "PublicationSearch",
                "searchterm": name,
                "searchtype": "F",
                "format": "json",
                "pageSize": str(limit),
                "apikey": self._api_key,
            },
        )
        return parse_bhl(payload)[:limit]
