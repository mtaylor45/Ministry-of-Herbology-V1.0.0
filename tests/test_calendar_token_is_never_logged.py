"""The one credential this application issues must not reach a log.

the front end is the deployment's, so the guard belongs to none of them alone.

the design promises the operator that a calendar-feed token "is never logged,
never reused across feeds, and revoking one must not disturb the others". The
first clause was false in the deployed stack until 2026-09-24, in two places at
once:

* uvicorn writes the request path for every request it serves, and
  ``/api/v1/calendar/{token}.ics`` is the path;
* Nginx's ``access_log off`` guard was written against ``/api/v1/feeds/``,
  which no route has ever served — the real paths are
  ``/api/v1/calendar/{token}.ics`` and ``/api/v1/tending/feeds`` — so every
  fetch fell through to ``location /api/`` and was logged in ``$request``.

The scheduler found the first. The second turned up on the way to fixing it, and
is the more instructive of the two: the intent was right, the comment claimed
the risk was handled, and the prefix matched nothing.
"""

from __future__ import annotations

import logging

import pytest
from app.log_redaction import CalendarTokenFilter, redact

TOKEN = "c0ffee7ab1e5deadbeef0123456789ab"
FEED_PATH = f"/api/v1/calendar/{TOKEN}.ics"


def test_a_token_is_redacted_out_of_a_request_path():
    assert TOKEN not in redact(FEED_PATH)
    assert redact(FEED_PATH) == "/api/v1/calendar/[redacted].ics"


def test_a_query_string_does_not_carry_the_token_past_the_filter():
    assert TOKEN not in redact(f"{FEED_PATH}?after=2026-09-01")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/specimens",
        "/api/v1/tending/rounds",
        "/api/v1/almanac/forecast?window=10d",
    ],
)
def test_an_ordinary_path_is_left_exactly_as_it_was(path):
    assert redact(path) == path


def test_the_filter_rewrites_the_uvicorn_access_record():
    """uvicorn formats its line from ``record.args``, not from the message."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("10.0.0.7:54321", "GET", FEED_PATH, "1.1", 200),
        exc_info=None,
    )
    assert CalendarTokenFilter().filter(record) is True
    assert TOKEN not in (record.getMessage())
    assert record.args[4] == 200, "status must survive — the log still has to be useful"


def test_a_record_of_an_unexpected_shape_is_passed_through_not_dropped():
    """A filter that raises takes the whole log line with it."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="something else entirely",
        args=None,
        exc_info=None,
    )
    assert CalendarTokenFilter().filter(record) is True


def test_nginx_guards_the_paths_that_actually_carry_the_token(repo_root):
    """The regression that matters: a guard aimed at a path nobody serves.

    Read from the shipped config rather than asserted in prose, so moving the
    route without moving the guard fails here.
    """
    conf = (repo_root / "infra" / "stack" / "nginx" / "nginx.conf").read_text()

    assert "location /api/v1/calendar/ {" in conf, (
        "the token path is unguarded; every fetch writes the credential into "
        "the access log's $request"
    )
    assert (
        "location /api/v1/tending/feeds {" in conf
    ), "the feed list returns webcal URLs with tokens inside them"
    assert (
        "location /api/v1/feeds/" not in conf
    ), "that prefix matches no route and reads as protection that is not there"
