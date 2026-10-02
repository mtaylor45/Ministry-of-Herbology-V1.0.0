"""How sure the engines are, and why — the weather engine.

Under the design there is no soil-moisture hardware and none is planned for v1,
so the water balance is the *sole* authority on when an outdoor plant is
watered. Nothing downstream will catch it being wrong. That makes one failure
mode worse than all the others put together: **an engine that loses an input
and goes on answering in the same confident voice.** A deficit that stopped
advancing because ET₀ went missing looks exactly like a plant that does not
need water.

So every number the Almanac publishes travels with the reasons it might be
wrong. This module is the arithmetic for that:

* a :class:`Degradation` is one named reason, with the best confidence still
  honest in its presence;
* :func:`assess` reduces a pile of them to the weakest cap and the list of
  reasons, which is what the API returns and what J renders beside the
  recommendation.

Confidence only ever falls. There is no evidence that arrives by inference —
the same rule ``workers/botany/tasks.py`` applies to plant facts, applied here
to the inputs of a calculation. the design fixes the four levels and the database
enforces them with a CHECK.

**A missing soil sensor is not in here, and must never be.** the design says the
model-only path is the shipping path, not a degraded one; listing "no sensor"
as a caveat on all twelve specimens forever would train every user to ignore
the caveat line on the one day it says something real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Best to worst. the design allows exactly these four.
CONFIDENCE_ORDER = ("high", "medium", "low", "unknown")


def rank(confidence: str) -> int:
    """Position in :data:`CONFIDENCE_ORDER`; an unknown word ranks worst."""
    try:
        return CONFIDENCE_ORDER.index(confidence)
    except ValueError:
        return len(CONFIDENCE_ORDER) - 1


def weakest(*confidences: str) -> str:
    """The least confident of several claims, which is what a chain is worth."""
    if not confidences:
        return "unknown"
    return CONFIDENCE_ORDER[max(rank(c) for c in confidences)]


def downgrade(confidence: str, steps: int = 1) -> str:
    """Lower a confidence by ``steps``, never below ``unknown``."""
    if steps <= 0:
        return confidence
    return CONFIDENCE_ORDER[min(rank(confidence) + steps, len(CONFIDENCE_ORDER) - 1)]


@dataclass(frozen=True, slots=True)
class Degradation:
    """One reason an answer is worth less than a clean measurement.

    ``caps_at`` is the *best* confidence still honest while this holds. It is a
    ceiling, not a subtraction: two independent doubts about the same input do
    not make it twice as doubtful, but neither may raise the other's ceiling.
    """

    code: str
    detail: str
    caps_at: str = "medium"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "caps_at": self.caps_at}


@dataclass(frozen=True, slots=True)
class Assessment:
    """A confidence and the full reason it is not higher."""

    confidence: str
    degradations: tuple[Degradation, ...] = ()

    @property
    def is_degraded(self) -> bool:
        return bool(self.degradations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "degraded": self.is_degraded,
            "degradations": [d.to_dict() for d in self.degradations],
        }


def assess(degradations: list[Degradation], *, base: str = "high") -> Assessment:
    """Reduce reasons to a confidence, weakest cap wins.

    ``base`` is what the answer would be worth with nothing wrong at all. It is
    rarely ``high`` in practice: a modelled deficit with a category-default
    coefficient starts at ``medium`` and can only go down from there.
    """
    ordered = sorted(degradations, key=lambda d: rank(d.caps_at), reverse=True)
    confidence = weakest(base, *(d.caps_at for d in ordered))
    return Assessment(confidence=confidence, degradations=tuple(ordered))


# --------------------------------------------------------------------- reasons
#
# Named constructors rather than string literals scattered through the engines:
# a caveat the UI has to render is part of the contract with the reader, and
# rewording one in six places is how half of them stop matching.


def et0_fallback(days: int) -> Degradation:
    """Hargreaves stood in for Open-Meteo's ET₀ on ``days`` days."""
    return Degradation(
        code="et0_fallback",
        detail=(
            f"ET₀ was computed locally (Hargreaves) for {days} "
            f"day{'s' if days != 1 else ''}, because the forecast did not carry it."
        ),
        caps_at="medium",
    )


def et0_missing(days: int) -> Degradation:
    """Neither ingested nor computable. The deficit did not advance."""
    return Degradation(
        code="et0_missing",
        detail=(
            f"{days} day{'s' if days != 1 else ''} had no ET₀ at all, ingested or "
            "computed. The deficit did not advance on those days, so the real "
            "figure is higher than this one."
        ),
        caps_at="low",
    )


def k_c_category_default(category: str | None, source: str | None) -> Degradation:
    """a published coefficient for a *category*, not for this plant."""
    scope = f"the {category} category" if category else "a vegetation category"
    cite = f" ({source})" if source else ""
    return Degradation(
        code="k_c_category_default",
        detail=(
            f"The water coefficient is a published default for {scope}{cite}, "
            "not a value measured for this species."
        ),
        caps_at="medium",
    )


def k_c_uncited() -> Degradation:
    """a number nobody attests is not a fact, whatever it computes."""
    return Degradation(
        code="k_c_uncited",
        detail=(
            "The water coefficient carries no citation, so every figure derived "
            "from it is a guess with arithmetic done to it."
        ),
        caps_at="unknown",
    )


def ingest_stale(hours: float) -> Degradation:
    """The newest observation is older than the ingest is supposed to allow."""
    return Degradation(
        code="ingest_stale",
        detail=(
            f"The newest stored reading is {hours:.0f} hours old. The deficit has "
            "not advanced since, so it reads lower than the plant's real one."
        ),
        caps_at="low" if hours >= 24 else "medium",
    )


def forecast_not_observed(days: int) -> Degradation:
    """Part of the series is still a forecast; forecast rain is not rain."""
    return Degradation(
        code="forecast_not_observed",
        detail=(
            f"{days} day{'s' if days != 1 else ''} of this series is forecast "
            "rather than observed. Rain that has not fallen yet has not watered "
            "anything."
        ),
        caps_at="medium",
    )


def certainty_not_recorded() -> Degradation:
    """A stored row from before the design, or from a worker that skipped it.

    Migration 004 defaults ``confidence`` to NULL and is never back-filled, so
    an empty column means *it did not say* — not *it was certain*. Reading it
    as ``medium`` is the exact laundering the design was written against, one
    table further down.
    """
    return Degradation(
        code="certainty_not_recorded",
        detail=(
            "This deficit was stored without the confidence it was computed "
            "with, so what it was worth at the time cannot be recovered."
        ),
        caps_at="unknown",
    )


def secondary_source(source: str) -> Degradation:
    """The contract's primary source was unreachable and NWS answered instead."""
    return Degradation(
        code="secondary_source",
        detail=(
            f"These figures came from the secondary source ({source}) because "
            "Open-Meteo could not be reached. It does not publish ET₀, so ET₀ "
            "here is computed locally."
        ),
        caps_at="medium",
    )
