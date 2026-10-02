"""Whether the hub is actually answering — the hub.

the design made Home Assistant a hard dependency: if it stops, indoor readings
stop, and nothing else will notice. **A silent adapter is this parts of the project's
failure mode**, and it is worse than a loud one because a flat line and a dead
hub look identical on a chart. So every run leaves a mark on the
``integration`` row — ``last_ok_at`` when it worked, ``last_error`` when it did
not — and the Ministry Office reads that rather than a log file.

Two rules run through the module.

**A stale success is not a success.** ``last_ok_at`` from four hours ago with
no error since is not health; it is an adapter that has stopped running. The
status here is computed against a clock and a tolerance, never read off the
presence of a value.

**Nothing secret reaches ``last_error``.** That column is rendered in the UI
and read by whoever is helping. Home Assistant's own errors do not contain the
token, but a misconfigured base URL can carry credentials, an httpx exception
quotes the URL it dialled, and a redirect can put a query string in a message.
:func:`redact` is a second line after :mod:`workers.hub.sources.http`'s
care, and it runs on the way *into* the column rather than on the way out,
because the column is what gets read.

The soil probes deliberately do not appear in here as a warning. the design says
the model-only path is the shipping path, so "no soil sensor configured" is
the normal state of a correct v1.0 installation and not a fault to report. A
sensor source that *is* configured and has gone quiet is very much a fault,
and that is :class:`SourceHealth`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .mapping import SensorSource

#: What replaces anything redacted, so a scrubbed message still reads as one.
MASK = "[redacted]"

#: Patterns that look like a credential wherever they appear. Deliberately
#: blunt: a false positive costs a reader one word of an error message, and a
#: false negative puts a long-lived access token on a screen.
_SECRET_PATTERNS = (
    # Anything after a bearer/token/password/api-key label.
    re.compile(
        r"(?i)\b(bearer|token|access[_-]?token|api[_-]?key|password|secret)\b"
        r"\s*[:=]?\s*[\"']?([A-Za-z0-9._\-]{8,})[\"']?"
    ),
    # Credentials embedded in a URL: https://user:pass@host/…
    re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*)://([^/\s:@]+):([^/\s@]+)@"),
    # A JWT, which is what a Home Assistant long-lived token is.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}"),
)


def redact(text: str | None, secrets: Iterable[str] = ()) -> str | None:
    """``text`` with anything credential-shaped replaced by :data:`MASK`.

    ``secrets`` are the exact values this deployment holds — the token, the
    MQTT password — and they are removed first and literally, because an exact
    match needs no pattern to be right. The patterns then catch the ones we do
    not hold, such as a credential someone put in ``MOH_HA_BASE_URL``.
    """
    if not text:
        return text
    result = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            result = result.replace(secret, MASK)
    result = _SECRET_PATTERNS[0].sub(rf"\1: {MASK}", result)
    result = _SECRET_PATTERNS[1].sub(rf"\1://\2:{MASK}@", result)
    result = _SECRET_PATTERNS[2].sub(MASK, result)
    return result


@dataclass(frozen=True, slots=True)
class IntegrationHealth:
    """One ``integration`` row, read as a state rather than as three columns.

    Mirrors the contract's ``Integration`` schema so the Ministry Office
    endpoint can serve this shape with ``status`` added — which is additive to
    the contract and therefore a request to the maintainers, noted in the pull request.
    """

    id: str
    kind: str
    name: str
    enabled: bool = True
    last_ok_at: datetime | None = None
    last_error: str | None = None
    #: Whether the deployment has been given what it needs to try at all.
    configured: bool = True
    #: How long a success stays good. Defaults to twice the poll interval:
    #: one missed run is a blip, two is a pattern.
    ok_for_s: float = 900.0

    def status(self, now: datetime) -> str:
        """One word for a screen. Order matters and is the argument.

        ``disabled`` and ``unconfigured`` come first because neither is a
        fault and showing them as one trains people to ignore the row. Then
        ``down`` — an error with no recent success — then ``stale``, which is
        the silent case: nothing has failed, and nothing has happened either.
        ``degraded`` is an error that a later success has already survived.
        """
        if not self.enabled:
            return "disabled"
        if not self.configured:
            return "unconfigured"
        fresh = self.last_ok_at is not None and (
            now - self.last_ok_at <= timedelta(seconds=self.ok_for_s)
        )
        if self.last_error and not fresh:
            return "down"
        if self.last_ok_at is None:
            return "unknown"
        if not fresh:
            return "stale"
        return "degraded" if self.last_error else "ok"

    def contract_status(self, now: datetime) -> str:
        """:meth:`status` folded onto the contract's five words.

        ``Integration.status`` is ``ok``, ``degraded``, ``down``, ``stale`` or
        ``unconfigured``. Two of this module's states have no word of their
        own there, and both are folded towards the reading that keeps them
        honest rather than the one that looks better:

        * ``disabled`` becomes ``unconfigured``. Somebody switched it off; it
          is not a fault, and ``enabled: false`` beside it says which kind of
          not-running it is.
        * ``unknown`` — configured, never once heard from — becomes ``stale``
          with ``last_ok_at: null``. It is not ``down`` (nothing has failed)
          and it must not be ``ok`` (nothing has succeeded): it is the silent
          case, which is what ``stale`` is for. Escalated to the maintainers in the earlier pull
          request as a sixth word the enum may want.
        """
        status = self.status(now)
        if status == "disabled":
            return "unconfigured"
        if status == "unknown":
            return "stale"
        return status

    def to_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "enabled": self.enabled,
            "last_ok_at": (self.last_ok_at.isoformat() if self.last_ok_at else None),
            "last_error": self.last_error,
            "status": self.status(now),
        }

    def to_contract(self, now: datetime, secrets: Iterable[str] = ()) -> dict[str, Any]:
        """The contract's ``Integration``, ``last_error`` redacted once more.

        The jobs redact on the way *into* the column. This redacts again on
        the way out, because the column is not only the hub's to write — a row an
        operator edited by hand, or one written before a pattern existed, is
        still going to be rendered on the Ministry Office screen.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "enabled": self.enabled,
            "status": self.contract_status(now),
            "last_ok_at": (self.last_ok_at.isoformat() if self.last_ok_at else None),
            "last_error": redact(self.last_error, secrets),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any], **overrides: Any) -> IntegrationHealth:
        from .sources.base import parse_time

        last_ok = row.get("last_ok_at")
        return cls(
            id=str(row["id"]),
            kind=str(row.get("kind") or "home_assistant"),
            name=str(row.get("name") or row.get("kind") or "Home Assistant"),
            enabled=bool(row.get("enabled", True)),
            last_ok_at=(parse_time(last_ok) if isinstance(last_ok, str) else last_ok),
            last_error=(str(row["last_error"]) if row.get("last_error") else None),
            **overrides,
        )


