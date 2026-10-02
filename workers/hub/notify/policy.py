"""When to interrupt somebody, and when to stay quiet — the hub.

The copy decides what a notification says. This module decides whether it is
sent at all, which is the harder half: a notification nobody wanted trains the
reader to swipe the next one away, and the next one is the freeze warning.

## The three cadences are different on purpose

**Rounds** go out once, at an hour a person chose, in the *site's* local time
and not the server's. A task list is not urgent — it is a list of things to do
today — so it waits for the morning and it never arrives twice.

**Frost is time-critical and says so.** The brief's own example: a Freeze
Warning issued at 2 PM for that night is not something to learn about at 3.
So the frost job runs on a short cycle, sends the moment the forecast changes
for the worse, and is the one kind that **ignores quiet hours** — a person who
asked not to be disturbed after ten did not mean "let the lemon tree die
quietly". :func:`may_send` makes that a stated exception rather than an
oversight, and a household that does not want it turns frost off entirely.

**Health waits.** A hub reboots, a Wi-Fi access point drops, a container
restarts. One failed poll is a blip; a fault is a failure that is still there
after :data:`HEALTH_GRACE_S`. Notifying on the first error would make this the
noisiest of the three and it is the least urgent.

## Not sending twice

There is no ``notification`` table in the frozen schema — this is escalation 1
in `the project notes` — so the ledger is derived from
``job_run``, which each job already writes. Every send records its
:attr:`~workers.hub.notify.model.Notification.dedupe_key` in ``job_run.detail``,
and the next run reads the recent rows back. It costs one indexed query
(``job_run_job_idx`` is on ``(job, started_at DESC)``) and needs no contract
change.

With no database — mock mode, and every test — the ledger is in-process, and
:class:`MemoryLedger` says so. A restart there can re-send today's rounds once.
That is stated rather than hidden, and it is the right trade: the alternative
is a mock stack that cannot demonstrate the feature at all.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from .model import URGENT_KINDS, Notification, Recipient

#: How long an integration must stay broken before it is worth a notification.
#: Two poll intervals plus a margin: one missed run is a blip, two is a
#: pattern, and a hub that comes back inside twenty minutes cost nobody a
#: plant.
HEALTH_GRACE_S = 1800.0

#: How long a sent key is remembered. Longer than any of the cadences, short
#: enough that ``job_run`` is not scanned back through a season.
LEDGER_WINDOW_S = 60 * 60 * 36

#: Jobs whose ``job_run`` rows carry ledger entries.
NOTIFY_JOBS: tuple[str, ...] = (
    "notify_rounds",
    "notify_frost",
    "notify_integration_health",
)

#: Where a send is recorded inside ``job_run.detail``.
LEDGER_FIELD = "notified"


def local_now(moment: datetime, timezone: str | None) -> datetime:
    """``moment`` in the site's own time, or UTC if the zone is unusable.

    Timestamps are stored UTC and local time is resolved per-site
    (`the project conventions`). A bad or missing zone falls back to UTC rather than
    raising: a notification an hour early is a nuisance, and a job that dies on
    a typo in ``site.timezone`` is a household that gets no notifications at
    all and no explanation.
    """
    if not timezone:
        return moment.astimezone(UTC)
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - any zoneinfo failure means "use UTC"
        return moment.astimezone(UTC)


def in_quiet_hours(hour: int, recipient: Recipient) -> bool:
    """Is ``hour`` inside this member's do-not-disturb window?

    The window wraps midnight, which is the normal case: 22 to 7 is nine hours
    of night, not fifteen hours of day.
    """
    start, end = recipient.quiet_from % 24, recipient.quiet_to % 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether to send, and — always — why not.

    A reason is recorded even for a quiet, correct no-op. "Why did I not get my
    rounds this morning?" has to be answerable from the job's own report, or
    the answer is a log file and an afternoon.
    """

    send: bool
    reason: str

    def __bool__(self) -> bool:
        return self.send


