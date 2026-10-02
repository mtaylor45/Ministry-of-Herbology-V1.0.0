"""A database connection for the hub's HTTP surface, in live mode — the hub.

The worker's jobs are handed an asyncpg connection in ``ctx``; the API process
has no Arq context, so the router borrows one from the API's own database URL.
It is the same arrangement the journal's ``workers/plates/db.py`` uses — an engine made
lazily, so importing the router never opens a socket and the mock stack keeps
starting with no database in reach — with one difference: every statement in
:mod:`workers.hub.store` is written for asyncpg's ``$1`` placeholders, so this
hands out the *driver* connection underneath SQLAlchemy rather than a
SQLAlchemy one. One set of statements, tested once, serves both processes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_ENGINE: Any = None


def get_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        from app.settings import get_settings
        from sqlalchemy.ext.asyncio import create_async_engine

        _ENGINE = create_async_engine(
            get_settings().database_url, pool_pre_ping=True, future=True
        )
    return _ENGINE


def set_engine(engine: Any) -> None:
    """Point the hub's routes at a different engine. For tests."""
    global _ENGINE
    _ENGINE = engine


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    """An asyncpg connection from the pool, inside a transaction."""
    async with get_engine().begin() as conn:
        raw = await conn.get_raw_connection()
        yield raw.driver_connection
