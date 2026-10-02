"""Calendar push: when a feed owes one, and what it pushes.

The hub's adapter (``workers.hub.calendar``) makes a CalDAV collection
match a set of events and schedules nothing. This module decides the two things
the design leaves to the scheduler: **what** a feed's events are, and **when** it owes a push.

## What

Exactly what :func:`tending.service.render_feed` serves for the same feed: the
same window, the same filters, the same one-event-per-UID rule, each event
built by the same :func:`tending.ics.event_for`. A pushed calendar and a
subscribed one are cut from one read, so they cannot disagree.

One case needs more than that. A subscribed calendar mirrors the feed, so a
task that *leaves* the feed while it is still in the window — its plant was
carried indoors and the feed is "outdoor only" — disappears from a subscriber's
calendar on their next refresh. A pushed calendar holds what it was given and
nobody ``DELETE``s, so the push sends that event once more as
``STATUS:CANCELLED`` with its ``SEQUENCE`` bumped, and remembers it did. If the
task comes back into the feed, its event goes out again above the sequence the
cancellation used. A task that ages out of the window is left alone: that is
history, not a withdrawal, and cancelling it would rewrite last fortnight.

## When

A feed **owes** a push when one of its events has a UID the CalDAV server has
not been sent, or a ``SEQUENCE`` above the one it was sent at — read against
``push_state``, the adapter's own per-UID memory. That is the adapter's own
idempotence rule turned into a question, so "owes a push" and "a push would
write something" are the same test and cannot drift apart.

Every change that alters a feed's events bumps a ``SEQUENCE`` or adds a UID —
completion, batch completion, rain or sensor satisfaction, a rule change, a
recurrence re-anchor, a frost task withdrawn, a relocation — because the ICS
feed has needed exactly that to tell a subscriber anything. So rather
than a hook at each of those places, which a ninth kind of change would one day
forget, the check runs after every request that can change the schedule:

1. **After the response** (a FastAPI background task) on every completion,
   batch completion, rule create, feed create, and every read that runs
   generation (Morning Rounds, the task list, an ICS fetch). Generation is
   where rain and sensor satisfaction, re-anchoring and frost withdrawal are
   *discovered*, so a change found on a read is pushed by that read. A write
   generates once more before it pushes: a completion re-anchors the plant's
   later occurrences, and those exist only after the next pass.
2. **A sweep every** :data:`SWEEP_INTERVAL_S` **seconds** in each API process,
   which runs generation itself. Generation runs on read, so weather that
   satisfies a task while nobody has the app open is otherwise found only when
   somebody next looks; the sweep is what makes the five-minute bound hold
   then. It costs one query when no feed pushes.

Both paths set ``push_dirty_since`` when a feed owes a push and clear it on a
clean push that started after it was set. Two API replicas, a background task
and a sweep landing together, or a retry, are harmless: the adapter writes
conditionally by UID and SEQUENCE. Within one process a per-feed lock keeps two
pushes of one feed from racing, and the second re-reads and usually finds
nothing owed.

## Revoke stops it at once

the design. The revoke route calls :func:`stop`, which cancels the adapter
call in flight for that feed in this process — a request already on the wire
may land, nothing after it is sent. The other API replica cannot be reached
that way, so every push re-reads its feed between batches of
:data:`PUSH_BATCH` events and stops when it finds it revoked; no new push of a
revoked feed starts anywhere. A push cut short records nothing.

## What is kept, and what never is

``push_state``, ``push_dirty_since``, ``push_last_ok_at`` and ``push_error``
(migration 007). Never the CalDAV credential — the adapter reads the
operator's secret file at push time and this module never sees its lines —
and never the feed token, which is in no event, no error and no log line here.
Every error stored is run through ``workers.hub.credentials.credential_reason``
first and replaced whole if it looks like it carries anything.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import httpx
from workers.hub.calendar import (
    AwaitingOperator,
    CaldavTarget,
    CalendarEvent,
    Known,
    PushResult,
    TargetInvalid,
    push,
    secret_name,
)
from workers.hub.credentials import credential_reason
from workers.hub.settings import HubSettings

from tending import ics, service
from tending.repository import PushOutcome, Record, TendingRepository

#: How often each API process looks for a change nobody's request found. A
#: minute is well inside the five-minute bound, and costs one query when no
#: feed pushes. See the module docstring.
SWEEP_INTERVAL_S = 60.0

#: ``push_status`` values (contract 1.9.0, the design).
OFF, AWAITING_OPERATOR, OK, FAILING = "off", "awaiting_operator", "ok", "failing"

#: What a withdrawn event says for itself, in a calendar nobody can reply to.
LEFT_FEED_DETAIL = (
    "No longer in this calendar: the plant moved out of what this feed shows. "
    "Nothing to do here."
)

#: For a test or a demo: given the target, the ``httpx.AsyncClient`` to push
#: with (an ``httpx.MockTransport`` fake). ``None`` lets the adapter build its
#: own client — basic auth, a timeout, no redirects — which is the only client
#: that ever carries the operator's credential.
client_factory: Callable[[CaldavTarget], httpx.AsyncClient] | None = None


def hub_settings() -> HubSettings:
    """The hub's settings, for ``MOH_SECRETS_DIR``. Read per push, never cached."""
    return HubSettings()


