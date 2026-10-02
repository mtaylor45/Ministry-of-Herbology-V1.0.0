"""Test setup for the maps module.

These live under ``api/grounds/`` because the ownership rule puts ``tests/`` in parts of the project
The test suite's hands. Run them with::

    .venv/bin/python -m pytest api/grounds -q

Everything here runs without a database and without a volume. The live
Postgres path is exercised by ``test_grounds_database.py``, which skips unless
``MOH_TEST_DATABASE_URL`` points at a database it may create tables in.

the design rule holds throughout: nothing below writes down a value it read
out of ``fixtures/``. A test that needs a layer asks the API for one and reads
the size off it; a test that needs a specimen takes the first the Register
offers. The fixtures can be rewritten under these tests without touching them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "api"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def client() -> Any:
    """A mock-mode client whose Grounds start and finish at the fixtures."""
    from fastapi.testclient import TestClient

    from app.main import app
    from grounds.fixture_repository import reset_fixture_repository

    reset_fixture_repository()
    with TestClient(app) as test_client:
        yield test_client
    reset_fixture_repository()


@pytest.fixture
def layers(client: Any) -> list[dict[str, Any]]:
    response = client.get("/api/v1/grounds/layers")
    assert response.status_code == 200, response.text
    return list(response.json())


@pytest.fixture
def floor_plan(layers: list[dict[str, Any]]) -> dict[str, Any]:
    return next(layer for layer in layers if layer["kind"] == "floor_plan")


@pytest.fixture
def survey(layers: list[dict[str, Any]]) -> dict[str, Any]:
    return next(layer for layer in layers if layer["kind"] == "survey")


@pytest.fixture
def a_specimen(client: Any) -> dict[str, Any]:
    register = client.get("/api/v1/specimens").json()
    return dict(register["items"][0])


def png_bytes(width: int = 64, height: int = 48, shade: int = 0xDD) -> bytes:
    """A real PNG of a given size. The upload path reads magic bytes, so a
    stand-in string will not do."""
    from grounds.mocks.plan_image import encode_greyscale_png

    return encode_greyscale_png(
        width, height, [bytearray([shade]) * width for _ in range(height)]
    )
