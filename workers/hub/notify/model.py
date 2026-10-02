"""What a notification is, and who gets it — the hub.

Three small types, and the interesting one is :class:`Certainty`.

## Certainty is a value, not a tone

Contract 1.3.0 puts ``confidence``, ``degraded`` and ``degradations[]`` on
``Task``, for the reason the design spends two pages on: an answer built on a
degraded input must not arrive looking like a clean one. A push notification is
where that is hardest to keep, because a push is *short*, and the first thing
brevity eats is the caveat.

So certainty is parsed into a value at the edge, carried to the copy, and the
copy has no way to render a degraded input as an instruction. Three states, not
two:

``stated`` and clean
    The scheduler told us, and it is confident. Say the thing plainly.
``stated`` and degraded (or low, or unknown)
    The scheduler told us it is a guess. Say so, in its own words —
    ``Degradation.detail`` is specified as "a plain sentence, written to be
    shown to the reader as-is", so it is shown as-is.
not ``stated``
    The API did not carry the fields at all. That is the live case today: the
    three fields are the scheduler's escalation 1 and are **not** in the frozen 1.2.0
    contract, so a deployment running a 1.2.0 API serves a task with no
    certainty on it whatsoever. Absence is not confidence. It reads as unknown
    and the copy hedges, because the alternative is that the one API version
    that cannot tell us anything is the one we sound most sure about.

## Recipients

``member.notify_prefs`` is a ``jsonb`` column typed ``additionalProperties:
true`` in the contract — an open blob with no stated convention, exactly like
``sensor_source.external_ids`` was. :meth:`Recipient.from_member_row`
reads one, and the convention it reads is written down in
`the project notes` and escalated to the maintainers for a line in the spec.

A member with no Home Assistant notify service configured is **not** a fault
and is not reported as one: it is the normal state of a household where one
person has the companion app and two do not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The contract's ``Confidence`` enum, worst first. Used to take a ceiling:
#: the design rule is that ``caps_at`` is a ceiling and not a subtraction.
CONFIDENCE_ORDER: tuple[str, ...] = ("unknown", "low", "medium", "high")

#: What this worker can interrupt someone about. One name per kind, used as the
#: ``notify_prefs`` key, the ledger prefix and the job name, so a household that
#: turns one off turns off exactly one thing.
KINDS: tuple[str, ...] = ("rounds", "frost", "health")

#: Frost is the only one that may arrive at three in the morning. See
#: :mod:`workers.hub.notify.policy`.
URGENT_KINDS = frozenset({"frost"})


def _worst(*values: str) -> str:
    """The lowest confidence of the ones given — a ceiling, never a sum."""
    ranked = [value for value in values if value in CONFIDENCE_ORDER]
    if not ranked:
        return "unknown"
    return min(ranked, key=CONFIDENCE_ORDER.index)


@dataclass(frozen=True, slots=True)
class Certainty:
    """How much the thing being notified about is actually known.

    ``stated`` records whether the source said anything at all. It is the
    difference between "the scheduler is confident" and "the scheduler is
    running a contract version that cannot express confidence", and collapsing
    those two is how a notification comes to sound like a measurement.
    """

    confidence: str = "unknown"
    degraded: bool = False
    #: ``Degradation.detail`` strings, shown to the reader as-is.
    reasons: tuple[str, ...] = ()
    stated: bool = False

    @property
    def is_sure(self) -> bool:
        """May this be phrased as a plain instruction with no caveat?"""
        return self.stated and not self.degraded and self.confidence == "high"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> Certainty:
        """Read the three the design fields off a ``Task`` or a ``FrostAlert``."""
        if not isinstance(payload, Mapping):
            return cls()
        present = [
            key for key in ("confidence", "degraded", "degradations") if key in payload
        ]
        if not present:
            return cls()
        raw = payload.get("degradations")
        degradations = (
            raw if isinstance(raw, Sequence) and not isinstance(raw, str) else ()
        )
        reasons: list[str] = []
        capped = str(payload.get("confidence") or "unknown")
        for item in degradations:
            if not isinstance(item, Mapping):
                continue
            detail = str(item.get("detail") or item.get("code") or "").strip()
            if detail:
                reasons.append(detail)
            capped = _worst(capped, str(item.get("caps_at") or "unknown"))
        return cls(
            confidence=capped if capped in CONFIDENCE_ORDER else "unknown",
            degraded=bool(payload.get("degraded")) or bool(reasons),
            reasons=tuple(dict.fromkeys(reasons)),
            stated=True,
        )

    def merge(self, other: Certainty) -> Certainty:
        """The certainty of two things said in one message: the worse of them."""
        return Certainty(
            confidence=_worst(self.confidence, other.confidence),
            degraded=self.degraded or other.degraded,
            reasons=tuple(dict.fromkeys(self.reasons + other.reasons)),
            stated=self.stated and other.stated,
        )


@dataclass(frozen=True, slots=True)
class Recipient:
    """One member, and the Home Assistant service that reaches them.

    ``service`` is an HA notify service — ``notify.mobile_app_marks_phone`` —
    and it is **not** a credential: it is the name of a service on a hub we are
    already authenticated to. The credential is the token in the Authorization
    header, and it never comes near this object.
    """

    member_id: str
    name: str
    service: str
    kinds: frozenset[str] = frozenset(KINDS)
    #: Local hour at which today's rounds may go out. Not a minute: nobody
    #: wants a task list to the second, and an hour is what a person means by
    #: "the morning".
    rounds_hour: int = 7
    #: ``[from, to)`` in local hours. Frost ignores it; see the policy module.
    quiet_from: int = 22
    quiet_to: int = 7
    units: str = "metric"
    #: True when nothing in ``notify_prefs`` named a service, so the Ministry
    #: Office can say "nobody is set up for notifications" without calling it
    #: a failure.
    configured: bool = True
    notes: tuple[str, ...] = ()

    def wants(self, kind: str) -> bool:
        return kind in self.kinds

    @classmethod
    def from_member_row(cls, row: Mapping[str, Any]) -> Recipient | None:
        """One ``member`` row into a recipient, or ``None`` if it is not one.

        Returns ``None`` rather than a disabled recipient for a member with no
        service: an archived member, or one who has simply never installed the
        companion app, is not a configuration error and must not be counted as
        one anywhere.
        """
        if row.get("archived_at"):
            return None
        prefs = row.get("notify_prefs")
        prefs = prefs if isinstance(prefs, Mapping) else {}
        block = prefs.get("home_assistant")
        block = block if isinstance(block, Mapping) else {}
        service = str(block.get("service") or "").strip()
        if not service:
            return None
        kinds = frozenset(kind for kind in KINDS if bool(block.get(kind, True)))
        quiet = block.get("quiet_hours")
        quiet_from, quiet_to = 22, 7
        if (
            isinstance(quiet, Sequence)
            and not isinstance(quiet, str)
            and len(quiet) == 2
        ):
            try:
                quiet_from, quiet_to = int(quiet[0]) % 24, int(quiet[1]) % 24
            except (TypeError, ValueError):
                pass
        try:
            rounds_hour = int(block.get("rounds_hour", 7)) % 24
        except (TypeError, ValueError):
            rounds_hour = 7
        return cls(
            member_id=str(row.get("id") or ""),
            name=str(row.get("name") or "somebody"),
            service=service,
            kinds=kinds,
            rounds_hour=rounds_hour,
            quiet_from=quiet_from,
            quiet_to=quiet_to,
            units=str(block.get("units") or prefs.get("units") or "metric"),
        )


@dataclass(frozen=True, slots=True)
class Notification:
    """One message, ready to hand to a channel.

    ``title`` and ``body`` are plain language, always. ``themed_title`` is the
    The original-theme rule pair and is carried *beside* the plain one rather than instead of
    it, so a surface that wants the Ministry's voice can have it and a phone at
    7 AM gets an instruction.
    """

    kind: str
    title: str
    body: str
    #: The dedupe key. Two notifications with the same key are the same news.
    dedupe_key: str
    themed_title: str | None = None
    urgent: bool = False
    #: A deep link into the app, e.g. ``/rounds``. Never a tokenised URL.
    deep_link: str | None = None
    certainty: Certainty = field(default_factory=Certainty)
    #: Structured extras for a client that can use them. Scanned like
    #: everything else before it goes out.
    data: Mapping[str, Any] = field(default_factory=dict)

    def lines(self) -> list[str]:
        return [line for line in self.body.splitlines() if line.strip()]
