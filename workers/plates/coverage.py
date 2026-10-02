"""Why a leaf is blank, for every plant in the register.

`GET /journal/coverage`, declared in contract 1.6.0 and built
here. It is the third place this project has made the same decision: the design
§2 gave `/almanac/frost` an envelope because *"a list of alerts cannot say 'and
these three I could not judge'"*, the design gave `MorningRounds` an
`unscheduled[]` because a plant with no task is indistinguishable from a plant
that needs nothing, and a plant missing from a book of plates is
indistinguishable from a plant nobody owns.

an earlier release shipped the first half of this: the book pages through **plants**, so a
plant with no plate already gets a named blank leaf. What it could not say was
*why*, because the contract had nowhere to put the reason. This module is the
second half.

## The honest-reason rule

:data:`REASON_KINDS` is closed, so the book can render each absence distinctly
and a new kind has to be declared rather than smuggled in as prose. Two of them
exist precisely so that nothing here has to guess:

* ``store_unavailable`` — there is nowhere to keep a plate. This is *knowable*
  from the deployment's own configuration, right now, without any record of a
  past run, so it is reported as fact rather than inferred.
* ``not_run`` — sourcing has never been attempted for this plant, **or this
  deployment cannot tell whether it was.** That second half is the important
  one: see :func:`live_absence`.

`reason` is the pipeline's own sentence and is prose, not contract. A client
branches on ``reason_kind``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

#: `PlateCoverageEntry.state`, in the contract's order.
State = Literal["approved", "waiting", "absent"]

#: `PlateCoverageEntry.reason_kind`, the closed set from the contract. The
#: pipeline's own outcome vocabulary minus the two kinds that produce a plate,
#: plus the two a reader needs that no run reports.
REASON_KINDS: tuple[str, ...] = (
    "no_candidate",
    "unlicensed_candidate",
    "generation_unavailable",
    "unusable_image",
    "store_unavailable",
    "not_run",
)

#: What `not_run` says when it means "this deployment keeps no record".
#: Deliberately not "nothing was found": the frozen schema has no column for a
#: sourcing outcome, so a live deployment genuinely does not know, and saying
#: so is the whole point of the kind existing (see `README.md`).
NOT_RUN_UNRECORDED = (
    "No plate has been recorded for this plant, and this deployment keeps no "
    "record of whether sourcing has been attempted for it, so it cannot say "
    "whether nothing was found or nothing was asked."
)

STORE_UNAVAILABLE = (
    "There is nowhere to keep a plate in this deployment, so none can be "
    "sourced or drawn until MOH_PLATES_IMAGE_DIR names a volume that survives "
    "a redeploy."
)


class UnknownReasonKind(ValueError):
    """A reason outside the contract's closed set. Never serialised."""


@dataclass(frozen=True, slots=True)
class Absence:
    """Why one plant has no plate."""

    kind: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in REASON_KINDS:
            raise UnknownReasonKind(
                f"{self.kind!r} is not one of the contract's reason kinds: "
                f"{', '.join(REASON_KINDS)}. A new kind is a contract change "
                ", not a new string."
            )
        if not self.reason or not self.reason.strip():
            raise ValueError(
                "An absence with a kind and no sentence is half an answer. The "
                "kind is what a client branches on; the sentence is what a "
                "reader is owed."
            )


@dataclass(frozen=True, slots=True)
class Entry:
    """One `PlateCoverageEntry`, before it is turned into JSON."""

    specimen: Mapping[str, Any]
    state: State
    plate_id: str | None = None
    absence: Absence | None = None

    def __post_init__(self) -> None:
        # The contract says it plainly: `reason_kind` and `reason` are set when
        # and only when `state` is absent; `plate_id` when and only when it is
        # not. Checked here so a repository cannot serve a contradiction.
        if self.state == "absent":
            if self.plate_id is not None:
                raise ValueError("An absent leaf cannot name a plate.")
            if self.absence is None:
                raise ValueError(
                    "An absent leaf must say why. `not_run` is the kind for "
                    "'this deployment does not know' — there is no silent case."
                )
        else:
            if self.plate_id is None:
                raise ValueError(f"A {self.state} leaf must name its plate.")
            if self.absence is not None:
                raise ValueError("A leaf with a plate has no absence to report.")


