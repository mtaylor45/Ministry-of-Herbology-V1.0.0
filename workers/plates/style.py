"""The one house style, and the marks a generated plate must not wear.

an earlier release wrote :data:`HOUSE_STYLE` and it was already right, so it is unchanged in
substance. What this module adds is the second half of the thought — the list
of things the prompt must *forbid*, which is where the honesty work actually
lives.

## Why the style is the problem as well as the goal

The brief asks for a *"nineteenth-century botanical plate, hand-coloured
lithograph… aged cream paper"*. That is the right aesthetic for this book and it
is also a recipe for a **fabricated historical artefact**: an image that reads
as a scan of a plate from 1840 and is not one. The label in the UI is the primary answer. This
module is the
second answer, applied at the prompt: *do not ask for the marks that make an
image claim a provenance.*

Aged paper is an aesthetic. A plate number, an engraver's signature, a Latin
binomial in copperplate script and a herbarium accession stamp are **claims**.
A reader who sees "Pl. XIV" in the corner has been told this came out of a
book, and no caption undoes that — the caption says "generated", the picture
says "volume two", and the picture wins. So the forbidden list is not a quality
preference; it is the same rule as `domain.py`'s refusal to write an
attribution a generated plate did not earn, enforced one step earlier.

## The original-theme rule, which is most live in this release

The style is a *genre* register — wizarding botany, an old academy's teaching
collection — and it stays clear of the franchise it evokes. No crests or
emblems, no house names or iconography, no film typefaces, no character names.
The earlier string was already clean of all of it; :data:`FORBIDDEN_MARKS` keeps it
that way by saying so out loud, and :func:`prompt_for` builds every prompt from
these two constants so there is no second place for a stray reference to enter.
"""

from __future__ import annotations

#: One house style for every generated plate, so the book reads as one volume.
#: Deliberately free of franchise references. Unchanged from
#: the earlier skeleton: it was right.
HOUSE_STYLE = (
    "nineteenth-century botanical plate, hand-coloured lithograph, single specimen "
    "centred on aged cream paper, fine ink linework, muted natural pigments, "
    "no text, no border, no signature"
)

#: Marks that would make a generated image claim a provenance it does not have.
#: Each is a thing a real plate carries *because* it came out of a real book.
FORBIDDEN_MARKS: tuple[str, ...] = (
    "no plate number or figure number",
    "no engraver, lithographer or artist signature",
    "no printed caption, binomial or handwriting of any kind",
    "no library, herbarium or museum stamp, label or accession number",
    "no publisher's imprint, date or volume mark",
    "no torn edge, foxing or water stain suggesting age of the sheet itself",
    "no crest, seal, emblem, coat of arms or institutional device",
)

#: The original-theme rule, stated to the model rather than only to ourselves.
FORBIDDEN_THEME: tuple[str, ...] = (
    "no franchise crests, emblems or house iconography",
    "no character names or invented place names",
    "no film or franchise typefaces",
)


def prompt_for(botanical_name: str, *, habit: str | None = None) -> str:
    """The whole prompt for one generated plate, from the two constants above.

    Takes a botanical name because that is what the plate is *of*, and nothing
    else: no care facts, no native range, no colour the pipeline inferred. A
    prompt that asserts what a plant looks like beyond its name is inventing a
    plant fact, and the picture is the hardest kind of invented fact
    to notice afterwards.

    ``habit`` is passed through only when it came from a cited record upstream.
    It is a caller's job to not pass a guess.
    """
    if not botanical_name or not botanical_name.strip():
        raise ValueError(
            "A plate is of a named plant. Generating from an empty name would "
            "produce a picture of nothing and label it as a species."
        )
    subject = botanical_name.strip()
    if habit:
        subject = f"{subject}, {habit.strip()}"
    constraints = ", ".join((*FORBIDDEN_MARKS, *FORBIDDEN_THEME))
    return f"{subject}. {HOUSE_STYLE}. {constraints}."
