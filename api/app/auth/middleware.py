"""Enforcement, in one place.

A plain ASGI middleware rather than a FastAPI dependency, so no router can
forget it: every request under ``/api/v1`` passes through here before any
parts of the project's code runs. What it lets through:

* everything, when no passphrase is configured — the demo (§8);
* operations the contract marks ``security: []`` (healthz, the calendar feed,
  the sign-in routes);
* a GET carrying the stack's service token (§5);
* ``/hub/lunette`` with the Lunette's device token (§6);
* any request whose ``moh_session`` cookie names a live session — and, for a
  mutating one, that also passes the cross-site checks below.

Everything else gets ``401`` with the contract's ``Error`` body.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from typing import Any

from app.auth.service import AuthService, get_service
from app.auth.tokens import COOKIE_NAME

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SERVICE_HEADER = b"x-moh-service-token"


def _headers(scope: dict[str, Any]) -> dict[bytes, bytes]:
    # Last one wins; nothing here is legitimately repeated.
    return {name.lower(): value for name, value in scope.get("headers", [])}


def session_cookie(headers: dict[bytes, bytes]) -> str | None:
    raw = headers.get(b"cookie")
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw.decode("latin-1"))
    except Exception:  # noqa: BLE001 - a malformed cookie header is no cookie
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


def clear_cookie_header(service: AuthService) -> tuple[bytes, bytes]:
    secure = "; Secure" if service.secure_cookie else ""
    value = f"{COOKIE_NAME}=; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age=0"
    return (b"set-cookie", value.encode("latin-1"))


async def _refuse(
    send: Any,
    status: int,
    detail: str,
    code: str,
    extra: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps({"detail": detail, "code": code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *(extra or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def cross_site_problem(
    method: str, headers: dict[bytes, bytes], service: AuthService
) -> str | None:
    """Why a cookie-carrying mutating request looks forged, or None.

    SameSite=Lax already keeps the cookie off a cross-site POST. These two
    checks are the belt to that brace: an Origin that is not ours is refused,
    and a body must be JSON — or a multipart upload whose Origin is ours —
    because a plain HTML form on another site can produce neither.
    """
    if method not in _MUTATING:
        return None
    origin = headers.get(b"origin", b"").decode("latin-1").lower()
    if origin and origin not in service.allowed_origins:
        return "This request came from another site, so it was refused."
    has_body = headers.get(b"content-length", b"0") not in (b"0", b"") or (
        b"transfer-encoding" in headers
    )
    if not has_body:
        return None
    content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
    if content_type.startswith("application/json"):
        return None
    if (
        content_type.startswith("multipart/form-data")
        and origin in service.allowed_origins
    ):
        return None
    return "Changes must be sent as JSON from this app."


class AuthMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        # A CORS preflight carries no cookie by design; CORS answers it.
        if (
            scope["type"] != "http"
            or scope["method"] == "OPTIONS"
            or not scope["path"].startswith("/api/v1")
        ):
            await self.app(scope, receive, send)
            return

        service = get_service()
        if not service.enforcing:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        headers = _headers(scope)
        operation = service.policy.match(method, path)

        if operation is not None and operation.open:
            await self.app(scope, receive, send)
            return

        presented = headers.get(SERVICE_HEADER)
        if presented is not None:
            if method == "GET" and service.service_token_ok(
                presented.decode("latin-1")
            ):
                await self.app(scope, receive, send)
                return
            # A wrong service token is not a reason to try the cookie instead.
            await _refuse(
                send, 401, "The service token was not accepted.", "unauthenticated"
            )
            return

        if operation is not None and operation.accepts_lunette:
            authorization = headers.get(b"authorization")
            if authorization and service.lunette_token_ok(
                authorization.decode("latin-1")
            ):
                await self.app(scope, receive, send)
                return

        token = session_cookie(headers)
        session = await service.session_for(token)
        if session is None:
            extra = [clear_cookie_header(service)] if token else []
            await _refuse(send, 401, "Sign in to continue.", "unauthenticated", extra)
            return

        problem = cross_site_problem(method, headers, service)
        if problem is not None:
            await _refuse(send, 403, problem, "cross_site")
            return

        scope.setdefault("state", {})["auth_session"] = session
        await self.app(scope, receive, send)
