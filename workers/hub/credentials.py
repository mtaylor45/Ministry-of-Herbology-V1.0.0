"""One credential check, for every payload this worker sends — the hub.

an earlier release put this in :mod:`workers.hub.mqtt`, because MQTT was the only thing F
published. an earlier release adds notifications, which leave the house through Home Assistant
rather than through a broker and are read by a person rather than by a
dashboard — and the rule is the same rule::

    Nothing secret goes in a payload.

It is not theoretical. The scheduler escalated that the calendar token was
being written to two access logs, and it was. A notification body is a more
attractive place for the same mistake: a task's ``detail``, an integration's
``last_error`` and a feed URL are all *text somebody wrote*, and text somebody
wrote is where a credential ends up.

So the scanning lives here, once, and both senders call it. Two halves, because
credentials arrive in two shapes:

* **labelled** — a JSON key called ``token``, ``api_key``, ``password``. Caught
  by name, wherever it is nested.
* **unlabelled** — a JWT, a ``https://user:pass@host`` URL, a tokenised feed
  path pasted into a note. Caught by pattern, in the raw text.

:class:`SecretInPayload` is raised rather than logged. A broker keeps a retained
message until something replaces it and a phone keeps a notification until
somebody swipes it: a credential sent once is a credential out there, and a
warning in a worker log is not read by anyone on the day it is written.

This module is deliberately blunt. A false positive costs one refused message
and a traceback naming the field; a false negative puts a long-lived access
token on somebody's lock screen.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

#: JSON keys that must never appear in anything this worker publishes, at any
#: depth. Names rather than values: a token is usually *labelled*.
FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "password",
        "secret",
        "authorization",
        "feed_token",
        "ics_token",
        "webcal_url",
    }
)

#: The unlabelled shapes. The last one is the scheduler's ICS subscription URL,
#: which carries the one credential this application issues in its path — the
#: single most likely thing to be helpfully pasted into a notification.
CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a JSON web token, which is what a Home Assistant long-lived token is",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}"),
    ),
    (
        "a labelled bearer token, api key or password",
        re.compile(r"(?i)\b(?:bearer|token|api[_-]?key)\b\s*[:=]\s*\S{8,}"),
    ),
    (
        "credentials embedded in a URL",
        re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),
    ),
    (
        "a tokenised calendar feed URL",
        re.compile(r"(?i)/(?:feeds?|calendar)/[A-Za-z0-9_\-]{16,}"),
    ),
)


#: "the caller did not decode the body", kept apart from ``None``, which is a
#: body that decoded to JSON null.
_MISSING = object()


class SecretInPayload(ValueError):
    """A payload carried something credential-shaped. Refused, not sent.

    Raised, never caught-and-logged. See the module docstring: the thing being
    prevented is a credential that outlives the mistake.
    """


def keys_of(body: Any) -> list[str]:
    """Every key in a decoded JSON body, at any depth."""
    if isinstance(body, Mapping):
        keys = [str(key) for key in body]
        for value in body.values():
            keys.extend(keys_of(value))
        return keys
    if isinstance(body, list):
        found: list[str] = []
        for item in body:
            found.extend(keys_of(item))
        return found
    return []


def credential_reason(text: str, body: Any = _MISSING) -> str | None:
    """Why ``text`` looks like it carries a credential, or ``None``.

    ``body`` is the already-decoded payload when the caller has one; otherwise
    ``text`` is parsed as JSON and a parse failure simply means "scan the text
    only", which is the right answer for a plain-text notification body.
    """
    if body is _MISSING:
        try:
            body = json.loads(text)
        except ValueError:
            body = None
    for key in keys_of(body):
        if key.lower() in FORBIDDEN_KEYS:
            return f"a {key!r} field"
    for description, pattern in CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return description
    return None


def assert_clean(label: str, text: str, body: Any = _MISSING) -> str:
    """``text`` back, or :class:`SecretInPayload` naming what was found.

    ``label`` is what the message *is* — an MQTT topic, a notification's
    recipient — so the traceback says which payload was refused without
    quoting the payload itself back into another log.
    """
    reason = credential_reason(text, body)
    if reason is not None:
        raise SecretInPayload(
            f"{label}: payload carries {reason}. Nothing secret leaves this "
            "worker in a payload (contracts/events/mqtt.md, and the same rule "
            "for notifications)."
        )
    return text
