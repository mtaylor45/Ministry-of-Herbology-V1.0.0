"""What there is to notify about — the hub.

Three questions, asked of three owners:

* *What is due today?* — ``GET /tending/rounds``, the scheduler.
* *Is a frost coming?* — ``GET /almanac/frost``, the weather engine.
* *Is anything broken?* — :func:`workers.hub.tasks.hub_health`, which is the hub's
  own and needs no HTTP call.

## Why this goes over HTTP rather than into another package

Reading the scheduler's ``task`` rows out of Postgres directly would be quicker to write
and wrong in two ways. The scheduler generates occurrences **on read** — the
rows only exist because an endpoint materialised them — so a worker querying
the table straight would notify about whatever the last visitor to the app
happened to cause, and about nothing at all on a quiet day. And ``api/tending/``
is not the hub's directory: reaching into another parts of the project's service layer
is the coupling the ownership rule exists to prevent.

So this asks the API the same question a browser asks, over the frozen
contract, on the internal network. The endpoints are 1.2.0 and unchanged; the
two fields this package would like — ``Task.confidence`` and
``MorningRounds.unscheduled`` — are the scheduler's escalations 1 and 3, served today and
read here *defensively*, so this works against an API that has them and against
one that does not (see :mod:`workers.hub.notify.copy`).

## No credential goes on this call

``MOH_API_URL`` points at the API service inside the deployment's own network.
This client sends **no** ``Authorization`` header and no cookie — in particular
it never sends ``MOH_HA_TOKEN``, which belongs to Home Assistant and to nothing
else. It is a separate client from :class:`~workers.hub.sources.http.HomeAssistantFetcher`
for exactly that reason: a shared client is one refactor away from presenting a
hub token to an unrelated host.

The contract declares a ``session`` cookie scheme that nothing enforces yet.
When it is enforced, this worker needs a service identity, and that is a
question for the maintainers — escalated in `the project notes` rather than
guessed at here with a shared secret.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..settings import HubSettings, get_settings
from ..sources.base import HubUnavailable

#: The paths, from ``contracts/openapi/openapi.yaml``. The server block is
#: ``/api/v1``; the host comes from ``MOH_API_URL``.
ROUNDS_PATH = "/tending/rounds"
FROST_PATH = "/almanac/frost"
MEMBERS_PATH = "/members"
SPECIMENS_PATH = "/specimens"
API_PREFIX = "/api/v1"


class MinistryReader(Protocol):
    """The three reads the notification jobs need."""

    async def rounds(self) -> Mapping[str, Any]: ...

    async def frost(self) -> Mapping[str, Any]: ...

    # ``Sequence`` rather than ``list``: a list is invariant in its element
    # type, so a reader returning ``list[dict[...]]`` — which every natural
    # implementation does — would not satisfy ``list[Mapping[...]]``.
    async def members(self) -> Sequence[Mapping[str, Any]]: ...


@dataclass(slots=True)
class ApiReader:
    """The live one: plain HTTP against this deployment's own API."""

    settings: HubSettings = field(default_factory=get_settings)
    _client: Any = None

    def build_client(self) -> Any:
        """The client, with the headers it is allowed to send and no others.

        A method rather than four lines inside :meth:`_get` so a test can hold
        it and assert what is on it. "This call carries no credential" is the
        kind of claim that is true until somebody adds a header in a hurry, and
        a comment does not fail a build.
        """
        import httpx

        return httpx.AsyncClient(
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "application/json",
            },
            timeout=self.settings.http_timeout_s,
        )

    def url_for(self, path: str) -> str:
        return f"{self.settings.api_url.rstrip('/')}{API_PREFIX}{path}"

    async def _get(self, path: str) -> Any:
        import httpx

        url = self.url_for(path)
        if self._client is None:
            self._client = self.build_client()
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise HubUnavailable(f"ministry_api: {exc}") from exc
        if response.status_code >= 400:
            raise HubUnavailable(
                f"ministry_api: HTTP {response.status_code} from {path}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise HubUnavailable(f"ministry_api: expected JSON from {path}") from exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def rounds(self) -> Mapping[str, Any]:
        payload = await self._get(ROUNDS_PATH)
        return payload if isinstance(payload, Mapping) else {}

    async def frost(self) -> Mapping[str, Any]:
        payload = await self._get(FROST_PATH)
        return payload if isinstance(payload, Mapping) else {}

    async def members(self) -> list[Mapping[str, Any]]:
        payload = await self._get(MEMBERS_PATH)
        return [row for row in (payload or ()) if isinstance(row, Mapping)]

    async def specimens(self) -> list[Mapping[str, Any]]:
        """Every plant, for the per-specimen MQTT entities."""
        payload = await self._get(SPECIMENS_PATH)
        return [row for row in (payload or ()) if isinstance(row, Mapping)]


def build_reader(settings: HubSettings | None = None) -> MinistryReader:
    """Which reader this process uses — the same rule as the fetcher's.

    Mock mode answers from :mod:`workers.hub.mocks.ministry`, so the whole
    notification path can be demonstrated with no API running and no network
    at all.
    """
    config = settings or get_settings()
    if config.mock_mode:
        from ..mocks.ministry import MockMinistryReader

        return MockMinistryReader(config)
    return ApiReader(config)
