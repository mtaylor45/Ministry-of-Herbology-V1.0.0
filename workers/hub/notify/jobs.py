"""The three notification jobs — the hub.

the earlier jobs read the world and wrote to a hypertable. These reach a person, which
changes what a job owes its reader in two ways.

**Every job says why it stayed quiet.** A poll that returns nothing is visible
as an empty hypertable. A notification that was not sent is visible as nothing
at all, and the question somebody asks the next morning — *why did I not get my
rounds?* — has to be answerable from the job's own return value. So every
:class:`~workers.hub.notify.policy.Decision` that came out ``False`` is in the
report, with its reason, whether it was quiet hours, a member who turned rounds
off, or simply that there was nothing due.

**A failure to notify is a failure.** Under the design Home Assistant is the only
route out — there is no push service of this application's own — so a hub that
is down does not mean "the household was not interrupted", it means "the frost
warning did not arrive and nobody knows". The delivery failure lands on
``integration.last_error`` like every other, and the send is **not** written to
the ledger, so the next run tries again rather than treating a message that was
never delivered as already said.

## The cadences, and the one that matters

``notify_frost`` runs every fifteen minutes. That is the whole point of it: the
brief's example is a Freeze Warning issued at 2 PM for that night, and a job on
a daily schedule learns about it at seven the next morning, which is after the
plants died. The key is the forecast's *content*, so a warning that worsens
gets through and a warning that merely repeats does not.

``notify_rounds`` runs hourly and sends at most once a day, when the site's
local clock has reached the hour the member chose.

``notify_integration_health`` runs hourly and waits out
:data:`~workers.hub.notify.policy.HEALTH_GRACE_S` before saying anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ..health import redact
from ..settings import HubSettings, get_settings
from .channels import Delivery, NotifyChannel, build_channel
from .copy import frost_notification, health_notification, rounds_notification
from .model import KINDS, Notification, Recipient
from .policy import (
    HEALTH_GRACE_S,
    LEDGER_FIELD,
    Decision,
    JobRunLedger,
    Ledger,
    MemoryLedger,
    health_is_sustained,
    local_now,
    may_send,
    window_start,
)
from .state import MinistryReader, build_reader

#: The ``integration`` row a notification failure is recorded against. The
#: notification path is Home Assistant's, so a notification that did not go out
#: is a fact about the Home Assistant integration, not about a fourth thing.
HA_INTEGRATION = ("home_assistant", "Home Assistant")

#: Kept process-wide so mock mode does not re-send today's rounds on every
#: single cron tick. It still forgets on restart, which
#: :class:`~workers.hub.notify.policy.MemoryLedger` says out loud.
_MEMORY_LEDGER = MemoryLedger()


def _settings(ctx: Mapping[str, Any]) -> HubSettings:
    settings = ctx.get("settings")
    return settings if isinstance(settings, HubSettings) else get_settings()


def _secrets(settings: HubSettings) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            settings.ha_token.get_secret_value(),
            settings.mqtt_password.get_secret_value(),
        )
        if value
    )


def _reader(ctx: Mapping[str, Any], settings: HubSettings) -> MinistryReader:
    reader = ctx.get("reader")
    return reader if reader is not None else build_reader(settings)


def _channel(ctx: Mapping[str, Any], settings: HubSettings) -> NotifyChannel:
    channel = ctx.get("channel")
    return channel if channel is not None else build_channel(settings)


def _ledger(ctx: Mapping[str, Any]) -> Ledger:
    ledger = ctx.get("ledger")
    if ledger is not None:
        return ledger
    connection = ctx.get("connection")
    if connection is not None:
        return JobRunLedger(connection)
    return _MEMORY_LEDGER


async def recipients_for(
    ctx: Mapping[str, Any], settings: HubSettings, reader: MinistryReader
) -> tuple[list[Recipient], list[str]]:
    """Who this deployment can notify, and every reason somebody is missing.

    The second half is the part worth having. "Nobody got the frost warning" is
    a sentence with four possible endings — no members, no companion app, the
    kind turned off, the API unreachable — and a job that returns an empty list
    with no explanation has made the household guess.
    """
    provided = ctx.get("recipients")
    if provided is not None:
        return list(provided), []

    notes: list[str] = []
    try:
        rows = await reader.members()
    except Exception as exc:  # noqa: BLE001 - reported, never raised at Arq
        return [], [redact(f"could not read members: {exc}", _secrets(settings)) or ""]

    recipients: list[Recipient] = []
    for row in rows:
        recipient = Recipient.from_member_row(row)
        if recipient is None and settings.ha_notify_service:
            # The deployment-wide fallback: one household, one phone, nobody
            # who wants to edit a JSON blob to get their watering reminders.
            recipient = Recipient.from_member_row(
                {
                    **row,
                    "notify_prefs": {
                        "home_assistant": {"service": settings.ha_notify_service}
                    },
                }
            )
        if recipient is None:
            notes.append(
                f"{row.get('name') or 'a member'} has no Home Assistant notify "
                "service in notify_prefs"
            )
            continue
        recipients.append(recipient)
    return recipients, notes


async def deliver(
    notifications: Sequence[tuple[Notification, Recipient]],
    *,
    channel: NotifyChannel,
    local_for: Any,
    already_sent: set[str],
) -> tuple[list[Delivery], list[dict[str, str]]]:
    """Gate each notification, send the ones that pass, and record both halves."""
    deliveries: list[Delivery] = []
    skipped: list[dict[str, str]] = []
    for notification, recipient in notifications:
        decision: Decision = may_send(
            notification,
            recipient,
            local=local_for(recipient),
            already_sent=already_sent,
        )
        if not decision:
            skipped.append(
                {
                    "kind": notification.kind,
                    "member_id": recipient.member_id,
                    "reason": decision.reason,
                }
            )
            continue
        deliveries.append(await channel.send(notification, recipient))
        # Within one run as well as across runs: two members sharing a service
        # must not each trigger the same message on the same phone.
        already_sent.add(notification.dedupe_key)
    return deliveries, skipped


async def _finish(
    ctx: Mapping[str, Any],
    job: str,
    *,
    started_at: datetime,
    now: datetime,
    deliveries: Sequence[Delivery],
    skipped: Sequence[Mapping[str, str]],
    notes: Sequence[str],
    settings: HubSettings,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One report, one ``job_run`` row, and the ledger entries that ride on it.

    Only *successful* deliveries are written to the ledger. A notification the
    hub refused was not said, and a ledger that recorded the attempt would make
    the retry impossible — which is the difference between a frost warning that
    arrives ten minutes late and one that never arrives at all.

    The ledger entry is stamped with ``now`` — the job's own clock — and not
    with the wall clock it happened to finish on. The two are the same in a
    deployment and are not the same in a test, and a ledger that reads back
    against one clock and writes against another is a dedupe that quietly does
    nothing.
    """
    finished_at = datetime.now(UTC)
    sent = [item for item in deliveries if item.ok]
    failed = [item for item in deliveries if not item.ok]
    keys = sorted({item.dedupe_key for item in sent if item.dedupe_key})

    detail: dict[str, Any] = {
        "job": job,
        "sent": [item.to_dict() for item in sent],
        "failed": [item.to_dict() for item in failed],
        "skipped": list(skipped),
        "notes": list(notes),
        LEDGER_FIELD: keys,
        **dict(extra or {}),
    }

    error = None
    if failed:
        reasons = ", ".join(sorted({item.reason for item in failed}))
        error = redact(
            f"{len(failed)} notification(s) could not be delivered: {reasons}",
            _secrets(settings),
        )

    connection = ctx.get("connection")
    if connection is not None:
        from .. import store

        if error:
            await store.record_error(connection, *HA_INTEGRATION, error)
        await store.record_job_run(
            connection,
            job,
            started_at=started_at,
            finished_at=finished_at,
            ok=not failed,
            detail=detail,
        )
    if keys:
        await _ledger(ctx).record(job, keys, at=now)

    return {
        **detail,
        "ok": not failed,
        "error": error,
        "started_at": started_at.isoformat(),
        "took_ms": round((finished_at - started_at).total_seconds() * 1000, 1),
    }


