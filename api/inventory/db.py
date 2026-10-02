"""The async engine for live mode.

Created lazily, so importing the inventory package never opens a socket and the
mock stack keeps starting without a database in reach.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import get_settings

_ENGINE: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            future=True,
        )
    return _ENGINE


def set_engine(engine: AsyncEngine | None) -> None:
    """Point the API at a different engine. For tests and for the fixture loader."""
    global _ENGINE
    _ENGINE = engine


async def dispose_engine() -> None:
    global _ENGINE
    if _ENGINE is not None:
        await _ENGINE.dispose()
        _ENGINE = None
