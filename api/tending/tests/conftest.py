"""Test setup for the scheduler.

These live under ``api/tending/`` because the ownership rule puts the repository's top-level
``tests/`` in the test suite's hands. Run them with::

    .venv/bin/pytest api/tending -q

Everything here runs without a database and without a network. The autouse
``no_network`` fixture makes that a fact rather than an intention: any test that
opens a socket fails, so a scheduling decision can never quietly come to depend
on reaching Open-Meteo.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Both, and in this order. Running ``pytest api/tending`` on its own makes
# ``api/pyproject.toml`` the config file and therefore ``api/`` the rootdir, so
# the repository-root ``conftest.py`` that normally puts ``workers`` on the path
# is never collected — and ``app.main`` imports the botany worker's router from
# there. CI collects four trees at once and does not hit it; a contributor
# running this package alone would, which is the worst kind of difference.
for _path in (REPO_ROOT, REPO_ROOT / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to open a connection.

    Except the live-database module, which exists to open one to the Postgres
    ``MOH_TEST_DATABASE_URL`` names and is skipped when nothing is named. Until
    an earlier release this fixture refused that connection too, so those tests could not pass
    anywhere they were not skipped.
    """
    if request.node.path.name == "test_tending_database.py":
        return

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "This suite is network-free: a test tried to open a socket. "
            "Use a recorded payload or a fixture instead."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def client():
    """A mock-mode client with the in-memory schedule reloaded from fixtures.

    The store is process-wide so a completion outlives its request; resetting it
    per test keeps one test's completions out of the next test's rounds.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from tending.fixture_repository import reset_fixture_repository

    reset_fixture_repository()
    with TestClient(app) as test_client:
        yield test_client
    reset_fixture_repository()
