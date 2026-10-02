"""A fake CalDAV collection for the scheduler's push tests, in the hub's style.

An ``httpx.MockTransport`` handler: one resource per path with an ETag,
``If-None-Match: *`` and ``If-Match`` honoured, every request recorded with
the moment it arrived. Shared by the mock-stack and live-database suites.
"""

from __future__ import annotations

import re
import time

import httpx

USERNAME = "alice@example.net"
PASSWORD = "app-pw-q7Lm2xV9sK4t"

_SEQUENCE = re.compile(r"^SEQUENCE:(\d+)", re.MULTILINE)
_UID = re.compile(r"^UID:(.+?)\r?$", re.MULTILINE)


class FakeCaldav:
    """A collection: path → (body, etag). Conditional PUT and GET, nothing else."""

    def __init__(self) -> None:
        self.resources: dict[str, tuple[str, str]] = {}
        self.requests: list[tuple[float, httpx.Request]] = []
        self.version = 0
        self.status: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((time.perf_counter(), request))
        if self.status is not None:
            # A refusal that quotes the credential back, as a careless server
            # might: none of it may reach push_error.
            return httpx.Response(
                self.status, text=f"bad login for {USERNAME} / {PASSWORD}"
            )
        path = request.url.path
        held = self.resources.get(path)
        if request.method == "GET":
            if held is None:
                return httpx.Response(404)
            return httpx.Response(200, text=held[0], headers={"ETag": held[1]})
        if request.method != "PUT":
            return httpx.Response(405)
        if request.headers.get("If-None-Match") == "*" and held is not None:
            return httpx.Response(412)
        match = request.headers.get("If-Match")
        if match is not None and (held is None or held[1] != match):
            return httpx.Response(412)
        self.version += 1
        etag = f'"v{self.version}"'
        self.resources[path] = (request.content.decode(), etag)
        return httpx.Response(201 if held is None else 204, headers={"ETag": etag})

    def puts(self, since: int = 0) -> list[tuple[float, httpx.Request]]:
        return [(at, r) for at, r in self.requests[since:] if r.method == "PUT"]

    def held(self) -> dict[str, tuple[int, str]]:
        """UID → (SEQUENCE, STATUS) of everything the collection holds."""
        out: dict[str, tuple[int, str]] = {}
        for body, _etag in self.resources.values():
            uid = _UID.search(body)
            sequence = _SEQUENCE.search(body)
            status = re.search(r"^STATUS:(\w+)", body, re.MULTILINE)
            assert uid and sequence and status
            out[uid.group(1)] = (int(sequence.group(1)), status.group(1))
        return out
