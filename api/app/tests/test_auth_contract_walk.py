"""Every operation in the contract, walked signed out.

The middleware reads the open list from the contract; this test reads the
contract separately and asks the running app, so a mismatch between the two —
or an operation whose router answers before the middleware runs — fails here.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth.service import build_service, set_service
from app.main import app
from app.settings import REPO_ROOT

SPEC = yaml.safe_load(
    (REPO_ROOT / "contracts" / "openapi" / "openapi.yaml").read_text()
)
DEFAULT = SPEC["security"]
OPERATIONS = [
    (method, template, operation)
    for template, item in SPEC["paths"].items()
    for method, operation in item.items()
    if method in {"get", "put", "post", "delete", "patch"}
]
PLACEHOLDER = "01890040-0000-7000-8000-000000000001"


def _url(template: str) -> str:
    return "/api/v1" + re.sub(r"\{[^}]+\}", PLACEHOLDER, template)


def _is_open(operation: dict) -> bool:
    return operation.get("security", DEFAULT) == []


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    directory: Path = tmp_path_factory.mktemp("secrets")
    (directory / "moh_household_passphrase").write_text("a long garden passphrase\n")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MOH_SECRETS_DIR", str(directory))
        patch.setenv("MOH_MOCK_MODE", "true")
        set_service(build_service())
        yield TestClient(app)
        set_service(None)


@pytest.mark.parametrize(
    ("method", "template"),
    [(m, t) for m, t, op in OPERATIONS if not _is_open(op)],
)
def test_signed_out_every_protected_operation_is_refused(
    client: TestClient, method: str, template: str
) -> None:
    response = client.request(method.upper(), _url(template), json={})
    assert (
        response.status_code == 401
    ), f"{method.upper()} {template} answered signed out"
    assert response.json()["code"] == "unauthenticated"


@pytest.mark.parametrize(
    ("method", "template"),
    [(m, t) for m, t, op in OPERATIONS if _is_open(op)],
)
def test_every_open_operation_answers_signed_out(
    client: TestClient, method: str, template: str
) -> None:
    body = {"passphrase": "not it"} if template == "/auth/session" else None
    response = client.request(method.upper(), _url(template), json=body)
    assert response.json().get("code") != "unauthenticated", f"{template} was refused"


def test_the_open_list_is_exactly_the_four_adr_0032_names() -> None:
    open_ops = sorted((m, t) for m, t, op in OPERATIONS if _is_open(op))
    assert open_ops == [
        ("get", "/auth/session"),
        ("get", "/calendar/{token}.ics"),
        ("get", "/healthz"),
        ("post", "/auth/session"),
    ]
