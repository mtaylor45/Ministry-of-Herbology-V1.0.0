"""The hub's HTTP surface — the hub.

``/hub/integrations``, ``/hub/sensors`` and ``/hub/lunette``: four contract
routes that sat in ``NOT_YET_IMPLEMENTED`` to an earlier release while the engines
behind them were built and tested and nothing served them. The handlers are
thin on purpose. What an integration's status is lives in
:mod:`workers.hub.health` and :mod:`workers.hub.office`; what the Lunette
shows lives in :mod:`workers.hub.lunette`.

Mounted by the API from ``workers/``, which the API image puts on
``PYTHONPATH`` alongside ``api/`` — the botany worker's arrangement for
``workers/botany/router.py`` and the journal's for ``workers/plates/router.py``.

Mock mode answers from the derived world in :mod:`workers.hub.world`
and an in-memory sensor list; live mode reads and writes the ``integration``
and ``sensor_source`` tables through :mod:`workers.hub.db`. The Lunette reads
the round over HTTP in both modes, from ``MOH_API_URL``, exactly as the
notification jobs do: ``api/tending/`` is the scheduler's, and the dependency runs scheduler → hub,
never the other way.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status

from . import office
from .settings import HubSettings, get_settings

router = APIRouter(prefix="/hub", tags=["hub"])


def hub_settings() -> HubSettings:
    return get_settings()


#: Module-level dependency singletons, as every other router here does it
#: (``Repo = Depends(get_repository)``), so no call sits in a default argument.
Settings = Depends(hub_settings)
SensorBody = Body(...)


async def hub_connection(settings: HubSettings = Settings) -> AsyncIterator[Any]:
    """``None`` in mock mode; a pooled asyncpg connection in live mode."""
    if settings.mock_mode:
        yield None
        return
    from .db import connection

    async with connection() as conn:
        yield conn


def ha_source() -> Any:
    """The Home Assistant a ``POST /hub/sensors`` checks against. Overridable."""
    return None


Conn = Depends(hub_connection)
HA = Depends(ha_source)


@router.get("/integrations")
async def list_integrations(
    settings: HubSettings = Settings, conn: Any = Conn
) -> list[dict[str, Any]]:
    """Integration health for the Ministry Office.

    A fresh deployment answers ``unconfigured`` for Home Assistant and MQTT:
    a setup step, not a fault.
    """
    return await office.list_integrations(settings, conn)


@router.get("/sensors")
async def list_sensors(
    settings: HubSettings = Settings, conn: Any = Conn
) -> list[dict[str, Any]]:
    return await office.list_sensors(settings, conn)


@router.post("/sensors", status_code=status.HTTP_201_CREATED)
async def create_sensor(
    response: Response,
    body: dict[str, Any] = SensorBody,
    settings: HubSettings = Settings,
    conn: Any = Conn,
    ha: Any = HA,
) -> dict[str, Any]:
    """Add a sensor source, after checking the adapter could read it.

    What was and was not checked travels in ``X-Hub-Check``: the contract's
    ``SensorSource`` has no field for it, and this route does not invent one.
    """
    try:
        checked = await office.create_sensor(settings, body, conn, ha=ha)
    except office.SensorRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.problems
        ) from exc
    response.headers["X-Hub-Check"] = checked.note
    return checked.source.to_dict()


def rounds_reader(settings: HubSettings = Settings) -> Any:
    """Where the Lunette reads the round: ``MOH_API_URL``, in both modes.

    Not :func:`workers.hub.notify.state.build_reader`, which answers from the hub's
    own mock in mock mode. The panel must show what Morning Rounds shows —
    The scheduler's round, under whatever scenario the operator selected — so it asks
    The scheduler's endpoint, over HTTP, every time. Overridable for tests.
    """
    from .notify.state import ApiReader

    return ApiReader(settings)


def loopback_reader(app: Any) -> Any:
    """A rounds reader that asks ``app`` itself, with no socket.

    For tests and the contract suite: the same HTTP request the deployment
    makes to ``MOH_API_URL``, carried by an ASGI transport into the app under
    test, so the Lunette is checked against the scheduler's real round rather than a copy.
    """
    import httpx

    from .notify.state import ApiReader

    def build(settings: HubSettings = Settings) -> Any:
        reader = ApiReader(settings)
        reader._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=settings.api_url
        )
        return reader

    return build


Reader = Depends(rounds_reader)


@router.get("/lunette")
async def lunette(
    settings: HubSettings = Settings, reader: Any = Reader
) -> dict[str, Any]:
    """Today's rounds for the e-ink panel. Frost first, hedges on the line.

    A round that cannot be read is a feed that says so — never an empty one,
    which a panel would draw as a quiet day.
    """
    import logging
    from datetime import UTC, datetime

    from .health import redact
    from .lunette import build_feed

    secrets = office.secrets_of(settings)
    try:
        rounds = await reader.rounds()
    except Exception as exc:  # noqa: BLE001 - the panel says so; the log says why
        logging.getLogger(__name__).warning(
            "lunette: could not read the round: %s", redact(str(exc), secrets)
        )
        rounds = None
    finally:
        close = getattr(reader, "aclose", None)
        if close is not None:
            await close()
    return build_feed(rounds, now=datetime.now(UTC), tz=settings.tz, secrets=secrets)
