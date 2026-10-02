"""Shared test setup. Owner: The test suite."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def spec() -> dict:
    import yaml

    with (REPO_ROOT / "contracts" / "openapi" / "openapi.yaml").open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="session")
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)
