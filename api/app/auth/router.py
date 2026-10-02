"""The five ``/auth`` routes."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import tokens
from app.auth.middleware import clear_cookie_header, session_cookie
from app.auth.service import AuthService, get_service
from app.auth.store import ABSOLUTE_LIFETIME, Session, now_utc

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("moh.auth")


class AuthSignIn(BaseModel):
    passphrase: str = Field(min_length=1, max_length=1024)


class AuthStatus(BaseModel):
    mode: str
    signed_in: bool
    expires_at: datetime | None


class AuthSessionInfo(BaseModel):
    label: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


class AuthSessionList(BaseModel):
    items: list[AuthSessionInfo]


def _client(request: Request) -> str:
    # Nginx sets X-Real-IP and is the only thing that can reach the API in the
    # stack. Without it — the demo, a test — the socket peer.
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "unknown"
    )


def _current(request: Request) -> Session | None:
    return getattr(request.state, "auth_session", None)


def _cookie(service: AuthService, token: str) -> str:
    secure = "; Secure" if service.secure_cookie else ""
    max_age = int(ABSOLUTE_LIFETIME.total_seconds())
    return (
        f"{tokens.COOKIE_NAME}={token}; HttpOnly{secure}; SameSite=Lax; "
        f"Path=/; Max-Age={max_age}"
    )


def _error(
    status: int, detail: str, code: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"detail": detail, "code": code},
        status_code=status,
        headers={"cache-control": "no-store", **(headers or {})},
    )


def _signed_out(service: AuthService) -> Response:
    response = Response(status_code=204, headers={"cache-control": "no-store"})
    name, value = clear_cookie_header(service)
    response.headers.append(name.decode(), value.decode())
    return response


@router.get("/session", response_model=AuthStatus, operation_id="getAuthSession")
async def get_auth_session(request: Request, response: Response) -> AuthStatus:
    response.headers["cache-control"] = "no-store"
    service = get_service()
    if not service.enforcing:
        return AuthStatus(mode="open", signed_in=False, expires_at=None)
    token = session_cookie(
        {b"cookie": request.headers.get("cookie", "").encode("latin-1")}
    )
    session = await service.session_for(token)
    return AuthStatus(
        mode="required",
        signed_in=session is not None,
        expires_at=session.expires_at if session else None,
    )


@router.post("/session", status_code=204, operation_id="createAuthSession")
async def create_auth_session(body: AuthSignIn, request: Request) -> Response:
    service = get_service()
    if not service.enforcing:
        # The demo: there is nothing to sign in to, and no cookie is issued.
        return Response(status_code=204, headers={"cache-control": "no-store"})

    client = _client(request)
    verdict = await service.limiter.check(client)
    if verdict.blocked:
        minutes = max(1, round(verdict.retry_after / 60))
        return _error(
            429,
            f"Too many tries. Wait about {minutes} minute{'s' if minutes != 1 else ''} "
            "and try again.",
            "rate_limited",
            {"retry-after": str(verdict.retry_after)},
        )

    assert service.secrets.passphrase is not None
    if not tokens.matches(body.passphrase, service.secrets.passphrase):
        count = await service.limiter.fail(client)
        # Never the submitted text: a typo of the real passphrase is most of it.
        logger.warning("sign-in refused for %s (%d in this window)", client, count)
        return _error(
            401, "That passphrase is not the household's.", "wrong_passphrase"
        )

    await service.limiter.succeed(client)
    token = tokens.new_token()
    await service.store.create(
        tokens.hash_token(token),
        service.epoch,
        tokens.device_label(request.headers.get("user-agent")),
    )
    response = Response(status_code=204, headers={"cache-control": "no-store"})
    response.headers.append("set-cookie", _cookie(service, token))
    return response


@router.delete("/session", status_code=204, operation_id="deleteAuthSession")
async def delete_auth_session(request: Request) -> Response:
    service = get_service()
    session = _current(request)
    if session is not None:
        await service.store.revoke(session.id, now_utc())
    return _signed_out(service)


@router.get(
    "/sessions", response_model=AuthSessionList, operation_id="listAuthSessions"
)
async def list_auth_sessions(request: Request, response: Response) -> AuthSessionList:
    response.headers["cache-control"] = "no-store"
    service = get_service()
    if not service.enforcing:
        return AuthSessionList(items=[])
    current = _current(request)
    live = await service.store.list_live(service.epoch, now_utc())
    return AuthSessionList(
        items=[
            AuthSessionInfo(
                label=s.label,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                current=current is not None and s.id == current.id,
            )
            for s in live
        ]
    )


@router.delete("/sessions", status_code=204, operation_id="deleteAllAuthSessions")
async def delete_all_auth_sessions() -> Response:
    service = get_service()
    if service.enforcing:
        await service.store.revoke_all(now_utc())
        logger.warning("every household session was revoked")
    return _signed_out(service)
