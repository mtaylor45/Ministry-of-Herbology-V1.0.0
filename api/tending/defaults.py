"""The care rules a plant gets before anybody writes one.

A fresh deployment has an empty ``care_rule`` table and twelve plants that still
need watering. These are the rules that stand in until the household edits them,
and they are derived strictly from what the botany worker has actually attested about
the species.

**The thing this module refuses to do is make up a number.** The no-invented-plant-facts rule and
the design
are not satisfied by a plausible default: a fourteen-day interval nobody cited,
presented in the same voice as a cited one, is a plant fact this project
invented. So:

* an interval with a citation becomes a rule at that citation's confidence;
* an interval with no citation becomes a rule at ``unknown`` confidence, and
  every task it generates says so in ``detail`` where a reader will see it;
* **no interval at all becomes no rule**, and the plant is named in Morning
  Rounds' ``unscheduled`` list with the reason. A plant that silently drops off
  the schedule is the failure this project has spent several design decisions guarding against
  in the weather engines; it arrives here through the door marked "sensible
  default".

Season multipliers are likewise absent from the defaults. The *mechanism* is in
``tending.domain`` and is tested, but "water 1.6× less often in winter" is a
care value like any other, and this package has no citation for it. A household
that wants one adds it with ``POST /tending/care-rules``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from tending.domain import Caveat, Rule, Subject

#: Deterministic ids for derived rules, so a rule keeps its identity — and every
#: task anchored to it keeps its ICS UID — across restarts and redeployments.
RULE_NAMESPACE = uuid.UUID("3a1f6b52-6d21-4a5e-9f3c-7d2b8e40c916")


@dataclass(frozen=True, slots=True)
class Attested:
    """A care value and what it is actually worth."""

    value: Any
    confidence: str = "unknown"
    source_id: str | None = None

    @property
    def is_cited(self) -> bool:
        return bool(self.source_id)


def attested(care_values: list[dict[str, Any]], field: str) -> Attested | None:
    """One field out of a species' cited care values, or ``None``."""
    for row in care_values or []:
        if row.get("field") == field and row.get("value") is not None:
            return Attested(
                value=row["value"],
                confidence=str(row.get("confidence") or "unknown"),
                source_id=row.get("source_id") or None,
            )
    return None


def derived_rule_id(specimen_id: str, task_type: str) -> str:
    return str(uuid.uuid5(RULE_NAMESPACE, f"{specimen_id}|{task_type}|derived"))


def interval_confidence(interval: Attested | None) -> str:
    """What a task built on this interval may honestly claim.

    An uncited number is ``unknown`` — not ``low``. the design is specific, and
    the difference matters: ``low`` says "we measured badly", ``unknown`` says
    "nobody has said".
    """
    if interval is None:
        return "unknown"
    return interval.confidence if interval.is_cited else "unknown"


def uncited_interval_caveat(subject: Subject) -> Caveat:
    """the design visible mark, in words somebody can act on."""
    return Caveat(
        code="interval_uncited",
        detail=(
            f"The watering interval for {subject.display_name} carries no "
            "citation, so this schedule is a guess with arithmetic done to it. "
            "Edit it on the Tending facet if you know better."
        ),
        caps_at="unknown",
    )


def water_rule(
    subject: Subject, interval: Attested | None
) -> tuple[Rule | None, str | None]:
    """The watering rule for one plant, or the reason it cannot have one.

    An outdoor plant is scheduled by the weather engine's water balance, which needs no
    interval; the interval rides along as the fallback for the days the model
    declines to answer. An indoor plant has nothing but the interval.

    An *uncited* interval is used and marked, not discarded. the design says a
    value with no citation is ``unknown`` and visibly flagged — which is a
    different instruction from "throw it away", and the difference is ten of
    this fixture's twelve plants. Only when there is no number at all is there
    no rule, and then the plant is named rather than dropped.
    """
    strategy = "water_balance" if subject.is_outdoor else "interval"
    days = None
    if interval is not None:
        try:
            days = max(1, int(round(float(interval.value))))
        except (TypeError, ValueError):
            days = None

    if days is None and strategy == "interval":
        return None, (
            "No watering interval is recorded for this species, and nothing "
            "measures its soil. Add a cited care value, or a care "
            "rule of your own, and it will join the rounds."
        )

    modifiers: dict[str, Any] = {}
    if subject.dormancy_months:
        # Suspended, not stretched: a dormant plant is off the schedule, not on
        # a longer one. Stretching still puts a watering in the calendar in the
        # month the plant least wants it.
        modifiers["dormancy"] = "suspend"

    confidence = interval_confidence(interval)
    caveats: tuple[Caveat, ...] = ()
    if interval is not None and not interval.is_cited:
        caveats = (uncited_interval_caveat(subject),)

    return (
        Rule(
            id=derived_rule_id(subject.specimen_id, "water"),
            task_type="water",
            strategy=strategy,
            base_interval_days=days,
            amount_ml=None,
            modifiers=modifiers,
            months=(),
            enabled=True,
            specimen_id=subject.specimen_id,
            interval_confidence=confidence,
            interval_caveats=caveats,
        ),
        None,
    )


def default_rules(
    subject: Subject, care_values: list[dict[str, Any]], fallback_interval: Any = None
) -> tuple[list[Rule], list[str]]:
    """Every derived rule for one plant, and the reasons for the ones missing.

    ``fallback_interval`` is the species' own ``water_interval_days`` column —
    The botany worker's synthesised value, which may have no ``care_value`` row
    citing it. It is used at ``unknown`` confidence and flagged, by design.
    """
    interval = attested(care_values, "water_interval_days")
    if interval is None and fallback_interval is not None:
        interval = Attested(value=fallback_interval, confidence="unknown")
    rule, reason = water_rule(subject, interval)
    rules = [rule] if rule is not None else []
    reasons = [reason] if reason else []
    return rules, reasons
