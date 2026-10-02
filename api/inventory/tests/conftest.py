"""Test setup for the inventory API.

These live under ``api/inventory/`` because the ownership rule puts ``tests/`` in
The test suite's hands. Run them with::

    .venv/bin/python -m pytest api/inventory -q

Everything here runs without a database. The live Postgres path is exercised by
``test_database_repository.py``, which skips unless ``MOH_TEST_DATABASE_URL``
points at a database it may create tables in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "api"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def spec() -> dict:
    import yaml

    with (REPO_ROOT / "contracts" / "openapi" / "openapi.yaml").open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def client():
    """A mock-mode client with the in-memory Register reloaded from fixtures.

    The fixture store is process-wide so writes outlive a request; resetting it
    per test keeps one test's new plants out of the next one's Register.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from inventory import enrichment
    from inventory.fixture_repository import reset_fixture_repository

    reset_fixture_repository()
    enrichment.clear_recent()
    with TestClient(app) as test_client:
        yield test_client
    reset_fixture_repository()
    enrichment.clear_recent()


@pytest.fixture
def indoor_location(client) -> dict:
    return next(
        loc for loc in client.get("/api/v1/locations").json() if not loc["is_outdoor"]
    )


@pytest.fixture
def outdoor_location(client) -> dict:
    return next(
        loc for loc in client.get("/api/v1/locations").json() if loc["is_outdoor"]
    )
