"""The live fetcher: rate-limited, cached, and honest about who is calling.

Keeping every outbound call behind this one class is what makes the rest of the
worker testable offline — a parser gets a payload, and does not care whether it
arrived from Kew or from ``mocks/recorded/``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Self

import httpx

from ..settings import BotanySettings, get_settings
from ..sources import SourceCache
from .base import FetchResult

#: Retried once, after a pause: a rate limit and a bad minute are not a verdict.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceUnavailable(RuntimeError):
    """The source could not be reached. Distinct from 'the source said no'."""


class HttpFetcher:
    """An ``httpx`` client with manners.

    * a real User-Agent naming the project and a contact URL;
    * a minimum gap between calls to the same host;
    * one retry on 429 and 5xx, honouring ``Retry-After`` when it is sent;
    * an in-process payload cache, because species facts do not change hourly.
    """

    def __init__(
        self,
        settings: BotanySettings | None = None,
        client: httpx.AsyncClient | None = None,
        cache: SourceCache | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self.cache = cache or SourceCache(ttl_s=self.settings.cache_ttl_s)
        self._last_call: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._payloads: dict[str, FetchResult] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept": "application/json",
                },
                timeout=self.settings.http_timeout_s,
                follow_redirects=True,
            )
        return self._client

    async def _wait_turn(self, host: str) -> None:
        async with self._lock:
            gap = self.settings.min_request_interval_s
            last = self._last_call.get(host)
            now = time.monotonic()
            if last is not None and now - last < gap:
                await asyncio.sleep(gap - (now - last))
            self._last_call[host] = time.monotonic()

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        key = SourceCache.key(kind, url, dict(params or {}))
        cached = self._payloads.get(key)
        if cached is not None:
            return FetchResult(
                url=cached.url,
                payload=cached.payload,
                retrieved_at=cached.retrieved_at,
                from_cache=True,
            )

        host = httpx.URL(url).host
        response: httpx.Response | None = None
        last_error: Exception | None = None
        for attempt in (0, 1):
            await self._wait_turn(host)
            try:
                response = await self.client.get(url, params=dict(params or {}))
            except httpx.HTTPError as exc:  # network, DNS, timeout
                last_error = exc
                response = None
            if response is not None and response.status_code not in RETRY_STATUSES:
                break
            if attempt == 0:
                await asyncio.sleep(_retry_after(response, self.settings))

        if response is None:
            raise SourceUnavailable(f"{kind}: {last_error}") from last_error
        if response.status_code >= 400:
            raise SourceUnavailable(
                f"{kind}: HTTP {response.status_code} for {response.url}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            # POWO behind a bot challenge answers 200 with HTML, which is not a
            # taxonomic opinion. Treat it as unreachable, not as "no match".
            raise SourceUnavailable(
                f"{kind}: expected JSON from {response.url}"
            ) from exc

        result = FetchResult(
            url=str(response.url), payload=payload, retrieved_at=datetime.now(UTC)
        )
        self._payloads[key] = result
        return result


def _retry_after(response: httpx.Response | None, settings: BotanySettings) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), 10.0)
            except ValueError:
                pass
    return max(settings.min_request_interval_s, 0.5)
