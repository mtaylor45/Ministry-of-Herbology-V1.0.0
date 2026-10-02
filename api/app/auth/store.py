"""Where sessions live: memory for the demo, Postgres for a deployment.

Both stores keep only SHA-256(token). Validity is decided here, in one
function, so the two stores cannot disagree about what "signed in" means.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

#: the design.
ABSOLUTE_LIFETIME = timedelta(days=365)
IDLE_LIFETIME = timedelta(days=60)
#: `last_seen_at` is written at most this often, so a page load is not a write.
TOUCH_INTERVAL = timedelta(hours=1)
#: Revoked and expired rows are deleted once they are this far gone.
SWEEP_AFTER = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Session:
    id: uuid.UUID
    token_hash: bytes
    epoch: str
    label: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


def is_live(session: Session, epoch: str, now: datetime) -> bool:
    """The one definition of a usable session."""
    return (
        session.revoked_at is None
        and session.epoch == epoch
        and session.expires_at > now
        and session.last_seen_at + IDLE_LIFETIME > now
    )


def now_utc() -> datetime:
    return datetime.now(UTC)


class SessionStore(Protocol):
    async def create(self, token_hash: bytes, epoch: str, label: str) -> Session: ...
    async def find(self, token_hash: bytes) -> Session | None: ...
    async def touch(self, session: Session, now: datetime) -> None: ...
    async def revoke(self, session_id: uuid.UUID, now: datetime) -> None: ...
    async def revoke_all(self, now: datetime) -> None: ...
    async def list_live(self, epoch: str, now: datetime) -> list[Session]: ...


def _new(token_hash: bytes, epoch: str, label: str, now: datetime) -> Session:
    return Session(
        id=uuid.uuid4(),
        token_hash=token_hash,
        epoch=epoch,
        label=label[:60] or "A device",
        created_at=now,
        last_seen_at=now,
        expires_at=now + ABSOLUTE_LIFETIME,
    )


class MemorySessionStore:
    """The demo's store, and the unit tests'. Lost on restart, which in mock
    mode is the point: nothing in mock mode outlives the process."""

    def __init__(self) -> None:
        self._by_hash: dict[bytes, Session] = {}

    async def create(self, token_hash: bytes, epoch: str, label: str) -> Session:
        session = _new(token_hash, epoch, label, now_utc())
        self._by_hash[token_hash] = session
        return session

    async def find(self, token_hash: bytes) -> Session | None:
        return self._by_hash.get(token_hash)

    async def touch(self, session: Session, now: datetime) -> None:
        if session.token_hash in self._by_hash:
            self._by_hash[session.token_hash] = replace(session, last_seen_at=now)

    async def revoke(self, session_id: uuid.UUID, now: datetime) -> None:
        for key, session in self._by_hash.items():
            if session.id == session_id and session.revoked_at is None:
                self._by_hash[key] = replace(session, revoked_at=now)

    async def revoke_all(self, now: datetime) -> None:
        for key, session in self._by_hash.items():
            if session.revoked_at is None:
                self._by_hash[key] = replace(session, revoked_at=now)

    async def list_live(self, epoch: str, now: datetime) -> list[Session]:
        live = [s for s in self._by_hash.values() if is_live(s, epoch, now)]
        return sorted(live, key=lambda s: s.last_seen_at, reverse=True)


_COLUMNS = (
    "id, token_hash, epoch, label, created_at, last_seen_at, expires_at, revoked_at"
)


class DatabaseSessionStore:
    """``household_session`` (migration 008)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, token_hash: bytes, epoch: str, label: str) -> Session:
        now = now_utc()
        session = _new(token_hash, epoch, label, now)
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO household_session "
                    "(id, token_hash, epoch, label, created_at, last_seen_at, expires_at) "
                    "VALUES (:id, :token_hash, :epoch, :label, :now, :now, :expires_at)"
                ),
                {
                    "id": session.id,
                    "token_hash": token_hash,
                    "epoch": epoch,
                    "label": session.label,
                    "now": now,
                    "expires_at": session.expires_at,
                },
            )
            # Opportunistic sweep: a sign-in is rare enough to carry it.
            await connection.execute(
                text(
                    "DELETE FROM household_session "
                    "WHERE coalesce(revoked_at, expires_at) < :cutoff"
                ),
                {"cutoff": now - SWEEP_AFTER},
            )
        return session

    async def find(self, token_hash: bytes) -> Session | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM household_session WHERE token_hash = :h"
                    ),
                    {"h": token_hash},
                )
            ).first()
        return Session(*row) if row else None

    async def touch(self, session: Session, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("UPDATE household_session SET last_seen_at = :now WHERE id = :id"),
                {"now": now, "id": session.id},
            )

    async def revoke(self, session_id: uuid.UUID, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE household_session SET revoked_at = :now "
                    "WHERE id = :id AND revoked_at IS NULL"
                ),
                {"now": now, "id": session_id},
            )

    async def revoke_all(self, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE household_session SET revoked_at = :now WHERE revoked_at IS NULL"
                ),
                {"now": now},
            )

    async def list_live(self, epoch: str, now: datetime) -> list[Session]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM household_session "
                        "WHERE revoked_at IS NULL AND epoch = :epoch "
                        "AND expires_at > :now AND last_seen_at > :idle "
                        "ORDER BY last_seen_at DESC"
                    ),
                    {"epoch": epoch, "now": now, "idle": now - IDLE_LIFETIME},
                )
            ).all()
        return [Session(*row) for row in rows]


def database_store(database_url: str) -> DatabaseSessionStore:
    """A store with its own small pool: sign-in must not queue behind a long
    inventory query, and two connections are plenty for it."""
    return DatabaseSessionStore(
        create_async_engine(
            database_url, pool_size=2, max_overflow=2, pool_pre_ping=True
        )
    )