def _local_for(settings: HubSettings, now: datetime) -> Any:
    from ..mocks.ministry import _read

    site = _read(settings.fixtures_dir / "site.json")
    timezone = site.get("timezone") if isinstance(site, Mapping) else None
    return lambda _recipient: local_now(now, timezone)


# ------------------------------------------------------------------- the jobs


async def notify_rounds(ctx: dict[str, Any]) -> dict[str, Any]:
    """Today's rounds, once, at the hour the member asked for.

    There is deliberately **no all-clear**. A day with nothing due sends
    nothing, because ``MorningRounds.unscheduled[]`` means the app cannot
    always tell "nothing needs doing" from "I could not work out what these
    plants need" — and of those two, only silence is honest about both.
    """
    settings = _settings(ctx)
    started_at = datetime.now(UTC)
    now = ctx.get("now") or started_at
    reader = _reader(ctx, settings)
    channel = _channel(ctx, settings)

    recipients, notes = await recipients_for(ctx, settings, reader)
    try:
        rounds = await reader.rounds()
    except Exception as exc:  # noqa: BLE001 - reported, never raised at Arq
        return await _finish(
            ctx,
            "notify_rounds",
            started_at=started_at,
            now=now,
            deliveries=[],
            skipped=[],
            notes=[
                *notes,
                redact(f"could not read the rounds: {exc}", _secrets(settings)) or "",
            ],
            settings=settings,
        )

    local_for = _local_for(settings, now)
    pending: list[tuple[Notification, Recipient]] = []
    skipped: list[dict[str, str]] = []
    for recipient in recipients:
        notification = rounds_notification(
            rounds, recipient, today=local_for(recipient).date()
        )
        if notification is None:
            skipped.append(
                {
                    "kind": "rounds",
                    "member_id": recipient.member_id,
                    "reason": "nothing is due — no all-clear is sent",
                }
            )
            continue
        pending.append((notification, recipient))

    already = await _ledger(ctx).sent_keys(window_start(now))
    deliveries, gated = await deliver(
        pending, channel=channel, local_for=local_for, already_sent=already
    )
    return await _finish(
        ctx,
        "notify_rounds",
        started_at=started_at,
        now=now,
        deliveries=deliveries,
        skipped=[*skipped, *gated],
        notes=notes,
        settings=settings,
        extra={"due": len(rounds.get("due") or ()), "recipients": len(recipients)},
    )


