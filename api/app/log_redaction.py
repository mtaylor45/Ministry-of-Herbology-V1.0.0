"""Keep calendar-feed tokens out of the access log.

belongs to whatever runs the app, and neither can fix this alone.

``GET /api/v1/calendar/{token}.ics`` carries the one credential this
application issues, in the URL path. It is there because Google's and Apple's
calendar fetchers send no session and no headers — there is nowhere else to put
it — and the design promises the operator that the token "is never logged".

The scheduler's package keeps that promise: it imports no logger and calls no
``print``, and has a test saying so. The promise was still false, because
uvicorn's access logger writes the request path for every request it serves,
and on a self-hosted box the container log usually ends up in a backup.

This filter rewrites the path in ``uvicorn.access`` records before they are
formatted. The status, timing and client address survive, so the log still
answers "is the feed being fetched, and does it work" — which is what an
operator actually reads it for — while the credential does not reach disk.

Nginx needs the same treatment and gets it separately in
``infra/stack/nginx/nginx.conf``; this half also covers running the API
without a front end at all.
"""

from __future__ import annotations

import logging
import re

#: The token sits between the route prefix and the ``.ics`` suffix. Matching on
#: the route rather than on "things that look like secrets" means a token of an
#: unexpected shape is still caught — the path is what makes it a credential.
_CALENDAR_TOKEN = re.compile(r"(/api/v1/calendar/)[^/?\s]+?(\.ics)")

REDACTED = r"\1[redacted]\2"


def redact(path: str) -> str:
    """Replace a calendar token in ``path`` with a marker."""
    return _CALENDAR_TOKEN.sub(REDACTED, path)


class CalendarTokenFilter(logging.Filter):
    """Strip calendar tokens from ``uvicorn.access`` records.

    uvicorn formats its access line from ``record.args`` rather than from the
    message, so the path is rewritten there. Anything shaped differently is
    left alone: a filter that raises takes the whole log line with it, and a
    missing access line is a worse outcome than a tidy one.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            redacted = redact(args[2])
            if redacted != args[2]:
                record.args = args[:2] + (redacted,) + args[3:]
        return True


def install() -> None:
    """Attach the filter to uvicorn's access logger.

    Safe to call when uvicorn is not the server, and safe to call twice: the
    logger exists either way, and a duplicate filter would only redact an
    already-redacted path.
    """
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, CalendarTokenFilter) for f in access.filters):
        access.addFilter(CalendarTokenFilter())
