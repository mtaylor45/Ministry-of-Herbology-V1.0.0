"""Shared setup for the hub worker's tests. Owner: The hub.

Every test here runs offline. The synthesised payloads and the frozen fixtures
are the only inputs, which is what makes a parser bug or a refusal rule
reproducible a year from now.

Run them the way CI does — the bare console script, not ``python -m pytest``::

    .venv/bin/pytest workers/hub -q

The repository-root ``conftest.py`` puts both source roots on ``sys.path``;
this file deliberately does not do it again, for the reason stated there.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

T = TypeVar("T")


@pytest.fixture
def run():
    """Drive a coroutine from a synchronous test.

    Deliberately not ``pytest-asyncio``: the repository has no root pytest
    config, so ``asyncio_mode`` is whatever the caller's rootdir happens to
    say, and a suite should not depend on where it was invoked from.
    """

    def _run(coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run(coro)

    return _run


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def now() -> datetime:
    """Frozen. Every entity's freshness is a difference against this."""
    return datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def settings():
    from workers.hub.settings import HubSettings

    return HubSettings(mock_mode=True, fixtures_dir=REPO_ROOT / "fixtures")


@pytest.fixture
def fetcher(settings, now):
    from workers.hub.mocks.fetcher import RecordedFetcher

    return RecordedFetcher(settings, now=lambda: now)


@pytest.fixture
def source(fetcher, settings):
    from workers.hub.sources.home_assistant import HomeAssistantSource

    return HomeAssistantSource(fetcher, settings)


@pytest.fixture
def sensor_sources(settings):
    from workers.hub import world

    return world.sensor_sources(settings)


@pytest.fixture
def connection():
    """A recording stand-in for asyncpg, so the writes are assertable.

    A fake rather than a database: every statement in
    ``workers/hub/store.py`` is built by a pure function, so what is worth
    asserting is *which* statements a job issues and in what order — and that
    is exactly what a real Postgres would make harder to see.
    """

    class RecordingConnection:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple[Any, ...]]] = []
            self.rows: dict[str, list[Any]] = {}

        async def execute(self, sql: str, *args: Any) -> str:
            self.executed.append((sql, args))
            return "OK"

        async def fetch(self, sql: str, *args: Any) -> list[Any]:
            self.executed.append((sql, args))
            for prefix, rows in self.rows.items():
                if prefix in sql:
                    return rows
            return []

        def statements(self) -> list[str]:
            return [sql for sql, _ in self.executed]

        def matching(self, fragment: str) -> list[tuple[str, tuple[Any, ...]]]:
            return [item for item in self.executed if fragment in item[0]]

    return RecordingConnection()


@pytest.fixture
def recipient():
    """One member who has set up the companion app and wants everything.

    Built from a ``member`` row rather than constructed directly, so the
    ``notify_prefs`` convention this parts of the project reads is exercised by every
    test that uses it rather than only by the two that parse it.
    """
    from workers.hub.notify.model import Recipient

    return Recipient.from_member_row(
        {
            "id": "01890050-0000-7000-8000-000000000001",
            "name": "Keeper",
            "notify_prefs": {
                "home_assistant": {
                    "service": "notify.mobile_app_test_phone",
                    "rounds_hour": 7,
                    "quiet_hours": [22, 7],
                }
            },
        }
    )


@pytest.fixture
def channel():
    from workers.hub.notify.channels import MemoryChannel

    return MemoryChannel()


@pytest.fixture
def ministry(settings):
    """The mock Ministry: today's rounds and tonight's frost, from fixtures."""
    from workers.hub.mocks.ministry import MockMinistryReader

    return MockMinistryReader(settings, today=date(2026, 10, 23))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test ever reaches for the network.

    The same guard the weather engine uses, and for the same reason: patching the
    *transport* rather than ``AsyncClient.send`` leaves ``httpx.MockTransport``
    usable, so the fetcher's retry and error-body handling can be tested
    against a transport that answers while nothing can open a connection.

    It matters more here than it does for weather. Every request this worker
    would make carries a long-lived Home Assistant access token, and a test
    that accidentally dialled a real address would send it there.
    """
    import socket

    import httpx

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a hub test tried to open a connection; tests replay the "
            "synthesised payloads and the frozen fixtures instead"
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
