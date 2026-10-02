"""The household's sign-in, end to end through the app.

Each test gets its own secrets directory and a fresh service, so the
passphrase, the sessions and the failure counters never leak between tests.
The app runs in mock mode: the memory store and limiter. The Postgres store
has its own test (test_auth_database.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import ratelimit
from app.auth.secrets import AuthConfigError, load_secrets
from app.auth.service import build_service, set_service
from app.main import app

PASSPHRASE = "a long garden passphrase"
SERVICE_TOKEN = "s" * 40
LUNETTE_TOKEN = "l" * 40
ORIGIN = "http://localhost:8000"


def _configure(directory: Path, **secrets: str) -> None:
    for name, value in secrets.items():
        (directory / name).write_text(value + "\n")
    set_service(build_service())


@pytest.fixture
def secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("MOH_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("MOH_MOCK_MODE", "true")
    yield tmp_path
    set_service(None)


@pytest.fixture
def client(secrets_dir: Path) -> TestClient:
    _configure(
        secrets_dir,
        moh_household_passphrase=PASSPHRASE,
        moh_service_token=SERVICE_TOKEN,
        moh_lunette_token=LUNETTE_TOKEN,
    )
    return TestClient(app)


def _sign_in(client: TestClient, passphrase: str = PASSPHRASE, ip: str = "10.0.0.1"):
    return client.post(
        "/api/v1/auth/session",
        json={"passphrase": passphrase},
        headers={"x-real-ip": ip, "user-agent": "Mozilla/5.0 (iPhone) Safari/605.1"},
    )


# --------------------------------------------------------------- open (demo)


def test_with_no_passphrase_the_app_is_open_and_says_so(secrets_dir: Path) -> None:
    set_service(build_service())
    client = TestClient(app)
    assert client.get("/api/v1/specimens").status_code == 200
    assert client.get("/api/v1/auth/session").json() == {
        "mode": "open",
        "signed_in": False,
        "expires_at": None,
    }


# ------------------------------------------------------------ the locked door


def test_signed_out_a_protected_route_is_refused_with_the_error_body(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/specimens")
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Sign in to continue.",
        "code": "unauthenticated",
    }
    assert response.headers["cache-control"] == "no-store"


def test_the_open_operations_still_answer(client: TestClient) -> None:
    assert client.get("/api/v1/healthz").status_code == 200
    assert client.get("/api/v1/auth/session").json()["mode"] == "required"
    # The maintainers made-up feed token is the feed route's problem (404), never the sign-in's.
    assert client.get("/api/v1/calendar/not-a-token.ics").status_code != 401


def test_the_docs_page_is_behind_the_door_too(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 401


def test_a_route_the_contract_does_not_know_is_protected(client: TestClient) -> None:
    assert client.get("/api/v1/no-such-route").status_code == 401


# ------------------------------------------------------------------ signing in


def test_a_wrong_passphrase_is_refused_without_a_cookie(client: TestClient) -> None:
    response = _sign_in(client, "not the passphrase at all")
    assert response.status_code == 401
    assert response.json()["code"] == "wrong_passphrase"
    assert "set-cookie" not in response.headers


def test_the_right_passphrase_sets_a_locked_down_cookie(client: TestClient) -> None:
    response = _sign_in(client)
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("moh_session=")
    for attribute in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=31536000"):
        assert attribute in cookie
    # The local dev URL is plain http, so Secure is left off there only.
    assert "Secure" not in cookie

    assert client.get("/api/v1/specimens").status_code == 200
    status = client.get("/api/v1/auth/session").json()
    assert status["mode"] == "required" and status["signed_in"] is True
    assert status["expires_at"] is not None


def test_secure_is_set_when_the_public_url_is_https(
    secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import get_settings

    monkeypatch.setenv("MOH_PUBLIC_BASE_URL", "https://herbology.home.arpa")
    get_settings.cache_clear()
    try:
        _configure(secrets_dir, moh_household_passphrase=PASSPHRASE)
        cookie = _sign_in(TestClient(app, base_url="https://testserver")).headers[
            "set-cookie"
        ]
        assert "; Secure" in cookie
    finally:
        get_settings.cache_clear()


def test_the_database_never_sees_the_token(client: TestClient) -> None:
    from app.auth.service import get_service

    token = _sign_in(client).cookies["moh_session"]
    store = get_service().store
    stored = list(store._by_hash)  # type: ignore[attr-defined]
    assert len(stored) == 1 and stored[0] != token.encode() and len(stored[0]) == 32


# --------------------------------------------------------------- rate limiting


def test_the_sixth_try_from_one_client_is_told_to_wait(client: TestClient) -> None:
    for _ in range(ratelimit.PER_CLIENT_LIMIT):
        assert _sign_in(client, "wrong wrong wrong").status_code == 401
    response = _sign_in(client)  # even the right one
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert "Wait about" in response.json()["detail"]
    # Another client is not punished for this one's guessing.
    assert _sign_in(client, ip="10.0.0.2").status_code == 204


def test_twenty_failures_from_anywhere_lock_the_household(client: TestClient) -> None:
    for n in range(ratelimit.HOUSEHOLD_LIMIT):
        _sign_in(client, "wrong wrong wrong", ip=f"10.1.0.{n}")
    assert _sign_in(client, ip="10.2.0.1").status_code == 429


def test_a_failure_is_logged_without_what_was_typed(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    _sign_in(client, "nearly the garden passphrase")
    assert "sign-in refused for 10.0.0.1" in caplog.text
    assert "nearly the garden" not in caplog.text


# ---------------------------------------------------------- signing out, rotation


def test_signing_out_this_device(client: TestClient) -> None:
    _sign_in(client)
    response = client.delete("/api/v1/auth/session")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/api/v1/specimens").status_code == 401


def test_a_revoked_cookie_is_cleared_when_it_is_refused(client: TestClient) -> None:
    token = _sign_in(client).cookies["moh_session"]
    client.delete("/api/v1/auth/session")
    client.cookies.set("moh_session", token)
    response = client.get("/api/v1/specimens")
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_the_device_list_and_signing_out_everywhere(client: TestClient) -> None:
    phone = TestClient(app)
    _sign_in(phone)
    _sign_in(client)
    items = client.get("/api/v1/auth/sessions").json()["items"]
    assert len(items) == 2
    assert [i["current"] for i in items].count(True) == 1
    assert all(i["label"] == "Safari on iPhone" for i in items)
    assert all(
        set(i) == {"label", "created_at", "last_seen_at", "current"} for i in items
    )

    assert client.delete("/api/v1/auth/sessions").status_code == 204
    assert phone.get("/api/v1/specimens").status_code == 401
    assert client.get("/api/v1/specimens").status_code == 401


def test_rotating_the_passphrase_signs_out_every_device(
    client: TestClient, secrets_dir: Path
) -> None:
    _sign_in(client)
    store = __import__("app.auth.service", fromlist=["get_service"]).get_service().store
    # The operator recreates the secret and redeploys: same sessions, new secret.
    (secrets_dir / "moh_household_passphrase").write_text(
        "an entirely new passphrase\n"
    )
    service = build_service()
    service.store = store
    set_service(service)
    assert client.get("/api/v1/specimens").status_code == 401
    assert _sign_in(client, "an entirely new passphrase").status_code == 204


# -------------------------------------------------------- the stack's own callers


def test_the_service_token_reads_but_never_writes(client: TestClient) -> None:
    header = {"x-moh-service-token": SERVICE_TOKEN}
    assert client.get("/api/v1/tending/rounds", headers=header).status_code == 200
    assert (
        client.post("/api/v1/specimens", headers=header, json={"name": "x"}).status_code
        == 401
    )


def test_a_wrong_service_token_is_refused_even_with_a_cookie(
    client: TestClient,
) -> None:
    _sign_in(client)
    response = client.get(
        "/api/v1/specimens", headers={"x-moh-service-token": "wrong" * 8}
    )
    assert response.status_code == 401


def test_the_lunette_token_opens_the_lunette_and_nothing_else(
    client: TestClient,
) -> None:
    bearer = {"authorization": f"Bearer {LUNETTE_TOKEN}"}
    assert client.get("/api/v1/hub/lunette", headers=bearer).status_code != 401
    assert client.get("/api/v1/specimens", headers=bearer).status_code == 401
    assert client.get("/api/v1/hub/lunette?token=" + LUNETTE_TOKEN).status_code == 401


# ------------------------------------------------------------------- cross-site


def test_a_change_from_another_site_is_refused(client: TestClient) -> None:
    _sign_in(client)
    response = client.post(
        "/api/v1/specimens",
        json={"name": "Fern"},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "cross_site"


def test_a_form_post_is_refused_even_from_here(client: TestClient) -> None:
    _sign_in(client)
    response = client.post(
        "/api/v1/specimens",
        content=b"name=Fern",
        headers={"content-type": "application/x-www-form-urlencoded", "origin": ORIGIN},
    )
    assert response.status_code == 403


def test_a_json_change_from_this_app_goes_through(client: TestClient) -> None:
    _sign_in(client)
    # An empty body: it passes the door and the cross-site checks and is then
    # refused by the route itself (422), so the shared mock data is untouched.
    response = client.post("/api/v1/specimens", json={}, headers={"origin": ORIGIN})
    assert response.status_code == 422


def test_a_preflight_is_answered_not_refused(client: TestClient) -> None:
    response = client.options(
        "/api/v1/specimens",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "POST",
        },
    )
    assert response.status_code == 200


# -------------------------------------------------------------- configuration


def test_a_short_passphrase_stops_startup_naming_the_secret(secrets_dir: Path) -> None:
    (secrets_dir / "moh_household_passphrase").write_text("short\n")
    with pytest.raises(AuthConfigError) as error:
        load_secrets()
    assert "moh_household_passphrase" in str(error.value)
    assert "short" not in str(error.value).replace("shorter", "")


def test_an_empty_secret_file_means_not_configured(secrets_dir: Path) -> None:
    (secrets_dir / "moh_household_passphrase").write_text("\n")
    assert load_secrets().enforcing is False
