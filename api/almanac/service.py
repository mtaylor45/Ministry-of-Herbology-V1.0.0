"""What the Almanac serves, and where it gets it — the weather engine.

The router is a thin translation of this module into the shapes
``contracts/openapi/openapi.yaml`` declares. Everything that decides anything
lives here, and everything that *computes* anything lives further down still,
in ``workers/weather/tasks.py``. The water-balance equation is written once,
there; this module must never grow a second copy of it, however convenient.

Two paths, one set of answers:

* **mock mode** reads ``fixtures/`` through
  ``workers.weather.world``, so the app's screens can build the Almanac screen and the scenario
  suite can run with no database and no network;
* **live mode** reads Postgres through ``workers.weather.store``, whose
  statements are built by pure functions and therefore tested without one.

The live path takes a connection as an argument rather than reaching for a
pool: connection management belongs to whoever owns the app's lifespan, and
inventing it inside one parts of the project's router is how two incompatible pools end
up in one process. Wiring it is noted for the maintainers and the deployment in the earlier pull
request.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from workers.weather import world
from workers.weather.quality import (
    Assessment,
    Degradation,
    assess,
    certainty_not_recorded,
    ingest_stale,
    weakest,
)
from workers.weather.settings import WeatherSettings
from workers.weather.settings import get_settings as weather_settings
from workers.weather.store import SITE_METRICS, WINDOW_DAYS
from workers.weather.tasks import (
    BalanceSeries,
    DayWeather,
    FrostNight,
    day_status,
    frost_alerts,
    run_balance,
)

from app import fixtures

#: How many days of the balance the endpoint *shows*. Long enough to see a
#: deficit building and rain clearing it; short enough to be one screen.
#:
#: **Not how many days it replays.** It was both until the test suite's drought story ran the
#: selector over a 21-day recording: a 14-day window restarts the deficit at zero
#: a fortnight ago, and an in-ground plant drawing on a 60 mm profile never gets
#: there. The lavender hedge read 34.02 mm — comfortable — where the weather says
#: 51.03 mm and the fixture says due by day 15. The worker replays the whole
#: recording and said `due`; the endpoint said `ok`; nothing compared them.
#:
#: A deficit is what the weather did, not what the last fortnight of it did, so
#: the replay now covers everything available and only the display is trimmed.
BALANCE_DAYS = 14

#: Namespace for deterministic alert ids. The contract types ``FrostAlert.id``
#: as a uuid, and an alert for the same plant on the same night must keep the
#: same one across restarts, or a dismissed alert comes back as a new one.
FROST_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

UNITS = {
    "temperature_c": "°C",
    "humidity_pct": "%",
    "soil_moisture_pct": "%",
    "precip_mm": "mm",
    "et0_mm": "mm",
}


# ------------------------------------------------------------------ forecast


def forecast(
    site_id: str, horizon: str, *, settings: WeatherSettings | None = None
) -> list[dict[str, Any]]:
    """The 10-day daily or 1-day hourly forecast, as ``ForecastPoint`` rows.

    In mock mode this is the baseline fixture put through the same Open-Meteo
    parser the live ingest uses, rather than a second hand-rolled shape — so a
    field the parser drops is a field the Almanac stops showing, and somebody
    finds out here rather than in production.

    Under a selected scenario (``MOH_SCENARIO``) it is that recording
    instead, starting at the day the operator is standing on: a forecast is the
    days ahead of now, and a deployment whose water balance has just been
    cleared by rain must not show a forecast from the week before it fell.
    """
    settings = settings or weather_settings()
    days = _rows_from(settings, _as_of(settings))
    if horizon == "daily":
        return [_daily_point(day) for day in days[:10]]
    return _hourly_points(days[0])


def _daily_point(day: dict[str, Any]) -> dict[str, Any]:
    stamp = f"{day['date']}T00:00:00Z"
    return {
        "time": stamp,
        "temp_min_c": day["tmin_c"],
        "temp_max_c": day["tmax_c"],
        "temperature_c": None,
        "precip_mm": day["precip_mm"],
        "precip_prob_pct": 80.0 if day["precip_mm"] else 10.0,
        "et0_mm": day["et0_mm"],
        "wind_kph": 12.0,
        "condition": day["condition"],
        # UTC, as everything is stored. At this site sunset falls after
        # midnight UTC, so it belongs to the next calendar day.
        "sunrise": f"{day['date']}T11:00:00Z",
        "sunset": f"{_next_day(day['date'])}T01:00:00Z",
    }


def _hourly_points(day: dict[str, Any]) -> list[dict[str, Any]]:
    """One day, hour by hour. Daily totals are preserved, not re-invented."""
    rain_hours = {14, 15, 16, 17}
    return [
        {
            "time": f"{day['date']}T{hour:02d}:00:00Z",
            "temperature_c": round(
                day["tmin_c"]
                + (day["tmax_c"] - day["tmin_c"])
                * max(0.0, (12 - abs(14 - hour)) / 12),
                1,
            ),
            "temp_min_c": None,
            "temp_max_c": None,
            "precip_mm": (
                round(day["precip_mm"] / len(rain_hours), 2)
                if hour in rain_hours
                else 0.0
            ),
            "precip_prob_pct": 80.0 if day["precip_mm"] else 10.0,
            "et0_mm": None,
            "wind_kph": 12.0,
            "condition": day["condition"],
            "sunrise": None,
            "sunset": None,
        }
        for hour in range(24)
    ]


# ------------------------------------------- which recording, and which day
#
# One reading of the setting, in ``workers.weather.world``, shared with the
# worker. These three are the thinnest possible wrapper over it, so that
# ``forecast``, ``history`` and ``water_balance`` all answer about the same
# week — and so that nothing in this package grows its own idea of "today".


def _as_of(settings: WeatherSettings) -> date | None:
    return world.as_of_day(settings)


def _rows_from(settings: WeatherSettings, day: date | None) -> list[dict[str, Any]]:
    """The recording from ``day`` onward — what is still ahead of the reader.

    Never empty: ``world.weather_rows`` refuses a day outside the recording, so
    the day itself is always one of these rows.
    """
    rows = world.weather_rows(settings)
    if day is None:
        return rows
    return [row for row in rows if date.fromisoformat(row["date"]) >= day]


def _rows_through(settings: WeatherSettings, day: date | None) -> list[dict[str, Any]]:
    """The recording up to and including ``day`` — what has already happened."""
    rows = world.weather_rows(settings)
    if day is None:
        return rows
    return [row for row in rows if date.fromisoformat(row["date"]) <= day]


# ------------------------------------------------------------------- history


def history(
    window: str,
    metric: str,
    *,
    site_id: str | None = None,
    location_id: str | None = None,
    specimen_id: str | None = None,
    settings: WeatherSettings | None = None,
) -> dict[str, Any]:
    """A bucketed series, column-oriented, ready to hand straight to uPlot.

    Daily buckets for every window, including ``1d``. In live mode these come
    from the ``weather_daily`` continuous aggregate rather than from raw
    ``weather_obs`` rows: the retention policy drops raw readings after 400
    days and the rollups carry the long history, so a query that scans the
    hypertable is both slower now and wrong later.
    """
    settings = settings or weather_settings()
    days = _rows_through(settings, _as_of(settings))[-WINDOW_DAYS[window] :]
    times: list[int] = []
    values: list[float | None] = []
    lows: list[float | None] = []
    highs: list[float | None] = []

    for day in days:
        moment = datetime.fromisoformat(day["date"]).replace(tzinfo=UTC)
        times.append(int(moment.timestamp()))
        if metric == "precip_mm":
            values.append(day["precip_mm"])
            lows.append(None)
            highs.append(None)
        elif metric == "et0_mm":
            values.append(day["et0_mm"])
            lows.append(None)
            highs.append(None)
        elif metric in {"humidity_pct", "soil_moisture_pct"}:
            # Neither is a site-weather metric: humidity indoors and soil
            # moisture both come from `reading`, which the hub fills and
            # which no deployment has yet. An empty series with the
            # right shape is the honest answer; a plausible curve would not be.
            values.append(None)
            lows.append(None)
            highs.append(None)
        else:
            values.append(round((day["tmin_c"] + day["tmax_c"]) / 2, 1))
            lows.append(day["tmin_c"])
            highs.append(day["tmax_c"])

    return {
        "metric": metric,
        "unit": UNITS.get(metric, ""),
        "times": times,
        "values": values,
        "min": lows,
        "max": highs,
        "label": f"{metric} · last {window}",
        "source": "weather_daily" if metric in SITE_METRICS else "reading_daily",
    }


# ------------------------------------------------------------- water balance


def water_balance(
    specimen_id: str,
    *,
    settings: WeatherSettings | None = None,
    irrigation: dict[date, float] | None = None,
) -> dict[str, Any] | None:
    """The deficit history and current state for one specimen.

    Returns ``None`` when there is no such specimen, so the router owns the
    404 and this stays a function about water.

    ``settings`` is an argument, defaulting to the process's own, so that the
    scenario a test or a demo is standing in can be stated rather than smuggled
    through a cached global — and so the worker's job and this endpoint can be
    handed the *same* object and shown to agree.

    ``irrigation`` is the plan's I(t) term: millimetres of deficit relieved per
    day by water somebody poured. :func:`run_balance` has accepted it
    and nothing ever passed one, so a logged watering changed nothing about the
    deficit. It is **passed in, never looked up**: the completion log is
    The scheduler's, and this module reading it would turn the scheduler → weather engine dependency
    into a cycle. The scheduler fills it in ``api/tending/environment.py``,
    which is the documented handoff, and owns the ml→mm conversion and the
    degradation that marks it as modelled.

    Widened by the scheduler under an explicit authorisation from the maintainers for the design —
    the signature and the forward below, and nothing else in this
    directory. The ownership rule otherwise: this file is the weather engine's.
    """
    specimen = fixtures.by_id(fixtures.specimens(), specimen_id)
    if not specimen:
        return None

    settings = settings or weather_settings()
    context = world.specimen_contexts(settings).get(specimen_id)
    if context is None:
        return None

    # Every day available, not the last ``BALANCE_DAYS`` — see that constant.
    series = run_balance(
        world.weather_days(settings),
        k_c=context.k_c,
        capacity=context.capacity_mm,
        cover_factor=context.cover_factor,
        latitude=world.site(settings).latitude,
        sensor_override_pct=context.sensor_override_pct,
        irrigation=irrigation,
    )
    return serialise_balance(
        specimen_id, series, is_outdoor=context.is_outdoor, show_days=BALANCE_DAYS
    )


def serialise_balance(
    specimen_id: str,
    series: BalanceSeries,
    *,
    is_outdoor: bool = True,
    show_days: int | None = None,
) -> dict[str, Any]:
    """``WaterBalance``, plus the honesty the frozen schema does not yet carry.

    The extra keys — ``confidence``, ``degraded``, ``degradations``, and
    ``et0_method`` on each day — are additive, so existing clients are
    unaffected. They are not optional decoration: this endpoint
    is the only thing that decides whether an outdoor plant gets watered, and a
    number returned without them is a degraded answer wearing a clean one's
    clothes. Adding them to ``WaterBalance`` in the contract is requested of A
    in the earlier pull request.

    ``show_days`` trims the per-day array for the screen. It trims *only* that:
    ``deficit_mm``, ``status`` and the assessment all come from the full replay,
    because they are facts about the whole series. Trimming the replay instead
    is the bug :data:`BALANCE_DAYS` now documents.
    """
    shown = series.days if show_days is None else series.days[-show_days:]
    payload: dict[str, Any] = {
        "specimen_id": specimen_id,
        "deficit_mm": round(series.deficit_mm, 2),
        "capacity_mm": round(series.capacity_mm, 2),
        "threshold_mm": round(series.threshold_mm, 2),
        "k_c": series.k_c.effective,
        "is_due": series.is_due,
        "sensor_override_pct": series.sensor_override_pct,
        "days": [day.to_dict() for day in shown],
        "status": series.status,
        "satisfied_by": series.satisfied_by,
        "cover_factor": series.cover_factor,
        "k_c_confidence": series.k_c.confidence,
        "k_c_source": series.k_c.source,
        "k_c_is_category_default": series.k_c.is_category_default,
        **series.assessment.to_dict(),
    }
    if not is_outdoor:
        # Indoor plants do not use this engine at all; they use interval rules
        # adjusted by season and indoor humidity. Answering with
        # a deficit and no warning would be inventing a fact about a pot in a
        # study where no rain falls and no ET₀ applies.
        payload["applies"] = False
        payload["note"] = (
            "Indoor specimens are watered on an interval rule, not on the "
            "outdoor water balance. This deficit is shown for reference only."
        )
    else:
        payload["applies"] = True
    return payload


# --------------------------------------------------------------------- frost


def frost(*, settings: WeatherSettings | None = None) -> list[dict[str, Any]]:
    """Open frost alerts within the 72h lookahead.

    Computed from the forecast by the engine, not read back out of the
    scenario's own ``expect`` block. A mock that replays the assertions proves
    only that the fixture can be parsed; this one fails when the engine is
    wrong, which is the entire purpose of having it.

    The ``SpecimenBrief`` is built from the context the alert was raised from
    rather than from a second lookup in ``fixtures``. The previous version
    dropped an alert whose specimen row it could not find, which
    means a plant freezes because a *name* could not be resolved.
    """
    settings = settings or weather_settings()
    contexts = world.specimen_contexts(settings)
    report = frost_alerts(
        world.frost_nights(settings),
        [context.frost_subject() for context in contexts.values()],
        advisories=world.scenario_advisories(settings),
        lookahead_hours=settings.frost_lookahead_hours,
    )

    out: list[dict[str, Any]] = []
    for alert in report.alerts:
        out.append(
            {
                "id": str(
                    uuid.uuid5(FROST_NAMESPACE, f"{alert.specimen_id}:{alert.night_of}")
                ),
                "specimen": _brief_from_context(
                    alert.specimen_id, contexts.get(alert.specimen_id)
                ),
                "night_of": alert.night_of.isoformat(),
                "forecast_low_c": round(alert.forecast_low_c, 1),
                "threshold_c": round(alert.threshold_c, 2),
                "action": alert.action,
                "advisory": alert.advisory,
                "task_id": None,
                "state": "open",
                **alert.assessment.to_dict(),
            }
        )
    return out


def unassessable_for_frost(
    *, settings: WeatherSettings | None = None
) -> list[dict[str, Any]]:
    """Plants whose frost risk cannot be judged, with the reason.

    Served as the ``unassessable`` half of ``/almanac/frost`` since the design
    gave that response an envelope. A plant is never dropped silently: if the
    engine cannot judge it, it is named here with the reason it could not.

    And *named*: ``specimen`` carries the ``SpecimenBrief`` contract 1.4.0 added, because a panel
    whose entire purpose is to name the plants
    nobody could judge, and which printed a uuid instead, had degraded into the
    thing it was built to prevent. ``specimen_id`` stays beside it until 1.5.0
    retires it.

    The brief is built from the :class:`world.SpecimenContext` that produced the
    verdict, not from a second lookup in ``fixtures``. A plant that could not be
    assessed must not then fail to appear because the lookup for its name missed
    — that would be the same hole one layer further out.
    """
    settings = settings or weather_settings()
    contexts = world.specimen_contexts(settings)
    report = frost_alerts(
        world.frost_nights(settings),
        [context.frost_subject() for context in contexts.values()],
        advisories=world.scenario_advisories(settings),
        lookahead_hours=settings.frost_lookahead_hours,
    )
    return [
        {
            "specimen_id": specimen_id,
            "specimen": _brief_from_context(specimen_id, contexts.get(specimen_id)),
            "reason": reason,
        }
        for specimen_id, reason in report.unassessable
    ]


def _brief_from_context(
    specimen_id: str, context: world.SpecimenContext | None
) -> dict[str, Any]:
    """``SpecimenBrief`` from what the engine already knew about the plant.

    ``display_name`` is required by the contract and must not be empty: the
    whole point of the field is that a reader sees a plant rather than a uuid.
    ``thumb_url`` is always ``None`` here — photos are the inventory API's and this
    module does not query them.
    """
    return {
        "id": specimen_id,
        "display_name": (
            context.display_name
            if context and context.display_name
            else "Unnamed specimen"
        ),
        "is_outdoor": bool(context.is_outdoor) if context else True,
        "thumb_url": None,
    }


# ------------------------------------------------------------------ live path


async def live_history(
    connection: Any,
    window: str,
    metric: str,
    *,
    site_id: str,
    today: date | None = None,
) -> dict[str, Any]:
    """The same series, read from the continuous aggregate.

    Kept beside the mock so the two cannot drift into different shapes without
    somebody editing this file and noticing.
    """
    from workers.weather.store import daily_weather_sql

    end = (today or datetime.now(UTC).date()) + timedelta(days=1)
    start = end - timedelta(days=WINDOW_DAYS[window])
    sql, params = daily_weather_sql(site_id, start, end)
    rows = await connection.fetch(sql, *params)

    column = SITE_METRICS.get(metric, "avg_temp_c")
    times = [
        int(
            datetime.combine(row["bucket"], datetime.min.time(), tzinfo=UTC).timestamp()
        )
        for row in rows
    ]
    return {
        "metric": metric,
        "unit": UNITS.get(metric, ""),
        "times": times,
        "values": [row[column] for row in rows],
        "min": [
            row["min_temp_c"] if metric == "temperature_c" else None for row in rows
        ],
        "max": [
            row["max_temp_c"] if metric == "temperature_c" else None for row in rows
        ],
        "label": f"{metric} · last {window}",
        "source": "weather_daily",
    }


def staleness_hours(newest: datetime | None, *, now: datetime | None = None) -> float:
    """How far behind the ingest is. ``None`` has never ingested at all.

    A site with no observations is not fresh; it is maximally stale, and
    returning 0 for it would be the exact failure the design was written about.
    """
    moment = now or datetime.now(UTC)
    if newest is None:
        return float("inf")
    return max(0.0, (moment - newest).total_seconds() / 3600.0)


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def frost_nights_from_forecast(rows: list[dict[str, Any]]) -> list[FrostNight]:
    """``weather_forecast`` daily rows to the nights the frost guard reads."""
    nights: list[FrostNight] = []
    for row in rows:
        low = row.get("temp_min_c")
        moment = row.get("time")
        if low is None or not isinstance(moment, datetime):
            continue
        nights.append(FrostNight(day=moment.date(), low_c=float(low)))
    return nights


def day_weather_from_rows(rows: list[dict[str, Any]]) -> list[DayWeather]:
    """``weather_daily`` rollup rows to the balance engine's daily inputs."""
    return [
        DayWeather(
            day=(
                row["bucket"]
                if isinstance(row["bucket"], date)
                else row["bucket"].date()
            ),
            precip_mm=float(row.get("precip_mm") or 0.0),
            et0_mm=row.get("et0_mm"),
            tmin_c=row.get("min_temp_c"),
            tmax_c=row.get("max_temp_c"),
        )
        for row in rows
    ]