def may_send(
    notification: Notification,
    recipient: Recipient,
    *,
    local: datetime,
    already_sent: Iterable[str] = (),
) -> Decision:
    """The whole gate, in one function, in the order the reasons matter."""
    if not recipient.service:
        return Decision(False, f"{recipient.name} has no Home Assistant notify service")
    if not recipient.wants(notification.kind):
        return Decision(False, f"{recipient.name} has {notification.kind} turned off")
    if notification.dedupe_key in set(already_sent):
        return Decision(False, "already sent — this is not new news")
    if notification.kind == "rounds" and local.hour < recipient.rounds_hour:
        return Decision(
            False,
            f"too early: rounds go out at {recipient.rounds_hour:02d}:00 local "
            f"and it is {local.hour:02d}:{local.minute:02d}",
        )
    if in_quiet_hours(local.hour, recipient):
        if notification.kind in URGENT_KINDS:
            # Stated, not assumed. Frost is the one thing worth waking
            # somebody for, and a household that disagrees turns it off.
            return Decision(True, "quiet hours, overridden: frost is time-critical")
        return Decision(False, f"{recipient.name} is in quiet hours")
    return Decision(True, "due")


def health_is_sustained(
    row: Any, *, now: datetime, grace_s: float = HEALTH_GRACE_S
) -> bool:
    """Has this integration been broken long enough to be worth saying?

    Measured from ``last_ok_at``, which is the only evidence available about
    when it was last fine. An integration that has **never** been fine —
    ``last_ok_at`` is null — is not given the benefit of the grace period a
    second time: it has had it since the deployment started, and a hub that has
    never once answered is exactly the setup problem worth telling somebody
    about.
    """
    last_ok = row.get("last_ok_at") if hasattr(row, "get") else None
    if last_ok is None:
        return True
    if isinstance(last_ok, str):
        try:
            last_ok = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
        except ValueError:
            return True
    if last_ok.tzinfo is None:
        last_ok = last_ok.replace(tzinfo=UTC)
    return (now - last_ok) >= timedelta(seconds=grace_s)


# --------------------------------------------------------------- the ledger


class Ledger(Protocol):
    """What has already been said, so it is not said twice."""

    async def sent_keys(self, since: datetime) -> set[str]: ...

    async def record(self, job: str, keys: Sequence[str], *, at: datetime) -> None: ...


@dataclass(slots=True)
class MemoryLedger:
    """The ledger with no database. In-process, and honest about it.

    A restart forgets everything, so mock mode can send today's rounds a second
    time. That is a property of running without Postgres, not a bug to paper
    over with a file somewhere: the deployed stack has a database, and
    :class:`JobRunLedger` is what it uses.
    """

    #: Kept as ``{key: when}`` so the window can be applied the same way the
    #: database ledger applies it.
    entries: dict[str, datetime] = field(default_factory=dict)
    is_durable: bool = False

    async def sent_keys(self, since: datetime) -> set[str]:
        return {key for key, at in self.entries.items() if at >= since}

    async def record(self, job: str, keys: Sequence[str], *, at: datetime) -> None:
        for key in keys:
            self.entries[key] = at


@dataclass(slots=True)
class JobRunLedger:
    """The ledger derived from ``job_run``, which every job writes anyway.

    Reading is one indexed query; writing is the ``job_run`` row the job was
    going to write regardless, with the keys in its ``detail``. A dedicated
    ``notification`` table would be better and is escalated to the maintainers — this is the
    honest workaround, not a preference.
    """

    connection: Any
    is_durable: bool = True

    async def sent_keys(self, since: datetime) -> set[str]:
        from .. import store

        rows = await store.read_notified_keys(self.connection, since)
        keys: set[str] = set()
        for row in rows:
            detail = row.get("detail") if hasattr(row, "get") else None
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except ValueError:
                    detail = None
            if isinstance(detail, dict):
                for key in detail.get(LEDGER_FIELD) or ():
                    keys.add(str(key))
        return keys

    async def record(self, job: str, keys: Sequence[str], *, at: datetime) -> None:
        # Deliberately a no-op: the keys ride out on the job's own ``job_run``
        # row, written by the job with the rest of its report. Two writes for
        # one fact is two things to keep in step.
        return None


def window_start(now: datetime, seconds: float = LEDGER_WINDOW_S) -> datetime:
    return now - timedelta(seconds=seconds)


def today_local(moment: datetime, timezone: str | None) -> date:
    return local_now(moment, timezone).date()
