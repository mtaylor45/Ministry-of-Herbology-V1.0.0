"""The only thing in this package that touches the network.

Split out so every parser and the whole pipeline are testable against recorded
payloads — the same reason the botany worker split `workers/botany/connectors/http.py`
out. The suite never makes a request; `tests/` drive stubs that implement the
:class:`~workers.plates.sources.PlateFetcher` protocol.

Two things this module is careful about:

* **Bytes are bounded while they arrive, not after.** A catalogue that answers
  a 2 GB stream must not be allowed to put 2 GB in memory first and then be
  told it was too big, so the read stops the moment it is one byte over.
* **The generator's key goes in a header and nowhere else.** Not a query
  parameter, not an exception message, not a log line. A key in a URL ends up
  in an access log, which is the defect the design addendum was written about.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import httpx

#: Sent on every request. A public catalogue is entitled to know who is asking,
#: and an operator running this deployment is the one asking.
USER_AGENT = "MinistryOfHerbology/1.0 (self-hosted plant journal; plate sourcing)"

_CHUNK = 64 * 1024


class ImageTooLargeToFetch(ValueError):
    """The response went past the configured byte bound while arriving."""


class HttpPlateFetcher:
    """Real HTTP, with a timeout the operator can lower."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_image_bytes: int = 25 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_image_bytes
        self._client = client

    def _make_client(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"user-agent": USER_AGENT},
        )

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> Any:
        client = self._make_client()
        try:
            response = await client.get(url, params=dict(params or {}))
            response.raise_for_status()
            return response.json()
        finally:
            if self._client is None:
                await client.aclose()

    async def get_bytes(self, kind: str, url: str) -> bytes:
        """Download an image, refusing the moment it is past the bound."""
        client = self._make_client()
        buffer = bytearray()
        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(_CHUNK):
                    buffer.extend(chunk)
                    if len(buffer) > self._max_bytes:
                        raise ImageTooLargeToFetch(
                            f"an image past this deployment's "
                            f"{self._max_bytes:,}-byte bound, so the download "
                            "was abandoned rather than finished."
                        )
        finally:
            if self._client is None:
                await client.aclose()
        return bytes(buffer)

    async def generate_image(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str | None,
        prompt: str,
    ) -> bytes:
        """Ask the operator's generator for one image.

        The key rides in ``authorization``. The response may be raw bytes or a
        base64 payload in the shape most images APIs use; both are handled, and
        anything else returns empty so `generation.py` reports "no plate"
        rather than storing a JSON error document as a picture.
        """
        body: dict[str, Any] = {"prompt": prompt, "n": 1}
        if model:
            body["model"] = model
        client = self._make_client()
        try:
            response = await client.post(
                endpoint,
                json=body,
                headers={
                    "authorization": f"Bearer {api_key}",
                    "user-agent": USER_AGENT,
                },
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("image/"):
                return response.content
            return _decode_image_payload(response.json())
        finally:
            if self._client is None:
                await client.aclose()


def _decode_image_payload(payload: Any) -> bytes:
    """Pull image bytes out of a JSON images response, or return nothing.

    Deliberately forgiving about *where* the base64 is and unforgiving about
    whether it decoded: a half-understood payload becomes b"" and therefore
    becomes "no plate", never a stored file.
    """
    if not isinstance(payload, dict):
        return b""
    entries = payload.get("data") or payload.get("images") or []
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries:
        encoded = (
            entry.get("b64_json") or entry.get("base64") or entry.get("image")
            if isinstance(entry, dict)
            else entry if isinstance(entry, str) else None
        )
        if not isinstance(encoded, str) or not encoded:
            continue
        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
    return b""
