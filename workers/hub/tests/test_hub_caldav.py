"""CalDAV push against a fake server. Owner: The hub.

The fake is an ``httpx.MockTransport`` holding one resource per path with an
ETag, honouring ``If-None-Match: *`` and ``If-Match`` the way RFC 4791 servers
do. It records every request, so "never DELETE" and "a repeat costs no
request" are assertions on traffic, not on the adapter's own report.

The credential in these tests is real-shaped on purpose. The leak tests put
the actual username and app password into the fake server's error bodies and
into a transport exception, and assert that neither reaches the result, an
exception message or a log record.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from workers.hub.calendar import (
    AwaitingOperator,
    CaldavTarget,
    CalendarEvent,
    Known,
    TargetInvalid,
    push,
    secret_name,
)
from workers.hub.settings import HubSettings

COLLECTION = "https://caldav.example.net/dav/calendars/user/alice@example.net/plants/"
USERNAME = "alice@example.net"
PASSWORD = "app-pw-q7Lm2xV9sK4t"
UID = "01890080-0000-7000-8000-000000000001@herbology"
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


def vevent(uid: str = UID, sequence: int = 0, status: str = "CONFIRMED") -> str:
    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"SEQUENCE:{sequence}\r\n"
        "DTSTAMP:20261022T060000Z\r\n"
        "DTSTART;VALUE=DATE:20261022\r\n"
        "DTEND;VALUE=DATE:20261023\r\n"
        "SUMMARY:Tend the Monstera — water 500 ml\r\n"
        f"STATUS:{status}\r\n"
        "END:VEVENT\r\n"
    )


def event(
    sequence: int = 0, status: str = "CONFIRMED", uid: str = UID
) -> CalendarEvent:
    return CalendarEvent(uid, sequence, status, vevent(uid, sequence, status))


def target() -> CaldavTarget:
    return CaldavTarget(
        COLLECTION, USERNAME, SecretStr(PASSWORD), secret="moh_caldav_f1"
    )


class FakeCaldav:
    """A collection: path → (body, etag). Conditional PUT and GET, nothing else."""

    def __init__(self) -> None:
        self.resources: dict[str, tuple[str, str]] = {}
        self.requests: list[httpx.Request] = []
        self.version = 0
        self.fail: Callable[[httpx.Request], httpx.Response | None] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            forced = self.fail(request)
            if forced is not None:
                return forced
        path = request.url.path
        held = self.resources.get(path)
        if request.method == "GET":
            if held is None:
                return httpx.Response(404)
            return httpx.Response(200, text=held[0], headers={"ETag": held[1]})
        if request.method == "PUT":
            if request.headers.get("If-None-Match") == "*" and held is not None:
                return httpx.Response(412)
            match = request.headers.get("If-Match")
            if match is not None and (held is None or held[1] != match):
                return httpx.Response(412)
            self.version += 1
            etag = f'"v{self.version}"'
            self.resources[path] = (request.content.decode(), etag)
            return httpx.Response(204 if held else 201, headers={"ETag": etag})
        return httpx.Response(405)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler),
            auth=httpx.BasicAuth(USERNAME, PASSWORD),
        )

    def methods(self) -> list[str]:
        return [r.method for r in self.requests]

    def body(self, uid: str = UID) -> str:
        path = httpx.URL(target().resource_url(uid)).path
        return self.resources[path][0]


@pytest.fixture
def server() -> FakeCaldav:
    return FakeCaldav()


def run_push(
    run: Any, server: FakeCaldav, events: list[CalendarEvent], **kw: Any
) -> Any:
    async def go() -> Any:
        async with server.client() as client:
            return await push(target(), events, client=client, now=NOW, **kw)

    return run(go())


# ------------------------------------------------------------------ writes


def test_a_new_event_is_created_once_with_if_none_match(run, server):
    result = run_push(run, server, [event()])
    assert result.ok and result.outcomes == {UID: "created"}
    (put,) = server.requests
    assert put.method == "PUT" and put.headers["If-None-Match"] == "*"
    assert put.url.path.endswith(".ics") and "%40herbology" in str(put.url)
    assert put.headers["Content-Type"].startswith("text/calendar")
    body = server.body()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert f"UID:{UID}" in body
    assert result.state[UID] == Known(0, '"v1"')


def test_a_bumped_sequence_updates_against_the_stored_etag(run, server):
    first = run_push(run, server, [event(0)])
    second = run_push(run, server, [event(1)], known=first.state)
    assert second.outcomes == {UID: "updated"}
    put = server.requests[-1]
    assert put.headers["If-Match"] == '"v1"' and "If-None-Match" not in put.headers
    assert "SEQUENCE:1" in server.body()
    assert second.state[UID] == Known(1, '"v2"')


def test_a_repeat_with_state_costs_no_request(run, server):
    first = run_push(run, server, [event(3)])
    before = len(server.requests)
    again = run_push(run, server, [event(3)], known=first.state)
    assert again.outcomes == {UID: "unchanged"} and again.ok
    assert len(server.requests) == before


def test_a_repeat_without_state_is_detected_on_the_server(run, server):
    """Two replicas, or a caller that lost its state: one 412 and one GET,
    then the server's SEQUENCE says there is nothing to do."""
    run_push(run, server, [event(2)])
    again = run_push(run, server, [event(2)])
    assert again.outcomes == {UID: "unchanged"} and again.ok
    assert server.methods()[-2:] == ["PUT", "GET"]
    assert again.state[UID].sequence == 2 and again.state[UID].etag == '"v1"'


