"""Turning a plant into a plate, or into a sentence saying why there isn't one.

One function matters here — :func:`source_or_generate` — and the shape of its
return type is the releases's main argument. It does not return
``Plate | None``. It returns a :class:`PlateOutcome`, which carries either a
plate or **the reason there is none**, because this project has decided three
times already that an absence has to be able to speak:

* the design gave `/almanac/frost` an envelope, because "a list of alerts
  cannot say *and these three I could not judge*".
* the design gave `MorningRounds` an `unscheduled[]`, because a plant with no
  task is indistinguishable from a plant that needs nothing.
* Here: a species with no plate is indistinguishable from a species nobody
  asked about, unless the pipeline says which.

The exit criterion for this release is *"each specimen has an approved plate"*,
which is a coverage target, and a coverage target is the classic reason to
lower a bar. The three bars this module will not lower:

1. **It never sets `approved`.** It cannot — :meth:`Plate.approve` takes a
   member id and a worker has nobody to put in it.
2. **It never reuses another species' plate.** A plate names its species, and
   borrowing a congener's picture is a wrong answer that looks like a right
   one. :func:`source_or_generate` is given one species and returns a plate of
   that species or nothing.
3. **It never calls a generated plate sourced.** Generation is a separate
   branch with a separate origin, and if generation is unavailable the outcome
   is :data:`NO_PLATE` with the reason attached.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import storage
from .config import (
    PlateSettings,
    generation_is_configured,
    generation_unavailable_reason,
    get_plate_settings,
)
from .domain import Plate, ProvenanceError
from .generation import GenerationUnavailable, PlateGenerator
from .sources import PlateCandidate, PlateFetcher, PlateSource

#: How a sourcing attempt ended, for the coverage report and the book view.
#: ``sourced`` and ``generated`` produced a plate; the rest did not, and each
#: names a different thing to do about it.
OUTCOME_KINDS = (
    "sourced",
    "generated",
    "no_candidate",
    "unlicensed_candidate",
    "generation_unavailable",
    "unusable_image",
)


@dataclass(frozen=True, slots=True)
class PlateOutcome:
    """A plate, or the reason there is none. Never both, never neither.

    The same bargain `Fetched<T>` makes on the web side: a caller cannot read
    the happy path without having been handed the unhappy one.
    """

    kind: str
    plate: Plate | None = None
    reason: str | None = None
    #: Every candidate that was looked at and refused, with why. Kept so the
    #: coverage report can say "Commons had one and its licence was 'cc by-nc'"
    #: rather than the uninformative "not found".
    rejections: tuple[str, ...] = ()
    #: Sources that were not asked at all, and why not. A source off for want
    #: of a credential is a different fact from a source that had nothing.
    skipped_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in OUTCOME_KINDS:
            raise ValueError(f"{self.kind!r} is not an outcome this pipeline reports.")
        if (self.plate is None) == (self.reason is None):
            raise ValueError(
                "An outcome carries a plate or a reason, never both and never "
                "neither — that is the whole point of the type."
            )

    @property
    def has_plate(self) -> bool:
        return self.plate is not None


@dataclass
class SourcingRun:
    """One pass over the roster for one plant, accumulating what it learned."""

    name: str
    species_id: str | None = None
    specimen_id: str | None = None
    rejections: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


async def source_plate(
    run: SourcingRun,
    sources: Sequence[PlateSource],
    fetcher: PlateFetcher,
    store: storage.PlateImageStore,
    settings: PlateSettings | None = None,
) -> PlateOutcome:
    """Try each catalogue in order. The first clearly licensed image wins.

    "Clearly licensed" is the only ranking this does. A prettier plate with no
    licence loses to a plainer one that has it, because the licence is not a
    tiebreaker — it is the condition of the plate existing at all.
    """
    settings = settings or get_plate_settings()
    for source in sources:
        if not source.is_available():
            reason = source.unavailable_reason()
            if reason:
                run.skipped.append(reason)
            continue
        try:
            candidates = await source.search(run.name, settings.max_candidates)
        except Exception as exc:  # noqa: BLE001 — see below
            # Deliberately blind. `PlateSource` is a Protocol: an
            # implementation may raise anything its HTTP client raises, and
            # one catalogue being down must cost one rejection rather than the
            # whole run. Narrowing this would reintroduce exactly the bug the
            # truncated-download fix removed.
            run.rejections.append(
                f"{source.kind} could not be asked about {run.name}: {exc}. "
                "Treated as having nothing, which is not a reason to generate."
            )
            continue
        for candidate in candidates:
            rejection = candidate.rejection()
            if rejection is not None:
                run.rejections.append(rejection)
                continue
            outcome = await _store_candidate(run, candidate, fetcher, store, settings)
            if outcome is not None:
                return outcome

    if run.rejections:
        return PlateOutcome(
            kind="unlicensed_candidate",
            reason=(
                f"Nothing with a licence this deployment can record was found for "
                f"{run.name}, so it has no plate."
            ),
            rejections=tuple(run.rejections),
            skipped_sources=tuple(run.skipped),
        )
    return PlateOutcome(
        kind="no_candidate",
        reason=f"No public-domain catalogue this deployment asked had a plate of {run.name}.",
        skipped_sources=tuple(run.skipped),
    )


async def _store_candidate(
    run: SourcingRun,
    candidate: PlateCandidate,
    fetcher: PlateFetcher,
    store: storage.PlateImageStore,
    settings: PlateSettings,
) -> PlateOutcome | None:
    """Fetch, measure, store, and build the row — or record why not and return None."""
    try:
        data = await fetcher.get_bytes(candidate.source_kind, candidate.image_url)
    except Exception as exc:  # noqa: BLE001 — a fetcher may raise anything
        run.rejections.append(
            f"{candidate.source_kind} offered {candidate.image_url} and it could "
            f"not be fetched: {exc}."
        )
        return None

    if len(data) > settings.max_image_bytes:
        run.rejections.append(
            f"{candidate.source_kind} offered an image of {len(data):,} bytes, past "
            f"this deployment's {settings.max_image_bytes:,}-byte bound."
        )
        return None

    try:
        extension = storage.sniff_extension(data)
        _check_pixel_bound(data, settings.max_image_pixels)
    except (storage.UnsupportedImageFormat, UnusableImage, ImageTooLarge) as exc:
        run.rejections.append(f"{candidate.source_kind} offered {exc}")
        return None

    plate_id = str(uuid.uuid4())
    key = storage.key_for(plate_id, extension)
    try:
        store.put(key, data)
    except storage.PlateStoreFull as exc:
        return PlateOutcome(
            kind="unusable_image",
            reason=str(exc),
            rejections=tuple(run.rejections),
            skipped_sources=tuple(run.skipped),
        )

    try:
        plate = Plate(
            id=plate_id,
            origin="public_domain",
            image_key=key,
            species_id=run.species_id,
            specimen_id=run.specimen_id,
            license=candidate.license,
            attribution=candidate.attribution,
        )
    except ProvenanceError as exc:
        # Belt and braces: `candidate.rejection()` should have caught this.
        # Reaching here means a parser produced something inconsistent, and the
        # bytes are dropped rather than left orphaned on the volume.
        store.delete(key)
        run.rejections.append(f"{candidate.source_kind}: {exc}")
        return None

    return PlateOutcome(
        kind="sourced",
        plate=plate,
        rejections=tuple(run.rejections),
        skipped_sources=tuple(run.skipped),
    )


async def source_or_generate(
    run: SourcingRun,
    sources: Sequence[PlateSource],
    fetcher: PlateFetcher,
    store: storage.PlateImageStore,
    generator: PlateGenerator | None = None,
    settings: PlateSettings | None = None,
) -> PlateOutcome:
    """Public-domain sourcing first; generation only if an operator chose one.

    The order is not a preference, it is the rule: a real plate with real
    provenance beats a drawn one every time, and the drawn one exists for the
    plants the historical record missed.
    """
    settings = settings or get_plate_settings()
    sourced = await source_plate(run, sources, fetcher, store, settings)
    if sourced.has_plate:
        return sourced

    if generator is None or not generation_is_configured(settings):
        return PlateOutcome(
            kind="generation_unavailable",
            reason=(
                f"{sourced.reason} " f"{generation_unavailable_reason(settings) or ''}"
            ).strip(),
            rejections=sourced.rejections,
            skipped_sources=sourced.skipped_sources,
        )

    try:
        plate = await generator.generate(run, store, settings)
    except GenerationUnavailable as exc:
        return PlateOutcome(
            kind="generation_unavailable",
            reason=f"{sourced.reason} {exc}".strip(),
            rejections=sourced.rejections,
            skipped_sources=sourced.skipped_sources,
        )
    return PlateOutcome(
        kind="generated",
        plate=plate,
        rejections=sourced.rejections,
        skipped_sources=sourced.skipped_sources,
    )


class ImageTooLarge(ValueError):
    """Header-declared dimensions exceed the configured bound."""


class UnusableImage(ValueError):
    """Bytes with the right magic number and a header that does not parse.

    A truncated PNG is the ordinary case — a catalogue's CDN cutting a download
    short. It arrives looking like an image and is not one, and the first draft
    of this module let it raise straight out of the pipeline: a run over twelve
    species would die on the first bad download instead of recording one
    rejection and carrying on. The suite found it, which is the argument for
    mock mode drawing real PNGs rather than passing sentinels around.
    """


def _check_pixel_bound(data: bytes, max_pixels: int) -> None:
    """Measure from the header, never by decoding.

    Reuses the maps module's probe (`api/grounds/images.py`), which already parses
    the PNG ``IHDR`` chunk and the JPEG ``SOFn`` markers. The JPEG marker walk
    is the subtle part — it has to skip ``DHT``, ``JPG`` and ``DAC``, which sit
    in the same numeric run and are not frames — and a third copy of it in this
    tree would be a third chance to get it wrong. Read-only use of another
    parts of the project's module, flagged for the maintainers in `README.md`: the probe is
    domain-neutral and belongs somewhere neither of us owns.

    If that module is not importable (a worker image built without `api/` on
    the path), the bound is skipped rather than guessed, and the size bound in
    bytes still applies.
    """
    try:
        from grounds.images import (
            ImageTooLargeError,
            UnsupportedImageError,
            check_within,
            probe,
        )
    except ImportError:  # pragma: no cover - both shipped images carry api/
        return
    try:
        check_within(probe(data), max_pixels)
    except ImageTooLargeError as exc:
        raise ImageTooLarge(str(exc)) from exc
    except UnsupportedImageError as exc:
        raise UnusableImage(str(exc)) from exc