async def notify_frost(ctx: dict[str, Any]) -> dict[str, Any]:
    """The frost alert, as soon as the forecast says so.

    Quiet hours do not apply (see :func:`~workers.hub.notify.policy.may_send`),
    and the message is marked time-sensitive so neither iOS's notification
    summary nor Android's doze mode holds it until the morning. A household
    that does not want to be woken turns ``frost`` off in ``notify_prefs``,
    which is a decision somebody made rather than one this worker made for
    them.
    """
    settings = _settings(ctx)
    started_at = datetime.now(UTC)
    now = ctx.get("now") or started_at
    reader = _reader(ctx, settings)
    channel = _channel(ctx, settings)

    recipients, notes = await recipients_for(ctx, settings, reader)
    try:
        report = await reader.frost()
    except Exception as exc:  # noqa: BLE001 - reported, never raised at Arq
        return await _finish(
            ctx,
            "notify_frost",
            started_at=started_at,
            now=now,
            deliveries=[],
            skipped=[],
            notes=[
                *notes,
                redact(f"could not read the frost report: {exc}", _secrets(settings))
                or "",
            ],
            settings=settings,
        )

    local_for = _local_for(settings, now)
    pending: list[tuple[Notification, Recipient]] = []
    skipped: list[dict[str, str]] = []
    for recipient in recipients:
        notification = frost_notification(report, recipient)
        if notification is None:
            skipped.append(
                {
                    "kind": "frost",
                    "member_id": recipient.member_id,
                    "reason": "no open frost alert",
                }
            )
            continue
        pending.append((notification, recipient))

    already = await _ledger(ctx).sent_keys(window_start(now))
    deliveries, gated = await deliver(
        pending, channel=channel, local_for=local_for, already_sent=already
    )
    unassessable = report.get("unassessable")
    return await _finish(
        ctx,
        "notify_frost",
        started_at=started_at,
        now=now,
        deliveries=deliveries,
        skipped=[*skipped, *gated],
        notes=notes,
        settings=settings,
        extra={
            "alerts": len(report.get("alerts") or ()),
            "unassessable": (
                len(unassessable) if isinstance(unassessable, list) else None
            ),
        },
    )