# --------------------------------------------- the live water balance
#
# the design put `confidence`, `degraded` and `degradations` on this endpoint's
# *response*; migration 004 gave `water_balance` somewhere to keep them, and
# writing them is the weather engine's (the design says so explicitly). `workers/weather/store.py`
# now does. This is the other half: a read that hands back what was written,
# so a deployment on Postgres answers with the same doubt as a deployment on
# fixtures instead of the flat `medium` a bare number could support.
#
# What the table still cannot carry is named rather than guessed at. It keeps
# no `status`, no `satisfied_by`, no `et0_method` and no forecast flag, so:
#
#   * `status` and `satisfied_by` are replayed from consecutive stored rows
#     through `tasks.day_status` — the same rule the engine ran, not a second
#     copy of it — which recovers them exactly for any day whose predecessor is
#     also stored, and reports the first day of the window as `ok`/`due` only;
#   * `et0_method`, `reference_et0_mm`, `gross_precip_mm` and `is_forecast` are
#     *omitted* per day rather than filled in with a plausible value. None is
#     required by the contract, and a `hargreaves` that nobody recorded is an
#     invented fact about how a number was arrived at.
#
# Columns for those are a contract change and therefore the maintainers'; it is raised in
# the pull request rather than worked around here.


def balance_from_rows(
    specimen_id: str,
    rows: Sequence[Any],
    *,
    is_outdoor: bool = True,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Stored ``water_balance`` rows as the contract's ``WaterBalance``.

    Pure, and takes rows rather than a connection, for the reason the rest of
    this module gives: the interesting part is the certainty arithmetic, and it
    should be testable without a database.
    """
    ordered = [row for row in rows if row is not None]
    if not ordered:
        return None
    latest = ordered[-1]

    days: list[dict[str, Any]] = []
    previous: Any = None
    for row in ordered:
        deficit = float(_field(row, "deficit_mm") or 0.0)
        threshold = float(_field(row, "threshold_mm") or 0.0)
        rain = float(_field(row, "precip_mm") or 0.0)
        irrigation = float(_field(row, "irrigation_mm") or 0.0)
        was_due = previous is not None and float(
            _field(previous, "deficit_mm") or 0.0
        ) >= float(_field(previous, "threshold_mm") or 0.0)
        status, satisfied_by = day_status(
            was_due=was_due,
            now_due=deficit >= threshold,
            # Already multiplied by the cover factor when it was written, so a
            # plant under a roof is not watered here by rain it never saw.
            rain_mm=rain,
            irrigation_mm=irrigation,
        )
        days.append(
            {
                "day": _day_of(row).isoformat(),
                "deficit_mm": round(deficit, 2),
                "et0_mm": round(float(_field(row, "et0_mm") or 0.0), 2),
                "precip_mm": round(rain, 2),
                "irrigation_mm": round(irrigation, 2),
                "status": status,
                "satisfied_by": satisfied_by,
            }
        )
        previous = row

    deficit = float(_field(latest, "deficit_mm") or 0.0)
    capacity = float(_field(latest, "capacity_mm") or 0.0)
    threshold = float(_field(latest, "threshold_mm") or 0.0)
    override = _field(latest, "sensor_override_pct")
    # A probe outranks the model. No hardware drives this today.
    is_due = float(override) < 30.0 if override is not None else deficit >= threshold

    assessment = stored_assessment(latest, today=today)
    payload: dict[str, Any] = {
        "specimen_id": specimen_id,
        "deficit_mm": round(deficit, 2),
        "capacity_mm": round(capacity, 2),
        "threshold_mm": round(threshold, 2),
        "k_c": _field(latest, "k_c"),
        "is_due": is_due,
        "sensor_override_pct": None if override is None else float(override),
        "days": days,
        "status": days[-1]["status"],
        "satisfied_by": days[-1]["satisfied_by"],
        "cover_factor": _field(latest, "cover_factor"),
        **assessment.to_dict(),
    }
    if not is_outdoor:
        payload["applies"] = False
        payload["note"] = (
            "Indoor specimens are watered on an interval rule, not on the "
            "outdoor water balance. This deficit is shown for reference only."
        )
    else:
        payload["applies"] = True
    return payload


def stored_assessment(row: Any, *, today: date | None = None) -> Assessment:
    """What a stored row says it was worth, plus what the row itself betrays.

    Two things are added to the recorded reasons rather than trusted from the
    column alone:

    * a row whose ``confidence`` is NULL predates the design or was written by
      something that skipped it. That is "it did not say", and it reads as
      ``unknown`` — never as ``medium``, which would be the laundering the design
      exists to stop;
    * a row older than today means the deficit has not advanced since it was
      computed, so the real figure is higher than the stored one. Under the design nothing else
      would ever notice.
    """
    recorded = _field(row, "confidence")
    degradations = [
        Degradation(
            code=str(entry.get("code") or "unknown"),
            detail=str(entry.get("detail") or ""),
            caps_at=str(entry.get("caps_at") or "medium"),
        )
        for entry in _degradations(_field(row, "degradations"))
    ]
    if not recorded:
        degradations.append(certainty_not_recorded())

    stale_days = (today - _day_of(row)).days if today is not None else 0
    if stale_days > 0:
        degradations.append(ingest_stale(stale_days * 24.0))

    # `base` is what the row claims for itself; the reasons above can only
    # lower it. Capped at `medium` on the way in as well: a modelled deficit is
    # a calculation about soil nobody has measured, and `high` is
    # reserved for a figure something actually observed. The engine that wrote
    # the row applies the same ceiling — this one is for rows it did not write.
    return assess(degradations, base=weakest("medium", str(recorded or "unknown")))


async def live_water_balance(
    connection: Any,
    specimen_id: str,
    *,
    is_outdoor: bool = True,
    today: date | None = None,
    days: int = BALANCE_DAYS,
) -> dict[str, Any] | None:
    """The same answer as :func:`water_balance`, read from Postgres.

    ``is_outdoor`` is passed in rather than looked up: the specimen belongs to
    The inventory API's tables and this module does not query them.
    """
    from workers.weather.store import water_balance_history_sql

    end = today or datetime.now(UTC).date()
    sql, params = water_balance_history_sql(specimen_id, end - timedelta(days=days - 1))
    rows = await connection.fetch(sql, *params)
    return balance_from_rows(specimen_id, rows, is_outdoor=is_outdoor, today=end)


def _field(row: Any, name: str) -> Any:
    """One column, whether the row is an asyncpg Record or a plain mapping."""
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return getattr(row, name, None)


def _day_of(row: Any) -> date:
    value = _field(row, "day")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _degradations(value: Any) -> list[dict[str, Any]]:
    """``degradations`` as asyncpg hands it back: json text, or already parsed."""
    if not value:
        return []
    if isinstance(value, str | bytes | bytearray):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [entry for entry in value if isinstance(entry, dict)]