@dataclass(frozen=True, slots=True)
class SourceHealth:
    """One configured ``sensor_source``, and whether it is still reporting.

    The phrase this produces is the one the design asks for by name: a gap has
    to render as *no recent reading*, not as a flat line drawn across it.
    """

    source_id: str
    name: str
    enabled: bool
    poll_seconds: int
    last_seen_at: datetime | None
    location_id: str | None = None
    specimen_id: str | None = None

    def tolerance_s(self, floor_s: float) -> float:
        """How long silence is allowed to last before it means something.

        Three intervals, or the configured floor, whichever is longer. Three
        rather than one because a poll that lands a second late must not make
        a healthy thermostat flicker on the Office screen every few minutes.
        """
        return max(float(self.poll_seconds) * 3.0, floor_s)

    def status(self, now: datetime, *, floor_s: float = 1800.0) -> str:
        if not self.enabled:
            return "disabled"
        if self.last_seen_at is None:
            return "never reported"
        gap = (now - self.last_seen_at).total_seconds()
        return "reporting" if gap <= self.tolerance_s(floor_s) else "no recent reading"

    def to_dict(self, now: datetime, *, floor_s: float = 1800.0) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "location_id": self.location_id,
            "specimen_id": self.specimen_id,
            "poll_seconds": self.poll_seconds,
            "last_seen_at": (
                self.last_seen_at.isoformat() if self.last_seen_at else None
            ),
            "status": self.status(now, floor_s=floor_s),
        }

    @classmethod
    def from_source(cls, source: SensorSource) -> SourceHealth:
        return cls(
            source_id=source.id,
            name=source.name,
            enabled=source.enabled,
            poll_seconds=source.poll_seconds,
            last_seen_at=source.last_seen_at,
            location_id=source.location_id,
            specimen_id=source.specimen_id,
        )


def health_report(
    integrations: Sequence[IntegrationHealth],
    sources: Sequence[SourceHealth],
    *,
    now: datetime,
    floor_s: float = 1800.0,
) -> dict[str, Any]:
    """What the Ministry Office needs to say whether the hub is answering.

    ``ok`` is a single boolean because the Office has one line for it, and it
    is deliberately conservative: an integration that is down, or a configured
    source that has gone quiet, makes the whole thing not-ok. A household with
    no integrations configured at all is ``ok`` — nothing is broken, nothing
    was asked for — and ``configured`` says so separately.

    ``awaiting`` is kept apart from ``problems`` on purpose. A source that has
    never produced a reading is usually a deployment that was set up four
    minutes ago, and putting it in the same list as a thermostat that went
    quiet overnight would make the alarming list the one people learn to
    ignore. It is still reported, because a source that is *still* awaiting
    tomorrow is a mapping that does not work.
    """
    integration_rows = [item.to_dict(now) for item in integrations]
    source_rows = [item.to_dict(now, floor_s=floor_s) for item in sources]
    # "unknown" is in here and "unconfigured" is not: an integration somebody
    # configured and which has never once reported is the silent failure this
    # module exists for — a worker that is not running looks exactly like it.
    bad_integrations = {"down", "stale", "unknown"}
    problems = [
        row["name"] for row in integration_rows if row["status"] in bad_integrations
    ] + [row["name"] for row in source_rows if row["status"] == "no recent reading"]
    return {
        "ok": not problems,
        "configured": any(
            row["status"] not in {"unconfigured", "disabled"}
            for row in integration_rows
        ),
        "checked_at": now.isoformat(),
        "problems": problems,
        "awaiting": [
            row["name"] for row in source_rows if row["status"] == "never reported"
        ],
        "integrations": integration_rows,
        "sources": source_rows,
    }