@dataclass(frozen=True, slots=True)
class Coverage:
    """`PlateCoverage`: the five counts, and one entry per plant."""

    entries: tuple[Entry, ...]

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def approved(self) -> int:
        return sum(1 for e in self.entries if e.state == "approved")

    @property
    def waiting(self) -> int:
        return sum(1 for e in self.entries if e.state == "waiting")

    @property
    def absent(self) -> int:
        return sum(1 for e in self.entries if e.state == "absent")


def plate_for(
    specimen: Mapping[str, Any], plates: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    """This plant's plate: its own if it has one, else its species'.

    The same rule as the book view's `buildPages()`, and for the same reason —
    **no fallback to another species.** A congener's picture is a wrong answer
    that looks like a right one, so the match is by id and nothing else.
    """
    specimen_id = str(specimen["id"])
    species_id = _species_id(specimen)
    own = next(
        (
            p
            for p in plates
            if p.get("specimen_id") and str(p["specimen_id"]) == specimen_id
        ),
        None,
    )
    if own is not None:
        return own
    if not species_id:
        return None
    return next(
        (
            p
            for p in plates
            if p.get("species_id") and str(p["species_id"]) == species_id
        ),
        None,
    )


def build(
    specimens: Iterable[Mapping[str, Any]],
    plates: Sequence[Mapping[str, Any]],
    absence_for: Any,
) -> Coverage:
    """One entry per specimen, in register order.

    ``absence_for(specimen)`` returns the :class:`Absence` for a plant with no
    plate. It is a callable rather than a dict because the two repositories
    know different things: mock mode knows which outcome its rotation gave,
    and a live deployment knows only what it can check right now.
    """
    entries: list[Entry] = []
    for specimen in specimens:
        plate = plate_for(specimen, plates)
        if plate is None:
            entries.append(
                Entry(specimen=specimen, state="absent", absence=absence_for(specimen))
            )
            continue
        entries.append(
            Entry(
                specimen=specimen,
                state="approved" if plate.get("approved") else "waiting",
                plate_id=str(plate["id"]),
            )
        )
    return Coverage(entries=tuple(entries))


def generated_count(
    specimens: Iterable[Mapping[str, Any]], plates: Sequence[Mapping[str, Any]]
) -> int:
    """How many plants are shown a plate drawn by software.

    Counted per **plant**, not per plate, so it is comparable with the other
    four counts: two specimens of one species sharing one generated plate are
    two plants being shown a drawn picture, which is what the book's
    `coverageSentence()` tells a reader.

    `TestCoverageAgreesWithTheBookItFeeds` holds the two together — not by
    importing the book's TypeScript, which it cannot, but by restating the
    book's pairing rule independently in the test and asserting this route
    agrees. It also asserts the two counts differ on the fixtures, so the test
    can actually tell "counted the plants" from "counted the plates"; counting
    the plates is the easier thing to write and reads correctly in isolation.
    """
    return sum(
        1
        for specimen in specimens
        if (plate := plate_for(specimen, plates)) is not None
        and plate.get("origin") == "generated"
    )


def live_absence(store_is_configured: bool) -> Absence:
    """What a live deployment can honestly say about a plant with no plate.

    The frozen schema has **no column for a sourcing outcome** — `plate` records
    plates that exist and nothing about attempts that produced none. So a live
    deployment cannot distinguish "every catalogue was asked and none had it"
    from "the worker has never run", and `not_run` is the kind that says so.

    The one thing it *can* check is whether there is anywhere to keep a plate,
    which is a fact about the configuration rather than about the past, and is
    true of every absent plant at once. Reported as `store_unavailable` because
    it is the more actionable of the two and it is certain.

    Escalated rather than worked around: see `README.md`. Inventing a cause
    here would be exactly what the design says the enum exists to prevent.
    """
    if not store_is_configured:
        return Absence(kind="store_unavailable", reason=STORE_UNAVAILABLE)
    return Absence(kind="not_run", reason=NOT_RUN_UNRECORDED)


def _species_id(specimen: Mapping[str, Any]) -> str | None:
    species = specimen.get("species")
    if isinstance(species, Mapping) and species.get("id"):
        return str(species["id"])
    value = specimen.get("species_id")
    return str(value) if value else None