# ------------------------------------------------------------------ status


def is_pushing(feed: Record) -> bool:
    return feed.get("push_target") == "caldav" and not feed.get("revoked_at")


def status_of(feed: Record, settings: HubSettings | None = None) -> str:
    """``push_status``, derived and never stored (migration 007's comment).

    ``off`` for no push or a revoked feed; ``awaiting_operator`` while the
    operator has not provisioned ``moh_caldav_<feed_id>`` — a setup step, not a
    failure; ``failing`` while the last push left an error; ``ok`` otherwise,
    including a feed whose secret is in place and whose first push has not run
    yet (``push_last_ok_at`` is then null, which says so).
    """
    if not is_pushing(feed):
        return OFF
    settings = settings or hub_settings()
    if not (settings.secrets_dir / secret_name(str(feed["id"]))).is_file():
        return AWAITING_OPERATOR
    return FAILING if feed.get("push_error") else OK


# ------------------------------------------------------------------ events


def _known(state: dict[str, Any]) -> dict[str, Known]:
    return {
        uid: Known(int(entry.get("sequence") or 0), entry.get("etag"))
        for uid, entry in state.items()
        if isinstance(entry, dict)
    }


def plan(
    feed: Record, window: list[Record], state: dict[str, Any]
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """The tasks one push sends; the UIDs in the feed; the UIDs withdrawn from it.

    ``window`` is every task in the feed window before filters
    (:func:`tending.service.window_tasks`). Sequences are raised above any
    withdrawal the server already holds; see the module docstring.
    """
    tasks = service.feed_events(window, feed)
    in_feed = {str(task["ics_uid"]) for task in tasks}
    out: list[dict[str, Any]] = []
    for task in tasks:
        held = state.get(str(task["ics_uid"])) or {}
        if held.get("left"):
            task = {
                **task,
                "ics_sequence": max(
                    int(task["ics_sequence"]), int(held.get("sequence") or 0) + 1
                ),
            }
        out.append(task)

    withdrawn: set[str] = set()
    for task in service.feed_events(window, {}):
        uid = str(task["ics_uid"])
        held = state.get(uid)
        if uid in in_feed or not held or held.get("left"):
            continue
        withdrawn.add(uid)
        out.append(
            {
                **task,
                "status": "cancelled",
                "detail": LEFT_FEED_DETAIL,
                "ics_sequence": max(
                    int(task["ics_sequence"]), int(held.get("sequence") or 0)
                )
                + 1,
            }
        )
    return out, in_feed, withdrawn


def owes(tasks: list[dict[str, Any]], state: dict[str, Any]) -> bool:
    """Would the adapter write anything? Its own rule, asked without asking it."""
    for task in tasks:
        held = state.get(str(task["ics_uid"]))
        if held is None or int(task["ics_sequence"]) > int(held.get("sequence") or 0):
            return True
    return False


def calendar_events(
    tasks: list[dict[str, Any]], *, base_url: str, now: datetime
) -> list[CalendarEvent]:
    """The hub's ``CalendarEvent`` per task, from the renderer the ICS feed uses."""
    events: list[CalendarEvent] = []
    for task in tasks:
        vevent = ics.event_for(task, base_url=base_url, now=now)
        events.append(
            CalendarEvent(
                uid=str(task["ics_uid"]),
                sequence=int(task.get("ics_sequence") or 0),
                status=str(vevent.get("status") or "CONFIRMED"),
                vevent=vevent.to_ical().decode("utf-8"),
            )
        )
    return events


# ------------------------------------------------------------------ errors


def safe_error(sentence: str | None, feed: Record) -> str:
    """A sentence fit for ``push_error``: The hub's escalation 3, and the feed token.

    The adapter's sentences are already redacted; this is the second gate for
    anything stored, including the two this module composes around
    ``TargetInvalid``. One that looks like it carries a credential, or carries
    this feed's token, is replaced whole rather than trimmed.
    """
    text = (sentence or "").strip() or "Calendar push failed for a reason not given."
    token = str(feed.get("token") or "")
    if credential_reason(text, None) or (token and token in text):
        return (
            "Calendar push failed, and the reason looked like it carried a "
            "credential, so it is not shown. Check the CalDAV secret for this feed."
        )
    return text


# ------------------------------------------------------------------ pushing

_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]
_LOCKS = weakref.WeakKeyDictionary()


