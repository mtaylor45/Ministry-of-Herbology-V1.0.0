"""Push a feed's events to a CalDAV collection — the hub.

The household's own calendar server (iCloud, Fastmail, Nextcloud, Radicale)
gets the same events the ICS feed serves, within minutes, instead of whenever
a subscribing client next remembers to refresh. G decides when and what; this
module only makes a collection match a set of events.

## How the collection is made to match

One resource per event, at ``<collection>/<uid>.ics``, written with ``PUT``:

* **New** — ``If-None-Match: *``, so a resource that is already there (another
  replica got there first, or the caller lost its state) is a ``412`` rather
  than an overwrite.
* **Known** — ``If-Match: <etag>`` with the ETag the last push returned, so an
  event somebody changed on their phone is a ``412`` rather than silently
  clobbered.
* **A ``412`` is not an error.** The resource is fetched and its ``SEQUENCE``
  compared: if the server already holds this sequence or a later one, the push
  for that UID is a no-op; otherwise it is written once more against the ETag
  the server just gave.
* **Never ``DELETE``.** A cancelled or satisfied task arrives as an event with
  ``STATUS:CANCELLED`` and a bumped ``SEQUENCE`` and is ``PUT`` like any other
  — the rule the ICS feed has followed because a deleted event leaves
  a stale copy on every device that already synced it.

**Idempotent by UID and SEQUENCE.** Given the state the last push returned
(:attr:`PushResult.state`), an event whose sequence the server already has is
reported ``unchanged`` and costs no request at all. Without that state it costs
one conditional ``PUT`` and one ``GET``, and is still reported ``unchanged``.

## Nothing secret leaves

The credential is three lines in an operator-provisioned file:
the collection URL, the username and an app password. It is read at push time
and kept nowhere. **No result, exception, or log line carries any of the
three** — not the password, not the username, and not the collection URL's
path either, because Fastmail's and Nextcloud's paths contain the username.
Errors name the *host* and say what to do. Every sentence is written here
rather than copied from ``httpx``, then run through :func:`workers.hub.health.redact`
with the username and password as literal secrets, then through
:func:`workers.hub.credentials.credential_reason`; one that still looks like
it carries something is replaced whole.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr

from ..credentials import credential_reason
from ..health import redact
from ..settings import DEFAULT_USER_AGENT, HubSettings

log = logging.getLogger(__name__)

#: Wraps each event so the resource is a whole iCalendar object (RFC 4791
#: §4.1: one VCALENDAR per resource). The same PRODID as the scheduler's feed, so the two
#: routes into a calendar are recognisably the same publisher.
PRODID = "-//The Ministry of Herbology//Tending//EN"

_SEQUENCE = re.compile(r"^SEQUENCE:(\d+)\s*$", re.MULTILINE)
_UID = re.compile(r"^UID:(.+?)\s*$", re.MULTILINE)


def secret_name(feed_id: str) -> str:
    """``moh_caldav_<feed_id>`` — the swarm secret one feed's push reads.

    The feed id is not a secret, so the Office can print the exact
    ``docker secret create`` command with this name in it.
    """
    return f"moh_caldav_{feed_id}"


# ------------------------------------------------------------------ errors


class AwaitingOperator(Exception):
    """No credential file for this feed yet. A setup step, not a failure."""


class TargetInvalid(ValueError):
    """The credential file is there and cannot be used. Says why, not what."""


# ------------------------------------------------------------------ target


@dataclass(frozen=True, slots=True, repr=False)
class CaldavTarget:
    """Where one feed pushes to. Built from the secret file, kept for one push.

    ``repr`` names the host only. The username is in the class because the
    server needs it, not because anything may print it.
    """

    collection_url: str
    username: str
    password: SecretStr
    #: Which secret this came from, for sentences an operator acts on.
    secret: str = "moh_caldav_<feed_id>"

    def __repr__(self) -> str:
        # The host only: Fastmail's and Nextcloud's collection paths contain
        # the username, so even the URL is not printed.
        return f"CaldavTarget(host={self.host!r}, secret={self.secret!r})"

    @property
    def host(self) -> str:
        return urlsplit(self.collection_url).hostname or "the CalDAV server"

    def resource_url(self, uid: str) -> str:
        return f"{self.collection_url}{quote(uid, safe='')}.ics"

    def secrets(self) -> tuple[str, ...]:
        return tuple(v for v in (self.password.get_secret_value(), self.username) if v)

    @classmethod
    def for_feed(cls, feed_id: str, settings: HubSettings) -> CaldavTarget:
        return cls.from_secret_file(settings.secrets_dir / secret_name(feed_id))

    @classmethod
    def from_secret_file(cls, path: Path | str) -> CaldavTarget:
        """Three lines: collection URL, username, app password.

        Every refusal names the secret and what is wrong with it, and quotes
        none of its lines back.
        """
        path = Path(path)
        name = path.name
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise AwaitingOperator(
                f"Calendar push is waiting for its credential: create the secret "
                f"named {name} with three lines — the CalDAV collection URL, the "
                "username and an app password."
            ) from None
        except OSError:
            raise TargetInvalid(
                f"The secret named {name} is mounted but cannot be read by this "
                "service; check the secret's mode and the service's secrets list."
            ) from None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 3:
            raise TargetInvalid(
                f"The secret named {name} must hold exactly three lines — the collection "
                f"URL, the username and the app password — and holds {len(lines)}."
            )
        url, username, password = lines
        parts = urlsplit(url)
        if parts.scheme == "http":
            raise TargetInvalid(
                f"The collection URL in {name} uses http://. An app password sent "
                "over plain HTTP is readable by anything on the path; use the "
                "server's https:// address."
            )
        if parts.scheme != "https" or not parts.hostname:
            raise TargetInvalid(
                f"The first line of {name} is not an https:// collection URL."
            )
        if parts.username or parts.password:
            raise TargetInvalid(
                f"The collection URL in {name} carries credentials of its own; put "
                "the username and app password on lines two and three instead."
            )
        if parts.query or parts.fragment:
            raise TargetInvalid(
                f"The collection URL in {name} has a query or fragment; use the "
                "collection's plain address."
            )
        collection = url if url.endswith("/") else url + "/"
        return cls(collection, username, SecretStr(password), secret=name)


# ------------------------------------------------------------------ events


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """One event as G hands it over. What the scheduler must pass, and nothing else.

    ``vevent`` is one serialised ``BEGIN:VEVENT`` … ``END:VEVENT`` block — what
    The scheduler's ICS renderer already builds per task (``ics.event_for(...).to_ical()``).
    Its ``UID`` line must equal ``uid``; ``sequence`` and ``status`` are what
    G set on it, repeated so this module can compare without parsing iCalendar.
    """

    uid: str
    sequence: int
    status: str
    vevent: str

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.uid.strip():
            out.append("an event has an empty UID")
        text = self.vevent.strip()
        if not (text.startswith("BEGIN:VEVENT") and text.endswith("END:VEVENT")):
            out.append(f"event {self.uid!r} is not one VEVENT block")
        found = _UID.search(text)
        if not found or found.group(1) != self.uid:
            out.append(f"event {self.uid!r}: its VEVENT carries a different UID")
        if self.sequence < 0:
            out.append(f"event {self.uid!r}: SEQUENCE cannot be negative")
        return out

    def resource(self) -> bytes:
        """The whole resource: the VEVENT in a VCALENDAR, CRLF line endings."""
        body = "\r\n".join(self.vevent.strip().splitlines())
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            f"PRODID:{PRODID}\r\nCALSCALE:GREGORIAN\r\n"
            f"{body}\r\nEND:VCALENDAR\r\n"
        ).encode()


@dataclass(frozen=True, slots=True)
class Known:
    """What the server held for one UID after the last push. The scheduler may persist it."""

    sequence: int
    etag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "etag": self.etag}


# ------------------------------------------------------------------ result


#: Per-UID outcomes. ``cancelled`` is a created-or-updated write of an event
#: whose status is CANCELLED, named apart because it is the one a reader of
#: the Office most wants to see happened.
OUTCOMES = (
    "created",
    "updated",
    "cancelled",
    "unchanged",
    "refused",
    "failed",
    "skipped",
)


@dataclass(slots=True)
class PushResult:
    """What one push did. Safe to store, log and render: it holds no credential.

    ``error`` is one sentence an operator can act on, ready for
    ``CalendarFeed.push_error`` (contract 1.9.0). ``error_kind`` is for the scheduler's
    retry decision: ``auth``, ``not_found`` and ``tls`` will not fix
    themselves; ``server``, ``network`` and ``timeout`` may.
    """

    host: str
    pushed_at: datetime
    outcomes: dict[str, str] = field(default_factory=dict)
    state: dict[str, Known] = field(default_factory=dict)
    error: str | None = None
    error_kind: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not any(
            outcome in ("failed", "refused") for outcome in self.outcomes.values()
        )

    def count(self, outcome: str) -> int:
        return sum(1 for value in self.outcomes.values() if value == outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "host": self.host,
            "pushed_at": self.pushed_at.isoformat(),
            "counts": {name: self.count(name) for name in OUTCOMES},
            "outcomes": dict(self.outcomes),
            "state": {uid: known.to_dict() for uid, known in self.state.items()},
            "error": self.error,
            "error_kind": self.error_kind,
        }


class _Stop(Exception):
    """A failure that ends the push: the next request would fail the same way."""

    def __init__(self, kind: str, sentence: str) -> None:
        super().__init__(sentence)
        self.kind = kind
        self.sentence = sentence


# -------------------------------------------------------------------- push


async def push(
    target: CaldavTarget,
    events: Iterable[CalendarEvent],
    *,
    known: Mapping[str, Known] | None = None,
    settings: HubSettings | None = None,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> PushResult:
    """Make ``target``'s collection hold ``events``. Never raises for the server.

    ``known`` is :attr:`PushResult.state` from the last push, if the scheduler kept it.
    ``client`` is for tests (an ``httpx.MockTransport``); otherwise one is built
    with basic auth, a timeout, and **no redirect following** — a redirect is
    reported, never followed, so the app password is only ever presented to
    the host the operator wrote down.
    """
    events = list(events)
    state: dict[str, Known] = dict(known or {})
    result = PushResult(
        host=target.host, pushed_at=now or datetime.now(UTC), state=state
    )
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(
            auth=httpx.BasicAuth(target.username, target.password.get_secret_value()),
            timeout=(settings.http_timeout_s if settings else 15.0),
            follow_redirects=False,
            headers={
                "User-Agent": settings.user_agent if settings else DEFAULT_USER_AGENT
            },
        )
    try:
        for index, event in enumerate(events):
            problems = event.problems()
            if problems:
                result.outcomes[event.uid or f"#{index}"] = "refused"
                result.error = result.error or _clean(
                    "Calendar push refused an event it was given: "
                    + "; ".join(problems),
                    target,
                )
                result.error_kind = result.error_kind or "rejected"
                continue
            payload = event.resource()
            if credential_reason(payload.decode("utf-8", "replace"), None):
                result.outcomes[event.uid] = "refused"
                result.error = result.error or (
                    f"Calendar push refused event {event.uid!r}: its text looks like "
                    "it carries a credential, and nothing secret leaves in a payload."
                )
                result.error_kind = result.error_kind or "rejected"
                continue
            try:
                result.outcomes[event.uid] = await _put_one(
                    client, target, event, payload, state
                )
            except _Stop as stop:
                result.outcomes[event.uid] = "failed"
                for later in events[index + 1 :]:
                    result.outcomes.setdefault(later.uid, "skipped")
                result.error = _clean(stop.sentence, target)
                result.error_kind = stop.kind
                break
    finally:
        if owns:
            await client.aclose()
    log.info(
        "caldav push to %s: %s",
        result.host,
        ", ".join(f"{n} {result.count(n)}" for n in OUTCOMES if result.count(n))
        or "nothing",
    )
    if result.error:
        log.warning("caldav push to %s failed: %s", result.host, result.error)
    return result


async def _put_one(
    client: httpx.AsyncClient,
    target: CaldavTarget,
    event: CalendarEvent,
    payload: bytes,
    state: dict[str, Known],
) -> str:
    previous = state.get(event.uid)
    if previous is not None and previous.sequence >= event.sequence:
        return "unchanged"
    url = target.resource_url(event.uid)
    condition = (
        {"If-Match": previous.etag}
        if previous is not None and previous.etag
        else {"If-None-Match": "*"}
    )
    response = await _send(client, "PUT", url, target, payload, condition)
    if response.status_code == 412:
        current = await _send(client, "GET", url, target)
        if current.status_code == 404:
            # Gone between the two requests, or the stored ETag was for a
            # resource nobody holds any more: write it fresh.
            response = await _send(
                client, "PUT", url, target, payload, {"If-None-Match": "*"}
            )
        else:
            _raise_for(current, target)
            held = _sequence_of(current.text)
            etag = current.headers.get("ETag")
            if held is not None and held >= event.sequence:
                state[event.uid] = Known(held, etag)
                return "unchanged"
            if not etag:
                raise _Stop(
                    "conflict",
                    f"{target.host} changed event {event.uid!r} since the last push "
                    "and gave no ETag to write against; it was left as the server "
                    "has it.",
                )
            response = await _send(
                client, "PUT", url, target, payload, {"If-Match": etag}
            )
            if response.status_code == 412:
                raise _Stop(
                    "conflict",
                    f"{target.host} kept changing event {event.uid!r} while it was "
                    "being written; it will be retried on the next push.",
                )
    _raise_for(response, target)
    state[event.uid] = Known(event.sequence, response.headers.get("ETag"))
    if event.status.upper() == "CANCELLED":
        return "cancelled"
    return "created" if response.status_code == 201 else "updated"


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    target: CaldavTarget,
    content: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """One request. Transport failures become sentences; nothing of httpx's is kept."""
    sent = dict(headers or {})
    if content is not None:
        sent["Content-Type"] = "text/calendar; charset=utf-8"
    try:
        return await client.request(method, url, content=content, headers=sent)
    except httpx.TimeoutException:
        raise _Stop(
            "timeout",
            f"{target.host} did not answer in time; the push will be retried.",
        ) from None
    except httpx.ConnectError as exc:
        text = str(exc).lower()
        if "ssl" in text or "certificate" in text or "tls" in text:
            raise _Stop(
                "tls",
                f"The TLS handshake with {target.host} failed: its certificate was "
                "not accepted. Check the collection URL's host, or the server's "
                "certificate.",
            ) from None
        raise _Stop(
            "network",
            f"Could not connect to {target.host}. Check the host in the collection "
            "URL and that this server can reach it.",
        ) from None
    except httpx.HTTPError:
        raise _Stop(
            "network",
            f"The connection to {target.host} failed part-way; the push will be "
            "retried.",
        ) from None


