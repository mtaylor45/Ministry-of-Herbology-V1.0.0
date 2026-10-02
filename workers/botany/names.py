"""Reading what the gardener typed.

Pure string work, no network: a typed name is split into the part a taxonomic
authority can look up and the part it cannot. Cultivars are the common case —
POWO and GBIF both index *Lavandula angustifolia*, neither indexes
*'Hidcote'* — so the cultivar epithet is carried separately and handed back to
the caller to store on the specimen (``specimen.cultivar`` in the schema).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: ``'Hidcote'``, ``‘Hidcote’``, ``"Hidcote"``, ``cv. Hidcote``. The quoted form
#: is the ICNCP one; the others are what people actually type.
_CULTIVAR_QUOTED = re.compile(r"[‘'\"“]\s*([^’'\"”]+?)\s*[’'\"”]")
_CULTIVAR_MARKER = re.compile(
    r"\b(?:cv\.?|cultivar)\s+([\w][\w'’-]*(?:\s+[A-Z][\w'’-]*)*)", re.IGNORECASE
)

#: ``Citrus x limon`` and ``Citrus X limon`` mean ``Citrus × limon``.
_HYBRID_X = re.compile(r"(?<=\s)[xX](?=\s)")
_HYBRID_PREFIX = re.compile(r"^[xX]\s+(?=[A-Za-z])")

#: Trailing authorship, in the two shapes that are safe to strip: one opening
#: with a basionym author in brackets (``Citrus x limon (L.) Osbeck``), and one
#: ending in the abbreviating full stop (``Monstera deliciosa Liebm.``). A
#: species epithet is lowercase, so neither pattern can eat one.
_AUTHOR_WORD = r"[A-Z][\w.'\u2019-]*"
_AUTHORSHIP = re.compile(
    r"\s+(?:"
    r"\([^()]*\)\s*" + _AUTHOR_WORD + r"(?:\s*(?:&|ex)\s*" + _AUTHOR_WORD + r")*"
    r"|" + _AUTHOR_WORD + r"\.(?:\s*(?:&|ex)\s*" + _AUTHOR_WORD + r")*"
    r")\s*$"
)

#: Infraspecific connectors POWO and GBIF both understand.
_RANK_MARKERS = {"subsp.", "ssp.", "var.", "f.", "forma", "subvar."}

_RANK_BY_MARKER = {
    "subsp.": "subspecies",
    "ssp.": "subspecies",
    "var.": "variety",
    "subvar.": "variety",
    "f.": "variety",
    "forma": "variety",
}


@dataclass(frozen=True, slots=True)
class ParsedName:
    """What we can say about a typed name before asking anybody."""

    raw: str
    #: Whitespace-collapsed, accent-preserving, cultivar and authorship removed.
    text: str
    #: The part to send to a taxonomic authority, ``None`` if nothing is left.
    scientific: str | None
    cultivar: str | None = None
    is_hybrid: bool = False
    #: A binomial shape (``Genus species``), as opposed to ``snake plant``.
    looks_scientific: bool = False
    #: ``species`` unless an infraspecific marker says otherwise.
    rank_hint: str = "species"

    @property
    def lookup(self) -> str:
        """What to search for: the scientific part if there is one, else the text."""
        return self.scientific or self.text


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def strip_authorship(text: str) -> str:
    """Drop a trailing author citation. ``Monstera deliciosa Liebm.`` is a name."""
    stripped = _AUTHORSHIP.sub("", text).strip()
    # Never strip the whole thing: ``L.`` alone is all the user gave us.
    return stripped or text.strip()


def normalise_hybrid(text: str) -> tuple[str, bool]:
    """``Citrus x limon`` → ``Citrus × limon``. Returns the flag too."""
    out = _HYBRID_PREFIX.sub("× ", text)
    out = _HYBRID_X.sub("×", out)
    return out, "×" in out


def _capitalise_binomial(text: str) -> str:
    """``monstera DELICIOSA`` → ``Monstera deliciosa``, leaving markers alone."""
    words = text.split(" ")
    out: list[str] = []
    for index, word in enumerate(words):
        if not word or word == "×" or word.lower() in _RANK_MARKERS:
            out.append(word)
            continue
        first_alpha = index == 0 or (index == 1 and words[0] == "×")
        out.append(word.capitalize() if first_alpha else word.lower())
    return " ".join(out)


def parse_name(raw: str) -> ParsedName:
    """Split a typed name into a lookup term, a cultivar and some hints."""
    text = _collapse(raw)
    cultivar: str | None = None

    match = _CULTIVAR_QUOTED.search(text)
    if match:
        cultivar = _collapse(match.group(1))
        text = _collapse(text[: match.start()] + " " + text[match.end() :])
    else:
        match = _CULTIVAR_MARKER.search(text)
        if match:
            cultivar = _collapse(match.group(1))
            text = _collapse(text[: match.start()] + " " + text[match.end() :])

    text = strip_authorship(text)
    text, is_hybrid = normalise_hybrid(text)
    text = _collapse(text)

    words = [w for w in text.split(" ") if w]
    core = [w for w in words if w != "×"]
    rank_hint = "species"
    for word in words:
        if word.lower() in _RANK_MARKERS:
            rank_hint = _RANK_BY_MARKER.get(word.lower(), "variety")
            break
    if rank_hint == "species" and len(core) == 1 and core[0][:1].isupper():
        # ``Hosta`` is a genus; ``mandrake`` is somebody's word for a plant,
        # and only a source gets to say what rank it turns out to be.
        rank_hint = "genus"
    if is_hybrid:
        rank_hint = "hybrid"

    looks_scientific = bool(core) and len(core) >= 2 and _is_epithet(core[1])
    scientific = _capitalise_binomial(text) if looks_scientific else None
    if not text:
        scientific = None

    return ParsedName(
        raw=raw,
        text=text,
        scientific=scientific,
        cultivar=cultivar or None,
        is_hybrid=is_hybrid,
        looks_scientific=looks_scientific,
        rank_hint=rank_hint,
    )


def _is_epithet(word: str) -> bool:
    """A species epithet is one lowercase-able Latin word, not ``plant`` or ``lily``."""
    return (
        bool(re.fullmatch(r"[A-Za-zÀ-ɏ-]{3,}\.?", word))
        or word.lower() in _RANK_MARKERS
    )


def similarity(left: str, right: str) -> float:
    """0..1 agreement between two names, case- and accent-insensitive.

    Deterministic and offline — the misspelling test must not depend on whatever
    a remote matcher scored today.
    """
    return round(SequenceMatcher(None, fold(left), fold(right)).ratio(), 4)


def fold(text: str) -> str:
    """Casefold, strip accents, and drop the hybrid marker.

    ``Citrus × limon``, ``Citrus x limon`` and GBIF's ``Citrus limon`` are one
    plant under three spellings, and a lemon tree should not be resolved twice
    because two authorities punctuate it differently.
    """
    decomposed = unicodedata.normalize("NFKD", text.replace("×", " x "))
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = [
        w for w in _collapse(without_marks).casefold().split(" ") if w and w != "x"
    ]
    return " ".join(words)


def merge_key(name: str) -> str:
    """The key two sources' names must share to count as the same taxon."""
    return fold(name)