def _lock(feed_id: str) -> asyncio.Lock:
    locks = _LOCKS.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(feed_id, asyncio.Lock())


async def push_feed(
    repo: TendingRepository,
    feed_id: str,
    *,
    base_url: str,
    window: list[Record] | None = None,
    now: datetime | None = None,
) -> str:
    """Push one feed if it owes a push. Returns what happened, in a word.

    ``ok``, ``nothing_owed``, ``awaiting_operator``, ``failing`` or ``off``.
    Re-reads the feed under its lock, so a revoke that landed while this was
    queued stops it before any request.
    """
    async with _lock(feed_id):
        feed = await repo.feed(feed_id)
        if feed is None or not is_pushing(feed):
            return OFF
        now = now or datetime.now(UTC)
        if window is None:
            window = await service.window_tasks(repo, now)
        state: dict[str, Any] = dict(feed.get("push_state") or {})
        tasks, in_feed, withdrawn = plan(feed, window, state)
        if not owes(tasks, state):
            return "nothing_owed"
        await repo.mark_push_owed(feed_id, now)

        settings = hub_settings()
        started = datetime.now(UTC)
        try:
            target = CaldavTarget.for_feed(feed_id, settings)
        except AwaitingOperator:
            # A setup step: push_status says so from the missing file, and the
            # feed stays owed so the push goes the moment the secret exists.
            return AWAITING_OPERATOR
        except TargetInvalid as invalid:
            await repo.record_push(
                feed_id,
                PushOutcome(
                    state=state,
                    started_at=started,
                    error=safe_error(str(invalid), feed),
                ),
            )
            return FAILING

        events = calendar_events(tasks, base_url=base_url, now=now)
        result = await _push_until_revoked(
            repo, feed_id, target, events, state, settings
        )
        if result is None:
            return OFF

        kept = _kept_state(
            result.state,
            previous=state,
            window=window,
            in_feed=in_feed,
            withdrawn=withdrawn,
            outcomes=result.outcomes,
        )
        if result.ok:
            await repo.record_push(
                feed_id,
                PushOutcome(state=kept, started_at=started, ok_at=result.pushed_at),
            )
            return OK
        await repo.record_push(
            feed_id,
            PushOutcome(
                state=kept, started_at=started, error=safe_error(result.error, feed)
            ),
        )
        return FAILING


#: Events per adapter call. Between calls the feed is read again, so a revoke
#: made on *another* API replica stops this push within one batch; one made in
#: this process cancels it outright (:func:`stop`). Each call is one TLS
#: connection, so a smaller batch costs handshakes for no gain.
PUSH_BATCH = 8

#: Feeds revoked in this process, and the adapter call each is running.
_STOPPED: set[str] = set()
_RUNNING: dict[str, asyncio.Future[PushResult]] = {}


def stop(feed_id: str) -> None:
    """Revoked: no further PUT for this feed from this process, from now.

    Cancels the adapter call in flight, if any — a request already on the wire
    may still land, nothing after it is sent — and refuses any later one. The
    router calls it after the revoke is stored; every replica also re-reads the
    feed between batches, which is what stops a push running elsewhere.
    """
    _STOPPED.add(feed_id)
    running = _RUNNING.get(feed_id)
    if running is not None:
        running.cancel()


