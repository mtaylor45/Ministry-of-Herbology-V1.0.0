"""Forecast, conditions history, water balance and frost.

``contracts/openapi/openapi.yaml`` declares them — no route is added here that
the contract does not have.

The router is deliberately thin. Every decision lives in ``service.py``, and
every calculation lives below that in ``workers/weather/tasks.py``. The earlier mock
this replaces re-implemented the water-balance equation inline, which meant two
copies of the one equation the plan says is written once; the endpoint now runs
the same engine the worker and the scenario suite run.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import service

router = APIRouter(prefix="/almanac", tags=["almanac"])


@router.get("/forecast")
async def get_forecast(
    site_id: str, horizon: str = Query("daily", pattern="^(hourly|daily)$")
) -> list[dict[str, Any]]:
    """1-day (hourly) and 10-day (daily) forecast."""
    return service.forecast(site_id, horizon)


@router.get("/history")
async def get_history(
    window: str = Query(..., pattern="^(1d|7d|30d)$"),
    site_id: str | None = None,
    location_id: str | None = None,
    specimen_id: str | None = None,
    metric: str = "temperature_c",
) -> dict[str, Any]:
    """1 / 7 / 30-day indoor and outdoor conditions history."""
    return service.history(
        window,
        metric,
        site_id=site_id,
        location_id=location_id,
        specimen_id=specimen_id,
    )


@router.get("/water-balance/{specimen_id}")
async def get_water_balance(specimen_id: str) -> dict[str, Any]:
    """Soil water deficit history and current state.

    The response carries its own confidence and the named reasons for it. Under
    the design nothing measures the soil, so this endpoint is the only thing that
    decides whether an outdoor plant is watered — and a degraded input has to
    leave here looking degraded rather than clean.
    """
    balance = service.water_balance(specimen_id)
    if balance is None:
        raise HTTPException(status_code=404, detail="No such specimen")
    return balance


@router.get("/frost")
async def list_frost_alerts() -> dict[str, Any]:
    """Open frost alerts within the 72h lookahead, and what could not be judged.

    An envelope rather than a bare list: a list of alerts cannot say
    "and these three I could not assess", and an unanswerable question must not
    reach the reader looking like a reassuring answer.
    """
    return {
        "alerts": service.frost(),
        "unassessable": service.unassessable_for_frost(),
    }