def test_an_older_sequence_never_overwrites_a_newer_one(run, server):
    run_push(run, server, [event(5)])
    stale = run_push(run, server, [event(4)])
    assert stale.outcomes == {UID: "unchanged"}
    assert "SEQUENCE:5" in server.body()


def test_cancellation_is_a_put_and_never_a_delete(run, server):
    first = run_push(run, server, [event(0)])
    cancelled = run_push(run, server, [event(1, "CANCELLED")], known=first.state)
    assert cancelled.outcomes == {UID: "cancelled"}
    assert "STATUS:CANCELLED" in server.body()
    assert "DELETE" not in server.methods()


def test_an_etag_conflict_reads_the_server_and_writes_once_more(run, server):
    """Somebody edited the event on a phone: the stored ETag is stale. The
    server's copy is still sequence 0, so ours (1) is written against its ETag."""
    first = run_push(run, server, [event(0)])
    path = httpx.URL(target().resource_url(UID)).path
    server.resources[path] = (server.resources[path][0], '"edited-on-phone"')
    result = run_push(run, server, [event(1)], known=first.state)
    assert result.outcomes == {UID: "updated"}
    assert server.methods()[-3:] == ["PUT", "GET", "PUT"]
    assert server.requests[-1].headers["If-Match"] == '"edited-on-phone"'


def test_a_stored_etag_for_a_vanished_resource_is_written_fresh(run, server):
    stale = {UID: Known(0, '"gone"')}
    result = run_push(run, server, [event(1)], known=stale)
    assert result.outcomes == {UID: "created"}
    assert server.methods() == ["PUT", "GET", "PUT"]


def test_a_g_rendered_vevent_round_trips(run, server):
    """The shape the scheduler will hand over: ``icalendar``'s ``Event.to_ical()``, built
    the way ``api/tending/ics.py`` builds one (not imported: scheduler → hub only)."""
    from icalendar import Event

    ev = Event()
    ev.add("uid", UID)
    ev.add("sequence", 2)
    ev.add("dtstamp", NOW)
    ev.add("dtstart", date(2026, 10, 22))
    ev.add("summary", "Tend the Monstera — water 500 ml")
    ev.add("status", "CONFIRMED")
    text = ev.to_ical().decode()
    result = run_push(run, server, [CalendarEvent(UID, 2, "CONFIRMED", text)])
    assert result.outcomes == {UID: "created"}
    assert "SEQUENCE:2" in server.body()


def test_an_event_whose_vevent_names_another_uid_is_refused(run, server):
    bad = CalendarEvent(UID, 0, "CONFIRMED", vevent("someone-else"))
    result = run_push(run, server, [bad, event(0, uid="second@herbology")])
    assert result.outcomes[UID] == "refused"
    assert result.outcomes["second@herbology"] == "created"
    assert not result.ok and result.error_kind == "rejected"


def test_an_event_carrying_a_credential_is_refused_not_sent(run, server):
    leaky = vevent().replace(
        "STATUS:CONFIRMED",
        "URL:https://moh.example/api/v1/tending/feeds/abcdefghijklmnopqrstu",
    )
    result = run_push(run, server, [CalendarEvent(UID, 0, "CONFIRMED", leaky)])
    assert result.outcomes == {UID: "refused"}
    assert server.requests == []


# ------------------------------------------------------------------ errors


LEAKY_BODY = (
    f"<error>user {USERNAME} with password {PASSWORD} denied for "
    f"https://{USERNAME}:{PASSWORD}@caldav.example.net{httpx.URL(COLLECTION).path}</error>"
)


def assert_no_credential(*texts: str) -> None:
    for text in texts:
        assert PASSWORD not in text
        assert USERNAME not in text
        assert "/dav/calendars/user/" not in text  # the path carries the username