async def _push_until_revoked(
    repo: TendingRepository,
    feed_id: str,
    target: CaldavTarget,
    events: list[CalendarEvent],
    state: dict[str, Any],
    settings: HubSettings,
) -> PushResult | None:
    """The hub's ``push`` in batches, stopping the moment the feed is revoked.

    Returns the batches' results merged as one, or ``None`` if the feed was
    revoked part-way: nothing is recorded for a feed that is no longer there to
    push. A batch that failed outright ends the push, as it ends the hub's own.
    """
    known = _known(state)
    merged: PushResult | None = None
    for start in range(0, len(events), PUSH_BATCH):
        if start and not is_pushing(await repo.feed(feed_id) or {}):
            return None
        if feed_id in _STOPPED:
            return None
        call = asyncio.ensure_future(
            _adapter(target, events[start : start + PUSH_BATCH], known, settings)
        )
        _RUNNING[feed_id] = call
        try:
            result = await call
        except asyncio.CancelledError:
            if call.cancelled() and feed_id in _STOPPED:
                return None
            raise
        finally:
            _RUNNING.pop(feed_id, None)
        known = result.state
        if merged is None:
            merged = result
        else:
            merged.outcomes.update(result.outcomes)
            merged.state = result.state
            merged.pushed_at = result.pushed_at
            merged.error = merged.error or result.error
            merged.error_kind = merged.error_kind or result.error_kind
        if "failed" in result.outcomes.values():
            break
    return merged


async def _adapter(
    target: CaldavTarget,
    events: list[CalendarEvent],
    known: dict[str, Known],
    settings: HubSettings,
) -> PushResult:
    if client_factory is None:
        return await push(target, events, known=known, settings=settings)
    async with client_factory(target) as client:
        return await push(target, events, known=known, settings=settings, client=client)


def _kept_state(
    state: dict[str, Known],
    *,
    previous: dict[str, Any],
    window: list[Record],
    in_feed: set[str],
    withdrawn: set[str],
    outcomes: dict[str, str],
) -> dict[str, Any]:
    """``push_state`` as stored: The hub's memory, trimmed to the window, withdrawals marked.

    ``left`` marks a UID the server holds as cancelled because its task left
    the feed. It is set when that cancellation lands, carried while the task
    stays out, and dropped when the task comes back and is written again — so
    a withdrawal is pushed once, not on every push after it.

    A UID that has aged out of the window is dropped — it will never be pushed
    again, and dropping the adapter's memory is always safe (migration 007).
    """
    in_window = {str(row["ics_uid"]) for row in window}
    kept: dict[str, Any] = {}
    for uid, known in state.items():
        if uid not in in_window:
            continue
        entry = known.to_dict()
        landed = outcomes.get(uid) in ("cancelled", "unchanged")
        stays_out = uid not in in_feed and bool((previous.get(uid) or {}).get("left"))
        if (uid in withdrawn and landed) or stays_out:
            entry["left"] = True
        kept[uid] = entry
    return kept


async def push_owed(
    repo: TendingRepository,
    *,
    base_url: str,
    generate: bool = False,
    now: datetime | None = None,
) -> dict[str, str]:
    """Push every non-revoked CalDAV feed that owes one. One window read for all.

    ``generate`` runs generation first, for the sweep: with nobody's request
    in flight, nothing else would discover weather that settled a task.
    """
    feeds = [feed for feed in await repo.feeds() if is_pushing(feed)]
    if not feeds:
        return {}
    now = now or datetime.now(UTC)
    if generate:
        await service.generate_tasks(repo, today=now.date())
    window = await service.window_tasks(repo, now)
    results: dict[str, str] = {}
    for feed in feeds:
        feed_id = str(feed["id"])
        results[feed_id] = await push_feed(
            repo, feed_id, base_url=base_url, window=window, now=now
        )
    return results


async def after_change(
    repo: TendingRepository, base_url: str, *, generate: bool = False
) -> None:
    """The background task the router adds after a request. Never raises."""
    # A push must never take a request down with it. Nothing is logged: this
    # package logs nothing at all (test_tending_tokens), because it handles the
    # one credential the app issues. A push that could not run leaves its feed
    # owing one, with ``push_dirty_since`` set and ``push_last_ok_at`` going
    # stale, which is what the Office reads; the sweep tries again.
    with suppress(Exception):
        await push_owed(repo, base_url=base_url, generate=generate)


async def sweep_forever(
    repository: Callable[[], Awaitable[TendingRepository]],
    base_url: Callable[[], str],
    *,
    interval_s: float = SWEEP_INTERVAL_S,
) -> None:
    """Every ``interval_s``: generate, then push what is owed. Until cancelled."""
    while True:
        await asyncio.sleep(interval_s)
        # As in :func:`after_change`: never raises, never logs, tries again.
        with suppress(Exception):
            await push_owed(await repository(), base_url=base_url(), generate=True)


def sweeping(
    repository: Callable[[], Awaitable[TendingRepository]],
    base_url: Callable[[], str],
) -> Callable[[Any], AbstractAsyncContextManager[None]]:
    """A router lifespan that runs :func:`sweep_forever` for the app's lifetime."""

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        task = asyncio.create_task(sweep_forever(repository, base_url))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return lifespan
