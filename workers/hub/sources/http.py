"""The live fetcher: the only socket in this worker — the hub.

Deliberately close to ``workers/weather/sources/http.py`` and
``workers/botany/connectors/http.py``. The three could be shared and should be,
but their shared home would sit outside all three parts of the project' directories, so
that is a note for the maintainers rather than an import across the boundary the ownership rule
draws.

Two differences from the weather engine's matter.

**Everything here carries a bearer token.** ``MOH_HA_TOKEN`` is a long-lived
Home Assistant access token and it reaches this file as a
:class:`~pydantic.SecretStr`. It is put into one header, in one place, and is
never logged, never interpolated into an error, and never returned. The error
paths below are written on the assumption that whatever they produce ends up
on ``integration.last_error``, which the Ministry Office renders — and
:func:`workers.hub.health.redact` scrubs them again on the way past, because
one careful module is not a guarantee and two are cheap.

**A 401 is not retried.** A rate limit is a bad minute; a refused token is a
verdict, and re-presenting it only helps a brute-force detector decide we are
one.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Self

import httpx

from ..settings import HubSettings, get_settings
from .base import FetchResult, HubUnavailable

#: Retried once, after a pause: a restarting hub and a busy minute are not a
#: verdict. 401 and 403 are deliberately absent — see the module note.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: What a refused token is reported as. The status code alone ("HTTP 401")
#: sends an operator to a log file; this sends them to the one setting that is
#: actually wrong.
UNAUTHORISED = (
    "Home Assistant refused the access token (HTTP {status}). Check "
    "MOH_HA_TOKEN — a long-lived token is revoked when the user that "
    "created it is removed."
)


class HomeAssistantFetcher:
    """An ``httpx`` client with manners and a bearer token."""

    def __init__(
        self,
        settings: HubSettings | None = None,
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
                headers=self._headers(),
                timeout=self.settings.http_timeout_s,
                follow_redirects=True,
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        """The one place the token is read.

        Absent when unset rather than sent empty: an empty ``Authorization``
        header makes Home Assistant answer 400, which reads as a malformed
        request when the real problem is an unconfigured deployment.
        """
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        token = self.settings.ha_token.get_secret_value()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def url_for(self, path: str) -> str:
        """``/states`` against the configured base, with no doubled slashes."""
        return f"{self.settings.ha_api_url}/{path.lstrip('/')}".rstrip("/")

    async def _wait_turn(self, host: str | None) -> None:
        async with self._lock:
            gap = self.settings.min_request_interval_s
            last = self._last_call.get(host or "")
            now = time.monotonic()
            if last is not None and now - last < gap:
                await asyncio.sleep(gap - (now - last))
            self._last_call[host or ""] = time.monotonic()

    async def get_json(
        self, kind: str, path: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        return await self._request(kind, path, params=params)

    async def post_json(
        self, kind: str, path: str, body: Mapping[str, Any] | None = None
    ) -> FetchResult:
        """Call a Home Assistant service — the one thing this worker *does*.

        ``POST /api/services/notify/<service>`` is the notification path. It is retried on the same
        statuses a read is, for
        the same reason: a restarting hub is not a verdict. A duplicate
        notification from a retry is a far smaller harm than a freeze warning
        that was dropped because the hub was rebooting.

        Home Assistant answers a service call with a JSON list of the states it
        changed — usually empty for ``notify`` — so the payload is returned
        rather than discarded, and an empty body is read as an empty list
        instead of as a failure.
        """
        return await self._request(kind, path, body=body, method="POST")

    async def _request(
        self,
        kind: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        method: str = "GET",
    ) -> FetchResult:
        if not self.settings.ha_base_url:
            raise HubUnavailable(
                f"{kind}: no Home Assistant base URL is configured " "(MOH_HA_BASE_URL)"
            )
        url = self.url_for(path)
        host = httpx.URL(url).host
        response: httpx.Response | None = None
        last_error: Exception | None = None

        for attempt in (0, 1):
            await self._wait_turn(host)
            try:
                if method == "POST":
                    response = await self.client.post(url, json=dict(body or {}))
                else:
                    response = await self.client.get(url, params=dict(params or {}))
            except httpx.HTTPError as exc:  # network, DNS, TLS, timeout
                last_error = exc
                response = None
            if response is not None and response.status_code not in RETRY_STATUSES:
                break
            if attempt == 0:
                await asyncio.sleep(_retry_after(response, self.settings))

        if response is None:
            raise HubUnavailable(f"{kind}: {last_error}") from last_error
        if response.status_code in (401, 403):
            raise HubUnavailable(
                f"{kind}: " + UNAUTHORISED.format(status=response.status_code)
            )
        if response.status_code == 404:
            raise HubUnavailable(
                f"{kind}: Home Assistant has no {path} (HTTP 404). The entity "
                "may have been renamed or removed."
            )
        if response.status_code >= 400:
            raise HubUnavailable(
                f"{kind}: HTTP {response.status_code} from Home Assistant "
                f"— {_reason(response)}"
            )
        if method == "POST" and not response.content.strip():
            # A service call that changed no state answers 200 with an empty
            # body. That is success, not a parse failure.
            return FetchResult(url=url, payload=[], retrieved_at=datetime.now(UTC))
        try:
            payload = response.json()
        except ValueError as exc:
            raise HubUnavailable(
                f"{kind}: expected JSON from Home Assistant at {path}; got "
                f"{response.headers.get('content-type', 'no content-type')}"
            ) from exc

        return FetchResult(url=url, payload=payload, retrieved_at=datetime.now(UTC))


def _reason(response: httpx.Response) -> str:
    """Home Assistant puts the complaint in ``message``; a proxy will not.

    The response *URL* is never quoted back. A misconfigured deployment can
    put credentials in a base URL, and this string is bound for a column the
    UI renders.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("message") or body.get("detail") or body)[:200]
    return str(body)[:200]


def _retry_after(response: httpx.Response | None, settings: HubSettings) -> float:
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), 10.0)
            except ValueError:
                pass
    return max(settings.min_request_interval_s, 0.5)