@pytest.mark.parametrize(
    ("status", "kind", "phrase"),
    [
        (401, "auth", "replace the secret named moh_caldav_f1"),
        (403, "auth", "refused the username and app password"),
        (404, "not_found", "no calendar at the collection URL"),
        (412, None, None),  # handled, not an error: see the conflict tests
        (500, "server", "will be retried"),
        (503, "server", "will be retried"),
        (301, "not_found", "Redirects are not followed"),
    ],
)
def test_every_status_is_a_sentence_without_the_credential(
    run, server, caplog, status, kind, phrase
):
    if status == 412:
        return
    server.fail = lambda request: httpx.Response(
        status, text=LEAKY_BODY, headers={"Location": f"https://{USERNAME}@x/"}
    )
    with caplog.at_level(logging.DEBUG, logger="workers.hub.calendar"):
        result = run_push(run, server, [event(0), event(0, uid="second@herbology")])
    assert not result.ok and result.error_kind == kind
    assert phrase in result.error
    assert "caldav.example.net" in result.error
    assert "[redacted]" not in result.error  # the secret's name is not a secret
    assert result.outcomes == {UID: "failed", "second@herbology": "skipped"}
    assert len(server.requests) == 1  # a refused password is not presented twice
    assert_no_credential(result.error, str(result.to_dict()), caplog.text)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx.ConnectTimeout, "timeout"),
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "network"),
    ],
)
def test_transport_failures_are_sentences_without_the_credential(
    run, server, caplog, exc, kind
):
    def raise_it(request: httpx.Request) -> httpx.Response:
        raise exc(
            f"failed for https://{USERNAME}:{PASSWORD}@caldav.example.net/",
            request=request,
        )

    server.fail = raise_it
    with caplog.at_level(logging.DEBUG, logger="workers.hub.calendar"):
        result = run_push(run, server, [event()])
    assert result.error_kind == kind
    assert_no_credential(result.error, str(result.to_dict()), caplog.text)


def test_a_tls_failure_says_so(run, server, caplog):
    def raise_it(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"[SSL: CERTIFICATE_VERIFY_FAILED] for {USERNAME}:{PASSWORD}",
            request=request,
        )

    server.fail = raise_it
    with caplog.at_level(logging.DEBUG, logger="workers.hub.calendar"):
        result = run_push(run, server, [event()])
    assert result.error_kind == "tls" and "certificate" in result.error
    assert_no_credential(result.error, caplog.text)


def test_the_request_carries_basic_auth_and_nothing_else_does(run, server):
    run_push(run, server, [event()])
    (put,) = server.requests
    assert put.headers["Authorization"].startswith("Basic ")
    assert PASSWORD.encode() not in put.content and USERNAME.encode() not in put.content


def test_a_target_never_prints_its_credential():
    shown = repr(target()) + str(target())
    assert PASSWORD not in shown and USERNAME not in shown


# -------------------------------------------------------- the secret file


def write(tmp_path: Path, *lines: str, name: str = "moh_caldav_f1") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


def test_the_secret_file_is_three_lines(tmp_path):
    loaded = CaldavTarget.from_secret_file(
        write(tmp_path, COLLECTION.rstrip("/"), USERNAME, PASSWORD)
    )
    assert loaded.collection_url == COLLECTION
    assert loaded.username == USERNAME
    assert loaded.password.get_secret_value() == PASSWORD
    assert loaded.secret == "moh_caldav_f1" and loaded.host == "caldav.example.net"


def test_a_missing_file_is_awaiting_the_operator_and_names_the_secret(tmp_path):
    settings = HubSettings(secrets_dir=tmp_path)
    with pytest.raises(AwaitingOperator, match="moh_caldav_feed-9"):
        CaldavTarget.for_feed("feed-9", settings)
    assert secret_name("feed-9") == "moh_caldav_feed-9"


@pytest.mark.parametrize(
    ("lines", "fragment"),
    [
        (("http://caldav.example.net/plants/", USERNAME, PASSWORD), "plain HTTP"),
        (
            (
                f"https://{USERNAME}:{PASSWORD}@caldav.example.net/p/",
                USERNAME,
                PASSWORD,
            ),
            "credentials of its own",
        ),
        ((COLLECTION, USERNAME), "exactly three lines"),
        (("caldav.example.net/plants", USERNAME, PASSWORD), "not an https://"),
        ((COLLECTION + "?x=1", USERNAME, PASSWORD), "query or fragment"),
    ],
)
def test_a_bad_secret_file_is_refused_without_quoting_it(tmp_path, lines, fragment):
    with pytest.raises(TargetInvalid) as caught:
        CaldavTarget.from_secret_file(write(tmp_path, *lines))
    assert fragment in str(caught.value)
    assert PASSWORD not in str(caught.value) and USERNAME not in str(caught.value)


def test_the_secrets_directory_defaults_to_the_docker_convention():
    assert HubSettings().secrets_dir == Path("/run/secrets")
