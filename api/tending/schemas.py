"""Request bodies, and the one place a stored row becomes a response.

Both stores serialise through here, so mock mode and live mode cannot answer in
different shapes — the same arrangement the inventory API's Register uses, for the
same reason.

Two notes on what leaves this module:

* **the feed token is never a field.** It appears inside ``webcal_url`` and
  ``https_url``, because that is what a subscriber pastes into a calendar, and
  nowhere else. A ``token`` key on the response would end up in a log, a
  screenshot or a support thread within a week;
* **``confidence``, ``degraded`` and ``degradations`` ride on ``Task``**, beyond
  contract 1.2.0. the design added exactly these to ``WaterBalance`` and
  ``FrostAlert`` and gave the reason: an answer built on a degraded input must
  not arrive looking like a clean one. A task generated from that same water
  balance is the next link in the chain. They are additive, so a client on
  1.2.0 is unaffected, and the change is requested of the maintainers in the pull
  request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from tending import tokens


class CareRuleCreate(BaseModel):
    """``POST /tending/care-rules``."""

    id: str | None = None
    species_id: str | None = None
    specimen_id: str | None = None
    task_type: str
    strategy: str = "interval"
    base_interval_days: int | None = None
    amount_ml: int | None = None
    modifiers: dict[str, Any] = Field(default_factory=dict)
    months: list[int] = Field(default_factory=list)
    enabled: bool = True


class CalendarFeedCreate(BaseModel):
    """``POST /tending/feeds``. The token is minted by the store, never supplied."""

    member_id: str
    name: str
    filters: dict[str, Any] = Field(default_factory=dict)
    push_target: str = "none"


class TaskCompletion(BaseModel):
    """``POST /tending/tasks/{task_id}/complete``."""

    completed_by: str | None = None
    amount_ml: int | None = None
    notes: str | None = None
    new_location_id: str | None = None


class BatchCompletion(BaseModel):
    """``POST /tending/tasks/complete-batch`` — what Morning Rounds sends."""

    task_ids: list[str]
    completed_by: str | None = None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=UTC)
        return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def deep_link(specimen_id: str) -> str:
    """One tap from a calendar event to the facet that completes the task."""
    return f"/specimen/{specimen_id}/tending"


def task_out(row: dict[str, Any]) -> dict[str, Any]:
    """A stored task as the contract's ``Task``."""
    specimen = row.get("specimen") or {"id": row.get("specimen_id")}
    return {
        "id": str(row["id"]),
        "specimen": {
            "id": str(specimen.get("id")),
            "display_name": specimen.get("display_name") or "Unnamed specimen",
            "is_outdoor": bool(specimen.get("is_outdoor")),
            "thumb_url": specimen.get("thumb_url"),
        },
        "task_type": row["task_type"],
        "due_at": _iso(row["due_at"]),
        "all_day": bool(row.get("all_day", True)),
        "status": row["status"],
        "satisfied_by": row.get("satisfied_by"),
        "amount_ml": row.get("amount_ml"),
        "priority": row.get("priority") or "normal",
        "title": row["title"],
        "plain_title": row["plain_title"],
        "detail": row.get("detail"),
        "completed_at": _iso(row.get("completed_at")),
        "completed_by": row.get("completed_by"),
        "deep_link": deep_link(str(specimen.get("id"))),
        # Stored on the row (migration 004's columns), so a completed
        # task keeps what it knew. ``None`` is still a real answer and is not
        # the same as "high": a row written never recorded one, and
        # the column is never back-filled. ``detail`` is the fallback for
        # ``degraded`` on such a row; it was only written with a caveat.
        "confidence": row.get("confidence"),
        "degraded": (
            bool(row["degraded"]) if "degraded" in row else bool(row.get("detail"))
        ),
        "degradations": row.get("degradations") or [],
    }


def ics_task(row: dict[str, Any]) -> dict[str, Any]:
    """The same task, shaped for :mod:`tending.ics`."""
    out = task_out(row)
    out["ics_uid"] = row["ics_uid"]
    out["ics_sequence"] = int(row.get("ics_sequence") or 0)
    return out


def care_rule_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "species_id": row.get("species_id"),
        "specimen_id": row.get("specimen_id"),
        "task_type": row["task_type"],
        "strategy": row.get("strategy") or "interval",
        "base_interval_days": row.get("base_interval_days"),
        "amount_ml": row.get("amount_ml"),
        "modifiers": row.get("modifiers") or {},
        "months": list(row.get("months") or []),
        "enabled": bool(row.get("enabled", True)),
    }


def feed_out(
    row: dict[str, Any], *, base_url: str, push_status: str = "off"
) -> dict[str, Any]:
    """A feed as the contract's ``CalendarFeed``. The token is in the URLs only.

    A revoked feed keeps its row and its name so the Ministry Office can show
    that it was revoked, but its URLs are withheld: publishing the rotated token
    of a feed somebody has just cut off would undo the cutting off.

    ``push_status`` is derived by ``tending.push.status_of`` — it reads whether
    the operator's secret file exists, which is not this module's business.
    ``push_state`` and ``push_config`` are never served: the first is the
    adapter's bookkeeping, the second must never hold anything.
    """
    revoked = bool(row.get("revoked_at"))
    token = "" if revoked else str(row["token"])
    return {
        "id": str(row["id"]),
        "member_id": str(row["member_id"]),
        "name": row["name"],
        "webcal_url": "" if revoked else tokens.webcal_url(base_url, token),
        "https_url": "" if revoked else tokens.https_url(base_url, token),
        "filters": row.get("filters") or {},
        "push_target": row.get("push_target") or "none",
        "push_status": push_status,
        "push_last_ok_at": _iso(row.get("push_last_ok_at")),
        "push_error": row.get("push_error"),
        "last_rendered_at": _iso(row.get("last_rendered_at")),
        "revoked": revoked,
    }