async def notify_integration_health(ctx: dict[str, Any]) -> dict[str, Any]:
    """Tell somebody when an adapter has stopped answering.

    an earlier release recorded every failure on ``integration.last_error`` so the Ministry
    Office could show it. This is the other half: an adapter
    that quietly stops is a month of missing indoor readings, and nobody opens
    the Ministry Office on a Tuesday to check.

    The grace period is the whole design. A hub reboots; a container restarts;
    a poll times out once. Notifying on the first error would make this the
    noisiest of the three jobs and the least useful, and a health alert people
    have learned to swipe away is worse than none.
    """
    settings = _settings(ctx)
    started_at = datetime.now(UTC)
    now = ctx.get("now") or started_at
    reader = _reader(ctx, settings)
    channel = _channel(ctx, settings)
    grace = float(
        ctx.get("grace_s") or settings.notify_health_grace_s or HEALTH_GRACE_S
    )

    report = ctx.get("health")
    if report is None:
        from ..tasks import hub_health

        report = await hub_health(dict(ctx))

    rows = [
        row for row in (report.get("integrations") or ()) if isinstance(row, Mapping)
    ]
    broken = [
        row
        for row in rows
        if str(row.get("status")) in {"down", "stale"}
        and health_is_sustained(row, now=now, grace_s=grace)
    ]
    waiting = [
        str(row.get("name"))
        for row in rows
        if str(row.get("status")) in {"down", "stale"} and row not in broken
    ]

    recipients, notes = await recipients_for(ctx, settings, reader)
    local_for = _local_for(settings, now)
    pending: list[tuple[Notification, Recipient]] = []
    skipped: list[dict[str, str]] = []
    for recipient in recipients:
        notification = health_notification({"integrations": broken}, recipient)
        if notification is None:
            skipped.append(
                {
                    "kind": "health",
                    "member_id": recipient.member_id,
                    "reason": "nothing has been broken long enough to say",
                }
            )
            continue
        pending.append((notification, recipient))

    already = await _ledger(ctx).sent_keys(window_start(now))
    deliveries, gated = await deliver(
        pending, channel=channel, local_for=local_for, already_sent=already
    )
    if waiting:
        notes = [
            *notes,
            "inside the grace period, not yet reported: " + ", ".join(sorted(waiting)),
        ]
    return await _finish(
        ctx,
        "notify_integration_health",
        started_at=started_at,
        now=now,
        deliveries=deliveries,
        skipped=[*skipped, *gated],
        notes=notes,
        settings=settings,
        extra={"broken": len(broken), "grace_s": grace},
    )


#: Every kind this package can send, for a test that asserts the three jobs and
#: the three ``notify_prefs`` switches have not drifted apart.
JOB_FOR_KIND: dict[str, Any] = {
    "rounds": notify_rounds,
    "frost": notify_frost,
    "health": notify_integration_health,
}
assert set(JOB_FOR_KIND) == set(KINDS)