def _raise_for(response: httpx.Response, target: CaldavTarget) -> None:
    """A status as a sentence that says what to change. Never the body."""
    status = response.status_code
    if status < 300:
        return
    host, secret = target.host, target.secret
    if status in (401, 403):
        raise _Stop(
            "auth",
            f"{host} refused the username and app password (HTTP {status}). Create a "
            f"new app password and replace the secret named {secret}.",
        )
    if status in (404, 409, 410):
        raise _Stop(
            "not_found",
            f"{host} has no calendar at the collection URL in the secret named {secret} (HTTP "
            f"{status}). Copy the calendar's CalDAV address again.",
        )
    if 300 <= status < 400:
        raise _Stop(
            "not_found",
            f"{host} redirected the request (HTTP {status}). Redirects are not "
            "followed while signed in, so the sign-in only ever goes to the host "
            f"the operator wrote down. Put the final address in the secret named "
            f"{secret}.",
        )
    if status in (413, 415, 400, 422):
        raise _Stop(
            "rejected",
            f"{host} refused an event as malformed (HTTP {status}). This is a fault "
            "in the Ministry, not in your setup; report it.",
        )
    if status == 429 or status >= 500:
        raise _Stop(
            "server",
            f"{host} is not accepting writes right now (HTTP {status}); the push "
            "will be retried.",
        )
    raise _Stop("server", f"{host} answered HTTP {status} to a calendar write.")


def _sequence_of(text: str) -> int | None:
    found = _SEQUENCE.search(text.replace("\r\n", "\n"))
    return int(found.group(1)) if found else None


def _clean(sentence: str, target: CaldavTarget) -> str:
    """Redact the three lines, then refuse anything still credential-shaped."""
    cleaned = redact(sentence, target.secrets()) or sentence
    if target.collection_url in cleaned:
        cleaned = cleaned.replace(target.collection_url, target.host)
    if credential_reason(cleaned, None):
        return (
            f"Calendar push to {target.host} failed, and the reason looked like it "
            "carried a credential, so it is not shown."
        )
    return cleaned


def events_from(rows: Sequence[Mapping[str, Any]]) -> list[CalendarEvent]:
    """Plain mappings (``uid``, ``sequence``, ``status``, ``vevent``) as events.

    For a caller that would rather hand over dicts than import this module's
    dataclass — the scheduler's choice.
    """
    return [
        CalendarEvent(
            uid=str(row["uid"]),
            sequence=int(row.get("sequence") or 0),
            status=str(row.get("status") or "CONFIRMED"),
            vevent=str(row["vevent"]),
        )
        for row in rows
    ]
