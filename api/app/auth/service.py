"""The sign-in's parts, assembled once per process."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.auth import tokens
from app.auth.policy import Policy, load_policy
from app.auth.ratelimit import MemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.auth.secrets import AuthSecrets, load_secrets
from app.auth.store import (
    TOUCH_INTERVAL,
    MemorySessionStore,
    Session,
    SessionStore,
    database_store,
    is_live,
    now_utc,
)
from app.settings import get_settings

logger = logging.getLogger("moh.auth")


@dataclass
class AuthService:
    secrets: AuthSecrets
    store: SessionStore
    limiter: RateLimiter
    policy: Policy
    #: Whether the cookie carries `Secure`: everywhere but plain-http dev.
    secure_cookie: bool
    #: Origins a mutating request may come from.
    allowed_origins: frozenset[str]

    @property
    def enforcing(self) -> bool:
        return self.secrets.enforcing

    @property
    def epoch(self) -> str:
        assert self.secrets.passphrase is not None
        return tokens.epoch_of(self.secrets.passphrase)

    async def session_for(self, token: str | None) -> Session | None:
        """The live session this cookie names, or None. Touches it hourly."""
        if not token or not self.enforcing:
            return None
        session = await self.store.find(tokens.hash_token(token))
        now = now_utc()
        if session is None or not is_live(session, self.epoch, now):
            return None
        if now - session.last_seen_at >= TOUCH_INTERVAL:
            await self.store.touch(session, now)
        return session

    def service_token_ok(self, presented: str | None) -> bool:
        expected = self.secrets.service_token
        return bool(presented and expected and tokens.matches(presented, expected))

    def lunette_token_ok(self, authorization: str | None) -> bool:
        expected = self.secrets.lunette_token
        if not (authorization and expected):
            return False
        scheme, _, presented = authorization.partition(" ")
        return scheme.lower() == "bearer" and tokens.matches(
            presented.strip(), expected
        )


def _origin(url: str) -> str:
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}".lower()


#: The dev server's origin, which the API's CORS already allows (main.py).
DEV_ORIGINS = frozenset({"http://localhost:5173"})

_SERVICE: AuthService | None = None


def build_service() -> AuthService:
    settings = get_settings()
    secrets = load_secrets()
    store: SessionStore
    limiter: RateLimiter
    if settings.mock_mode:
        store, limiter = MemorySessionStore(), MemoryRateLimiter()
    else:
        from redis.asyncio import Redis

        store = database_store(settings.database_url)
        limiter = RedisRateLimiter(Redis.from_url(settings.redis_url))
    if not secrets.enforcing:
        level = logging.INFO if settings.mock_mode else logging.WARNING
        logger.log(
            level,
            "no household passphrase is configured: sign-in is off and the app is open "
            "to anyone who can reach it",
        )
    return AuthService(
        secrets=secrets,
        store=store,
        limiter=limiter,
        policy=load_policy(settings.contracts_dir),
        secure_cookie=settings.public_base_url.lower().startswith("https://"),
        allowed_origins=frozenset({_origin(settings.public_base_url)}) | DEV_ORIGINS,
    )


def get_service() -> AuthService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = build_service()
    return _SERVICE


def set_service(service: AuthService | None) -> None:
    """Replace the process's service. For tests, and to re-read the secrets."""
    global _SERVICE
    _SERVICE = service
