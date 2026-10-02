"""Shared setup for the weather worker's tests. Owner: The weather engine.

Every test here runs offline. The recordings in ``mocks/recorded/`` and the
frozen fixtures are the only inputs, which is what makes a parser bug or a
confidence rule reproducible a year from now.

Run them the way CI does — the bare console script, not ``python -m pytest``::

    .venv/bin/pytest workers/weather -q

The repository-root ``conftest.py`` puts both source roots on ``sys.path``;
this file deliberately does not do it again, for the reason stated there.
"""

from __future__ import annotations

import asyncio
import json
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


@pytest.fixture(scope="session")
def recorded_dir() -> Path:
    return REPO_ROOT / "workers" / "weather" / "mocks" / "recorded"


@pytest.fixture(scope="session")
def payload(recorded_dir: Path):
    def _load(relative: str) -> Any:
        return json.loads((recorded_dir / relative).read_text())

    return _load


@pytest.fixture(scope="session")
def fixture(repo_root: Path):
    def _load(relative: str) -> Any:
        return json.loads((repo_root / "fixtures" / relative).read_text())

    return _load


@pytest.fixture
def settings():
    from workers.weather.settings import WeatherSettings

    return WeatherSettings(mock_mode=True, fixtures_dir=REPO_ROOT / "fixtures")


@pytest.fixture
def fetcher(settings):
    from workers.weather.mocks.fetcher import RecordedFetcher

    return RecordedFetcher(settings)


@pytest.fixture
def site(settings):
    from workers.weather import world

    return world.site(settings)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def day() -> date:
    return date(2026, 6, 1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test ever reaches for the network.

    This patches the *transport* rather than ``AsyncClient.send``, which is a
    deliberate difference from the botany suite's version. Patching the client
    also blocks ``httpx.MockTransport``, and the HTTP fetcher's retry and
    error-body handling can only be tested against a transport that answers.
    Blocking the real transport and the socket layer underneath it is both
    stricter and more useful: a test can serve a canned response, and nothing
    can open a connection.
    """
    import socket

    import httpx

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a weather test tried to open a connection; tests replay "
            "mocks/recorded/ and the frozen fixtures instead"
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
