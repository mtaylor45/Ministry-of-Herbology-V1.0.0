"""What a plate is allowed to claim about itself.

A plate is a picture of a plant, and this project's whole claim is that it does
not invent plant facts. A picture is a fact about a plant too
— a stronger one than a number, because nobody reads an image's small print
before believing it. The house style asks for a *"nineteenth-century botanical
plate, hand-coloured lithograph… aged cream paper"*, and an image that meets
that brief and was made last Tuesday by a diffusion model is a **fabricated
historical artefact** unless something on it says otherwise.

So the invariants below are the same rule this project has written three times
already, in a fourth place:

* the design — do not imply the soil was measured.
* the design — an unanswerable question must not read as a reassuring answer.
* the design — "somebody watered this" is a fact; "it relieved 14 mm" is a model.
* here — "this is a plate of *Monstera deliciosa*" is a fact about an image's
  provenance, and `origin: generated` is the whole of the evidence for it.

Three rules, and each one refuses rather than softens:

1. **A generated plate carries no licence and no attribution.** Those fields
   exist to record provenance that was *earned* from a real source. A generated
   plate has none, and a blank field is the honest value. Filling it with
   anything — the house style, the model's name, "AI generated" — puts a
   credit-shaped string where readers look for a credit.
2. **A plate claiming `public_domain` with no licence recorded is an
   unsupported claim**, and is not storable. The frozen schema already says so
   (``CHECK (origin <> 'public_domain' OR license IS NOT NULL)``); this module
   says it in Python so the pipeline fails at the candidate rather than at the
   INSERT. The no-invented-plant-facts rule shape: a value with no citation does not get to keep the
   claim. The maintainers' instinct in the brief was that such a plate cannot be
   ``approved``; the schema is stricter than that and I agree with the schema —
   it cannot be *recorded as public domain at all*. See `README.md`.
3. **Nothing in this package may set `approved`.** Approval is a member's act
   and the frozen table has `approved_by` to name them. A pipeline has no
   member identity, so it cannot approve, and `approve()` demands an approver.

The ownership rule has a corollary worth stating: a candidate whose licence is missing or
unrecognised is **discarded**, not downgraded to `generated`. Relabelling a
found image as generated would be a second lie about the same picture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

#: The contract's `Plate.origin` enum, in the contract's order.
Origin = Literal["public_domain", "generated", "user_upload"]

ORIGINS: tuple[Origin, ...] = ("public_domain", "generated", "user_upload")

#: Licence *families* this project will record and display. the design is
#: free-sources-only; these are the four that let an operator redistribute the
#: image inside their own deployment. Anything else — "all rights reserved", a
#: non-commercial clause, a bare "courtesy of" — is not a licence we can stand
#: behind.
ACCEPTABLE_LICENCES = {"public domain", "cc0", "cc by", "cc by-sa"}

#: A catalogue states a version: Commons' ``LicenseShortName`` is "CC BY-SA 4.0",
#: not "cc by-sa". Matching the bare family only would have thrown away most of
#: the licensed plates on Commons for a spelling, so a version is recognised and
#: **kept** — the version is part of the licence, and a row that records "cc by"
#: for a 4.0 file has lost something a reader relying on the credit may need.
#:
#: The pattern is anchored at both ends on purpose. That single detail is what
#: makes "CC BY-NC" fail: the alternation can match "cc by", but the remaining
#: "-nc" has nowhere to go, so the whole match fails rather than silently
#: accepting a non-commercial file as "cc by". A looser match here would be the
#: one bug in this module that produces a wrong licence rather than no plate.
_LICENCE_PATTERN = re.compile(
    r"^(public domain|cc0|cc by-sa|cc by)(?:[ -]?(\d+(?:\.\d+)?))?$"
)

#: An origin whose provenance fields must be empty. Kept as a set rather than a
#: literal so the next origin added has to decide which side it is on.
ORIGINS_WITHOUT_PROVENANCE: frozenset[str] = frozenset({"generated"})

#: An origin that cannot exist without a recorded licence.
ORIGINS_REQUIRING_LICENCE: frozenset[str] = frozenset({"public_domain"})


class ProvenanceError(ValueError):
    """A plate tried to claim something it had not earned.

    Raised rather than logged. Every caller of this module is a pipeline with
    no reader in front of it, so a warning would land in a log nobody reads
    while the plate went into the book anyway.
    """


def is_usable_licence(licence: str | None) -> bool:
    """Is this a licence this deployment will record and show?

    Whitespace, case and a version suffix are artefacts of whichever catalogue
    the string came out of; everything else is load-bearing. An empty string is
    not a licence, and neither is ``"unknown"``.

    This is a whitelist, and it stays one. A catalogue spelling nobody here
    anticipated ("PD-old-100", "No known copyright restrictions") costs a plate
    rather than risking a provenance claim the deployment cannot stand behind —
    which is the direction this project's errors are supposed to run.
    """
    return normalise_licence(licence) is not None


def normalise_licence(licence: str | None) -> str | None:
    """The canonical spelling of a usable licence, or ``None``.

    Callers store what this returns, so two catalogues spelling it ``"Public
    Domain"`` and ``"public domain"`` do not produce two labels in one book —
    while ``"CC BY-SA 4.0"`` keeps its version, because the version is part of
    the licence and not noise.
    """
    if not licence:
        return None
    collapsed = " ".join(licence.split()).lower()
    match = _LICENCE_PATTERN.match(collapsed)
    if match is None:
        return None
    family, version = match.group(1), match.group(2)
    if family not in ACCEPTABLE_LICENCES:  # pragma: no cover - pattern owns this
        return None
    return f"{family} {version}" if version else family


@dataclass(frozen=True)
class Plate:
    """One plate, with its provenance checked at construction.

    Frozen on purpose: a plate that can be mutated after its invariants were
    checked has no invariants. :meth:`approve` returns a new one.

    `image_key` and `thumb_key` are storage keys, not URLs — the schema's
    columns. The router turns a key into the contract's `image_url`, because
    where the bytes live is a deployment's business and not a client's.
    """

    id: str
    origin: Origin
    image_key: str
    species_id: str | None = None
    specimen_id: str | None = None
    thumb_key: str | None = None
    license: str | None = None
    attribution: str | None = None
    source_id: str | None = None
    style: str | None = None
    approved: bool = False
    approved_by: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ProvenanceError(
                f"{self.origin!r} is not one of the contract's origins: "
                f"{', '.join(ORIGINS)}."
            )
        if self.species_id is None and self.specimen_id is None:
            raise ProvenanceError(
                "A plate must belong to a species or to a specimen; this one "
                "names neither, so nothing could ever display it."
            )
        if not self.image_key:
            raise ProvenanceError("A plate with no image is not a plate.")

        if self.origin in ORIGINS_REQUIRING_LICENCE and not self.license:
            raise ProvenanceError(
                "A plate claiming to be public domain with no licence recorded "
                "is an unsupported claim, and this is where it stops. Record "
                "the licence the source stated, or discard the candidate — do "
                "not relabel it."
            )
        if self.license is not None and not is_usable_licence(self.license):
            raise ProvenanceError(
                f"{self.license!r} is not a licence this deployment will show. "
                f"Acceptable: {', '.join(sorted(ACCEPTABLE_LICENCES))} "
                "."
            )

        if self.origin in ORIGINS_WITHOUT_PROVENANCE:
            if self.license is not None:
                raise ProvenanceError(
                    "A generated plate has no licence. The field is for "
                    "provenance a real source gave us, and a generated plate "
                    "earned none."
                )
            if self.attribution is not None:
                raise ProvenanceError(
                    "A generated plate carries no botanical attribution. "
                    "Anything in this field reads as a credit, which is the "
                    "one thing a drawn-to-order image must not have."
                )
            if self.source_id is not None:
                raise ProvenanceError(
                    "A generated plate cites no source. `source_id` points at "
                    "the `source` table, which is for works that exist."
                )

        if self.approved and not self.approved_by:
            raise ProvenanceError(
                "An approved plate names who approved it. `approved` with no "
                "`approved_by` is a decision with no author, which is what "
                "makes the field worth having — see `approve()`."
            )
        if self.approved_by and not self.approved:
            raise ProvenanceError(
                "`approved_by` with `approved` false is a half-recorded "
                "decision. Clear both or set both."
            )

    @property
    def is_generated(self) -> bool:
        return self.origin == "generated"

    @property
    def needs_generated_label(self) -> bool:
        """Must the reader be told, on the plate, that nobody drew this by hand?

        the design settled the analogous question for task certainty: next to the
        instruction, not behind a tooltip. A book view's equivalent of "next to
        the instruction" is *on the plate*, in the caption a reader cannot
        scroll past, and in the alt text a reader who cannot see it is given.
        """
        return self.is_generated

    def approve(self, member_id: str) -> Plate:
        """The maintainers named member accepts this plate as this plant's portrait.

        The only way `approved` becomes true. It takes a member id and not a
        flag precisely so that no pipeline can call it by accident: a worker
        has nobody to put in this argument.
        """
        if not member_id:
            raise ProvenanceError(
                "Approval is somebody's act. Pass the member who made it — a "
                "pipeline cannot approve a plate (see this module's docstring)."
            )
        return replace(self, approved=True, approved_by=member_id)

    def unapprove(self) -> Plate:
        """Withdraw approval, and the name attached to it, together."""
        return replace(self, approved=False, approved_by=None)
