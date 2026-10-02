"""Counting failed sign-ins.

Fixed fifteen-minute windows. Five failures from one client blocks that
client; twenty from any mix blocks everyone, including the right passphrase,
until the window ends. A household locked out of its garden app for fifteen
minutes is the safe failure.

Redis in a deployment, because there are two API replicas and a counter in
each would double every limit. Memory in the demo, which has no Redis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

WINDOW_SECONDS = 15 * 60
PER_CLIENT_LIMIT = 5
HOUSEHOLD_LIMIT = 20

_HOUSEHOLD = "*"


@dataclass(frozen=True, slots=True)
class Verdict:
    blocked: bool
    retry_after: int = 0


class RateLimiter(Protocol):
    async def check(self, client: str) -> Verdict: ...
    async def fail(self, client: str) -> int: ...
    async def succeed(self, client: str) -> None: ...


def _window(now: float) -> tuple[int, int]:
    """The current window's number, and the seconds left in it."""
    start = int(now // WINDOW_SECONDS)
    remaining = WINDOW_SECONDS - int(now - start * WINDOW_SECONDS)
    return start, max(remaining, 1)


class MemoryRateLimiter:
    def __init__(self, clock: Any = time.time) -> None:
        self._clock = clock
        self._counts: dict[tuple[int, str], int] = {}

    def _get(self, window: int, key: str) -> int:
        return self._counts.get((window, key), 0)

    async def check(self, client: str) -> Verdict:
        window, remaining = _window(self._clock())
        if (
            self._get(window, client) >= PER_CLIENT_LIMIT
            or self._get(window, _HOUSEHOLD) >= HOUSEHOLD_LIMIT
        ):
            return Verdict(True, remaining)
        return Verdict(False)

    async def fail(self, client: str) -> int:
        window, _ = _window(self._clock())
        # Old windows are dropped as new ones start, so this cannot grow.
        self._counts = {k: v for k, v in self._counts.items() if k[0] == window}
        for key in (client, _HOUSEHOLD):
            self._counts[(window, key)] = self._get(window, key) + 1
        return self._get(window, client)

    async def succeed(self, client: str) -> None:
        window, _ = _window(self._clock())
        self._counts.pop((window, client), None)


class RedisRateLimiter:
    def __init__(self, redis: Any, clock: Any = time.time) -> None:
        self._redis = redis
        self._clock = clock

    @staticmethod
    def _key(window: int, who: str) -> str:
        return f"moh:auth:fail:{window}:{who}"

    async def check(self, client: str) -> Verdict:
        window, remaining = _window(self._clock())
        mine, everyone = await self._redis.mget(
            self._key(window, client), self._key(window, _HOUSEHOLD)
        )
        if int(mine or 0) >= PER_CLIENT_LIMIT or int(everyone or 0) >= HOUSEHOLD_LIMIT:
            return Verdict(True, remaining)
        return Verdict(False)

    async def fail(self, client: str) -> int:
        window, remaining = _window(self._clock())
        pipe = self._redis.pipeline()
        for who in (client, _HOUSEHOLD):
            pipe.incr(self._key(window, who))
            pipe.expire(self._key(window, who), remaining + 5)
        mine, *_ = await pipe.execute()
        return int(mine)

    async def succeed(self, client: str) -> None:
        window, _ = _window(self._clock())
        await self._redis.delete(self._key(window, client))
