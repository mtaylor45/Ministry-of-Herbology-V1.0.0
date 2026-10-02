"""The live fetcher: rate-limited, polite, and the only socket in the worker.

Deliberately close to ``workers/botany/connectors/http.py``. The two could be
shared, and should be — but the shared home for them would be outside both
parts of the project' directories, so that is a note for the maintainers rather than an import
across
a boundary the ownership rule draws.

One difference matters. NWS **requires** a User-Agent naming a contact; it
answers 403 without one. Open-Meteo does not require one and gets it anyway.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Self

import httpx

from ..settings import WeatherSettings, get_settings
from .base import FetchResult, SourceUnavailable

#: Retried once, after a pause: a rate limit and a bad minute are not a verdict.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HttpFetcher:
    """An ``httpx`` client with manners."""

    def __init__(
        self,
        settings: WeatherSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._last_call: dict[str, float] = {}
        self._lock = asyncio.Lock()

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
                    "Accept": "application/geo+json, application/json",
                },
                timeout=self.settings.http_timeout_s,
                follow_redirects=True,
            )
        return self._client

    async def _wait_turn(self, host: str | None) -> None:
        async with self._lock:
            gap = self.settings.min_request_interval_s
            last = self._last_call.get(host or "")
            now = time.monotonic()
            if last is not None and now - last < gap:
                await asyncio.sleep(gap - (now - last))
            self._last_call[host or ""] = time.monotonic()

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
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
                f"{kind}: HTTP {response.status_code} for {response.url} "
                f"— {_reason(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceUnavailable(
                f"{kind}: expected JSON from {response.url}"
            ) from exc

        # Open-Meteo answers 200 with ``{"error": true, "reason": ...}`` for
        # some malformed requests, so a status code alone is not consent.
        if isinstance(payload, dict) and payload.get("error"):
            raise SourceUnavailable(f"{kind}: {payload.get('reason', 'refused')}")

        return FetchResult(
            url=str(response.url), payload=payload, retrieved_at=datetime.now(UTC)
        )


def _reason(response: httpx.Response) -> str:
    """Open-Meteo puts the real complaint in the body; NWS uses ``detail``."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("reason") or body.get("detail") or body)[:200]
    return str(body)[:200]


def _retry_after(response: httpx.Response | None, settings: WeatherSettings) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), 10.0)
            except ValueError:
                pass
    return max(settings.min_request_interval_s, 0.5)
