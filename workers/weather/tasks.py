"""Weather & environment worker — the weather engine.

The water balance and the frost guard live here, as pure functions over
explicit inputs, with ingest and persistence outside them. That is what makes
``tests/engines/`` possible: the scenario fixtures are replayed through these
functions directly, with no database, no clock and no network.

## What this engine is, and what that costs

the design settled that there is no soil-moisture hardware and none is planned
for v1. So for every outdoor plant, **this file is the only thing that decides
whether it needs water.** Nothing measures the soil; nothing downstream will
notice if the answer is wrong. Two consequences run through everything below:

1. **Failing closed is the failure mode to design against.** If ET₀ stops
   arriving, the deficit stops growing, every plant reads as comfortable, and
   the app goes quiet — which is indistinguishable from a garden that does not
   need anything. the design fallback exists for exactly this, and where even
   that cannot run the day is reported as missing rather than as zero.
2. **Degraded inputs must reach the reader as degraded confidence.** Several
   coefficients are category defaults — published, cited, and
   still not a measurement of this plant. A category default that arrives as
   ``0.85`` and leaves as "water in two days" has been laundered on the way
   through. ``quality.py`` carries the reasons out with the number.

The equation itself, from the plan and the design:

    D(t) = clamp( D(t-1) + K_c·ET₀ − f_cover·P − I, 0, D_max )

It is written once, in :func:`step_deficit`, and nowhere else — not in the API,
not in the mocks. ``f_cover`` is 0 under a porch roof and 1 under open sky, and
it is the single most commonly got-wrong part of the model.

Indoor plants do not use this engine at all; they use interval rules adjusted
by season and indoor humidity, which belong to the scheduler.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from workers.runtime import ArqBootstrap

from .et0 import Et0Day, resolve_et0
from .quality import (
    Assessment,
    Degradation,
    assess,
    et0_fallback,
    et0_missing,
    forecast_not_observed,
    ingest_stale,
    k_c_category_default,
    k_c_uncited,
    secondary_source,
    weakest,
)

#: Fraction of a container's water-holding capacity that may be lost before a
#: watering is due. Containers reach it far sooner than open ground.
THRESHOLD_FRACTION = 0.6

#: Frost margin. The plan specifies 3 °F of headroom over the species minimum.
FROST_MARGIN_C = 3.0 * 5.0 / 9.0

#: Nights above the threshold before a plant that was carried in is suggested
#: back out, counted after the last frost night.
RETURN_OUTDOORS_NIGHTS = 3


@dataclass(frozen=True, slots=True)
class BalanceInputs:
    """One day of inputs to the soil water balance."""

    et0_mm: float
    precip_mm: float
    irrigation_mm: float = 0.0
    #: 0 for a covered spot the rain never reaches, 1 for open sky.
    cover_factor: float = 1.0


def step_deficit(
    previous_mm: float, inputs: BalanceInputs, k_c: float, capacity_mm: float
) -> float:
    """Advance the soil water deficit by one day.

    ``D(t) = clamp(D(t-1) + K_c·ET₀ − f_cover·P − I, 0, D_max)`` — the plan's
    water-balance equation, and the only place it is written down in code.
    """
    deficit = (
        previous_mm
        + k_c * inputs.et0_mm
        - inputs.cover_factor * inputs.precip_mm
        - inputs.irrigation_mm
    )
    return max(0.0, min(capacity_mm, deficit))


def capacity_mm(in_container: bool, container_litres: float | None) -> float:
    """Plant-available water the root zone holds, in millimetres of deficit.

    A container runs dry quickly; open ground draws on a much deeper profile.
    The container figure scales with pot volume and saturates, because a bigger
    pot buys less than proportionally more buffer once roots fill it.
    """
    if not in_container:
        return 60.0
    litres = container_litres or 10.0
    return min(40.0, 8.0 + 0.55 * litres)


def is_watering_due(deficit_mm: float, capacity: float) -> bool:
    return deficit_mm >= capacity * THRESHOLD_FRACTION


def frost_threshold_c(species_min_temp_c: float) -> float:
    """The temperature at which we act, not the one at which the plant dies."""
    return species_min_temp_c + FROST_MARGIN_C


def needs_frost_action(
    forecast_low_c: float, species_min_temp_c: float, *, is_outdoor: bool
) -> bool:
    if not is_outdoor:
        return False
    return forecast_low_c <= frost_threshold_c(species_min_temp_c)


def frost_action(*, in_container: bool) -> str:
    """Containers come inside; anything in the ground gets covered instead."""
    return "bring_indoors" if in_container else "cover"


# --------------------------------------------------------------------------
# The water balance, run over a series
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WaterCoefficient:
    """``K_c`` and what it is actually worth.

    A coefficient arrives from the botany worker in one of three conditions, and the
    difference has to survive the trip through the engine:

    * **measured for this species**, cited — full confidence;
    * **a published category default** — cited to a table (FAO-56, WUCOLS) at
      *category* scope, capped at ``medium``, and never presented as a
      measurement of this plant;
    * **uncited** — a number with no source, which the design requires be marked
      ``unknown`` and visibly flagged. The balance still computes, because a
      plant with no coefficient still needs deciding about; it simply does not
      pretend to know.
    """

    value: float | None
    confidence: str = "unknown"
    source: str | None = None
    category: str | None = None
    is_category_default: bool = False

    #: Used only when there is no coefficient at all. Not a fact about any
    #: plant — a placeholder that keeps the arithmetic defined, and every
    #: answer resting on it is reported ``unknown``.
    FALLBACK: ClassVar[float] = 0.6

    @property
    def effective(self) -> float:
        return self.FALLBACK if self.value is None else self.value

    @classmethod
    def from_care_value(
        cls, care_value: dict[str, Any] | None, source: dict[str, Any] | None = None
    ) -> WaterCoefficient:
        """Read one ``care_value`` row for ``water_k_c``.

        ``scope`` on the source, or a ``category`` on the note, is what marks a
        category default. The botany worker writes those; until it
        does, a cited value simply reads as species-level, which is the older
        and more generous reading — so this is re-checked when D lands.

        **A ``source_id`` that resolves to nothing is not a citation.** This used
        to fall back to the raw id when the source row could not be found, which
        put a uuid in ``k_c_source`` — a reader shown a uuid where a title
        belongs, the defect the design fixed one layer out — and, worse, made
        the value read as *cited* so it kept whatever confidence it claimed.
        The no-invented-plant-facts rule is the other way round: a value nobody can be shown the
        source of
        is ``unknown`` and visibly marked. A user override is the stated
        exception (``CareValue``'s own description, and contract 1.4.0 made the
        unsourced state sayable at last): the household attesting to a number is
        a citation of a different kind, not an absent one.
        """
        if not care_value:
            return cls(value=None, confidence="unknown")
        scope = str((source or {}).get("scope") or care_value.get("scope") or "")
        category = care_value.get("category") or (source or {}).get("category")
        is_default = scope == "category" or bool(category)
        confidence = str(care_value.get("confidence") or "unknown")
        if is_default:
            # the design caps a category default at medium, never high.
            confidence = weakest(confidence, "medium")
        title = (source or {}).get("title")
        if not title and not care_value.get("is_user_override"):
            confidence = "unknown"
        return cls(
            value=_as_float(care_value.get("value")),
            confidence=confidence,
            source=str(title) if title else None,
            category=str(category) if category else None,
            is_category_default=is_default,
        )

    def degradations(self) -> list[Degradation]:
        if self.value is None or self.source is None or self.confidence == "unknown":
            return [k_c_uncited()]
        if self.is_category_default:
            return [k_c_category_default(self.category, self.source)]
        return []


@dataclass(frozen=True, slots=True)
class DayWeather:
    """One day of weather for one site, as the balance needs it."""

    day: date
    precip_mm: float = 0.0
    et0_mm: float | None = None
    tmin_c: float | None = None
    tmax_c: float | None = None
    #: True while this day is still a forecast. Rain that has not fallen has
    #: not watered anything, and the series says which days those are.
    is_forecast: bool = False
    source: str = "open_meteo"


@dataclass(frozen=True, slots=True)
class BalanceDay:
    """One day of the balance, with the provenance of the day's inputs."""

    day: date
    deficit_mm: float
    et0: Et0Day
    demand_mm: float
    precip_mm: float
    gross_precip_mm: float
    irrigation_mm: float
    cover_factor: float
    is_due: bool
    status: str
    satisfied_by: str | None
    is_forecast: bool

    def to_dict(self) -> dict[str, Any]:
        """The shape ``/almanac/water-balance`` publishes per day."""
        return {
            "day": self.day.isoformat(),
            "deficit_mm": round(self.deficit_mm, 2),
            # ``et0_mm`` is the demand the plant actually made on the soil —
            # K_c·ET₀, which is the term in the equation. The reference figure
            # and how it was arrived at travel beside it rather than instead.
            "et0_mm": round(self.demand_mm, 2),
            "reference_et0_mm": None if self.et0.mm is None else round(self.et0.mm, 2),
            "et0_method": self.et0.method,
            "precip_mm": round(self.precip_mm, 2),
            "gross_precip_mm": round(self.gross_precip_mm, 2),
            "irrigation_mm": round(self.irrigation_mm, 2),
            "is_forecast": self.is_forecast,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class BalanceSeries:
    """A replayed balance: every day, the state it ended in, and its confidence."""

    days: tuple[BalanceDay, ...]
    deficit_mm: float
    capacity_mm: float
    threshold_mm: float
    k_c: WaterCoefficient
    cover_factor: float
    sensor_override_pct: float | None
    assessment: Assessment

    @property
    def is_due(self) -> bool:
        if self.sensor_override_pct is not None:
            # A probe outranks the model. No hardware drives this
            # today; the seam is kept honest by the scenario suite.
            return self.sensor_override_pct < 30.0
        return is_watering_due(self.deficit_mm, self.capacity_mm)

    @property
    def status(self) -> str:
        return self.days[-1].status if self.days else "ok"

    @property
    def satisfied_by(self) -> str | None:
        return self.days[-1].satisfied_by if self.days else None


def run_balance(
    weather: Sequence[DayWeather],
    *,
    k_c: WaterCoefficient,
    capacity: float,
    cover_factor: float,
    latitude: float,
    irrigation: dict[date, float] | None = None,
    starting_deficit: float = 0.0,
    sensor_override_pct: float | None = None,
    stale_hours: float | None = None,
) -> BalanceSeries:
    """Replay the water balance over a series of days, carrying provenance.

    The arithmetic is :func:`step_deficit` and nothing else. What this adds is
    the bookkeeping that keeps the answer honest:

    * ET₀ is resolved per day — ingested, else Hargreaves from
      the day's min and max, else missing;
    * **a missing day does not advance the deficit**, and is counted. A deficit
      that stopped growing because a number went missing reads lower than the
      plant's real one, so the series says how many days it skipped;
    * a day that was due and is no longer, because rain fell, is marked
      ``satisfied`` rather than dropped. The user needs to see that the sky did
      their job.
    """
    irrigation = irrigation or {}
    coefficient = k_c.effective

    rows: list[BalanceDay] = []
    deficit = starting_deficit
    fallback_days = 0
    missing_days = 0
    forecast_days = 0
    secondary_days = 0

    for entry in weather:
        et0 = resolve_et0(
            entry.day,
            ingested_mm=entry.et0_mm,
            tmin_c=entry.tmin_c,
            tmax_c=entry.tmax_c,
            latitude_deg=latitude,
            source=entry.source,
        )
        if et0.is_fallback:
            fallback_days += 1
        if et0.is_missing:
            missing_days += 1
        if entry.is_forecast:
            forecast_days += 1
        if entry.source != "open_meteo":
            secondary_days += 1

        applied = irrigation.get(entry.day, 0.0)
        was_due = is_watering_due(deficit, capacity)
        demand = coefficient * (et0.mm or 0.0)
        deficit = step_deficit(
            deficit,
            BalanceInputs(
                et0_mm=et0.mm or 0.0,
                precip_mm=entry.precip_mm,
                irrigation_mm=applied,
                cover_factor=cover_factor,
            ),
            coefficient,
            capacity,
        )
        effective_rain = cover_factor * entry.precip_mm
        now_due = is_watering_due(deficit, capacity)
        status, satisfied_by = day_status(
            was_due=was_due,
            now_due=now_due,
            rain_mm=effective_rain,
            irrigation_mm=applied,
        )
        rows.append(
            BalanceDay(
                day=entry.day,
                deficit_mm=deficit,
                et0=et0,
                demand_mm=demand,
                precip_mm=effective_rain,
                gross_precip_mm=entry.precip_mm,
                irrigation_mm=applied,
                cover_factor=cover_factor,
                is_due=now_due,
                status=status,
                satisfied_by=satisfied_by,
                is_forecast=entry.is_forecast,
            )
        )

    degradations = list(k_c.degradations())
    if fallback_days:
        degradations.append(et0_fallback(fallback_days))
    if missing_days:
        degradations.append(et0_missing(missing_days))
    if forecast_days:
        degradations.append(forecast_not_observed(forecast_days))
    if secondary_days:
        degradations.append(secondary_source("nws"))
    if stale_hours is not None and stale_hours > 0:
        degradations.append(ingest_stale(stale_hours))

    return BalanceSeries(
        days=tuple(rows),
        deficit_mm=deficit,
        capacity_mm=capacity,
        threshold_mm=capacity * THRESHOLD_FRACTION,
        k_c=k_c,
        cover_factor=cover_factor,
        sensor_override_pct=sensor_override_pct,
        # A modelled deficit is never better than ``medium`` on its own: it is
        # a calculation about soil nobody has measured. ``high`` is
        # reserved for a figure something actually observed.
        assessment=assess(degradations, base=weakest("medium", k_c.confidence)),
    )


def day_status(
    *, was_due: bool, now_due: bool, rain_mm: float, irrigation_mm: float
) -> tuple[str, str | None]:
    """What today's row says happened, in the plan's vocabulary.

    "Satisfied" is not "no longer due". It is the specific, visible state of a
    watering that *was* owed and that the weather settled — the plan is explicit
    that the task must not simply vanish.

    Public because the live Almanac path replays it over stored
    ``water_balance`` rows: the table keeps no ``status`` column, so the one
    rule that decides "satisfied" has to be reachable from there rather than
    written a second time.

    ``rain_mm`` is rain that reached the soil — already multiplied by the
    cover factor. Passing gross rainfall here waters a plant under a roof.
    """
    if now_due:
        return "due", None
    if was_due and (rain_mm > 0.0 or irrigation_mm > 0.0):
        return "satisfied", "rain" if rain_mm >= irrigation_mm else "irrigation"
    return "ok", None


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# The frost guard
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrostNight:
    """One forecast night: the date it is the night *of*, and its low."""

    day: date
    low_c: float


@dataclass(frozen=True, slots=True)
class FrostSubject:
    """What the frost guard needs to know about one plant."""

    specimen_id: str
    is_outdoor: bool
    in_container: bool
    min_temp_c: float | None
    min_temp_confidence: str = "unknown"
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class FrostAlert:
    """One night, one plant, one thing to do about it."""

    specimen_id: str
    night_of: date
    forecast_low_c: float
    threshold_c: float
    action: str
    advisory: str | None
    assessment: Assessment

    def to_dict(self) -> dict[str, Any]:
        return {
            "specimen_id": self.specimen_id,
            "night_of": self.night_of.isoformat(),
            "forecast_low_c": round(self.forecast_low_c, 1),
            "threshold_c": round(self.threshold_c, 2),
            "action": self.action,
            "advisory": self.advisory,
            **self.assessment.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FrostReport:
    """The alerts, and the plants that could not be assessed at all.

    The second list is the point. A species with no minimum temperature cannot
    be reasoned about, and leaving it silently out of the alerts would make an
    unanswerable question look like a reassuring answer — the same failure the
    water balance guards against, in the engine where the plant dies overnight.
    """

    alerts: tuple[FrostAlert, ...] = ()
    unassessable: tuple[tuple[str, str], ...] = ()

    def for_specimen(self, specimen_id: str) -> FrostAlert | None:
        return next((a for a in self.alerts if a.specimen_id == specimen_id), None)


def frost_alerts(
    nights: Sequence[FrostNight],
    subjects: Sequence[FrostSubject],
    *,
    advisories: Sequence[Any] = (),
    lookahead_hours: int = 72,
    today: date | None = None,
) -> FrostReport:
    """The first night within the lookahead that each plant needs protecting.

    One alert per plant, not one per cold night: three warnings for one cold
    snap is how people learn to swipe them away. The action follows the plan —
    a container comes indoors, anything in the ground gets covered. You cannot
    carry a hedge inside.

    A hardy plant gets nothing at all. A false frost alert on a lavender is not
    a harmless extra; it is what teaches someone to ignore the real one on a
    lemon.

    **On NWS advisories.** The plan names an advisory covering the site as a
    second trigger. It is carried on the alert, and it extends the lookahead to
    the end of the advisory's window — but it does not on its own raise an alert
    for a plant whose own threshold the forecast never crosses. The contract
    test ``test_a_frost_alert_reports_the_night_it_actually_names`` requires
    every alert's stated low to sit at or below its own stated threshold, and an
    advisory-only alert would state a low above it. Reconciling the two is a
    question for the maintainers, and it is raised in the earlier pull request rather than settled
    here.
    """
    if not nights:
        return FrostReport()

    start = today or nights[0].day
    horizon = start + timedelta(hours=lookahead_hours)
    horizon = max(horizon, _advisory_horizon(advisories, horizon))
    in_window = [night for night in nights if start <= night.day <= horizon]

    alerts: list[FrostAlert] = []
    unassessable: list[tuple[str, str]] = []

    for subject in subjects:
        if not subject.is_outdoor:
            continue  # indoor plants are never frost-alerted
        if subject.min_temp_c is None:
            reason = (
                "no minimum temperature is recorded for this species, so its "
                "frost risk cannot be judged"
            )
            unassessable.append((subject.specimen_id, reason))
            continue

        threshold = frost_threshold_c(subject.min_temp_c)
        night = next((n for n in in_window if n.low_c <= threshold), None)
        if night is None:
            continue

        advisory = _advisory_covering(advisories, night.day)
        degradations: list[Degradation] = []
        if subject.min_temp_confidence in {"low", "unknown"}:
            degradations.append(
                Degradation(
                    code="min_temp_uncited",
                    detail=(
                        "The species minimum temperature this alert is measured "
                        "against carries no reliable citation."
                    ),
                    caps_at="low",
                )
            )
        alerts.append(
            FrostAlert(
                specimen_id=subject.specimen_id,
                night_of=night.day,
                forecast_low_c=night.low_c,
                threshold_c=threshold,
                action=frost_action(in_container=subject.in_container),
                advisory=advisory,
                # A forecast three nights out is not a measurement, and an
                # advisory from the NWS is corroboration worth saying so about.
                assessment=assess(degradations, base="high" if advisory else "medium"),
            )
        )

    return FrostReport(alerts=tuple(alerts), unassessable=tuple(unassessable))


def return_outdoors_day(
    nights: Sequence[FrostNight],
    threshold_c: float,
    *,
    consecutive: int = RETURN_OUTDOORS_NIGHTS,
) -> date | None:
    """When a plant carried indoors may go back out.

    Three consecutive nights above the threshold, counted **after** the last
    night that fell below it — not the first three mild nights in the series,
    which would send a lemon back out the evening before the freeze.
    """
    below = [index for index, night in enumerate(nights) if night.low_c <= threshold_c]
    if not below:
        return None
    run = 0
    for night in nights[max(below) + 1 :]:
        run = run + 1 if night.low_c > threshold_c else 0
        if run == consecutive:
            return night.day
    return None


def _advisory_horizon(advisories: Sequence[Any], default: date) -> date:
    ends = [
        getattr(advisory, "expires", None)
        for advisory in advisories
        if getattr(advisory, "is_frost", False)
    ]
    dates = [end.date() for end in ends if isinstance(end, datetime)]
    return max([default, *dates]) if dates else default


def _advisory_covering(advisories: Sequence[Any], day: date) -> str | None:
    """The headline of a frost advisory in force on the night of ``day``.

    Checked at 06:00 UTC the following morning — roughly dawn at this
    longitude, and the hour a frost advisory is actually about. Checking at
    midnight would miss every advisory that runs "2 AM to 9 AM".
    """
    moment = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    moment = moment.replace(hour=6)
    for advisory in advisories:
        if getattr(advisory, "is_frost", False) and advisory.covers(moment):
            headline = getattr(advisory, "headline", None)
            return str(headline) if headline else str(advisory.event)
    return None


# --------------------------------------------------------------------------
# Arq jobs
# --------------------------------------------------------------------------
#
# Every job returns a plain dict rather than writing and staying silent, so a
# run's outcome is visible in Arq's result store and in a test without a
# database. Where ``ctx`` carries a ``connection``, rows are persisted through
# ``store``; where it does not — mock mode, and every test — the job still does
# the work and reports it. A job that can only be observed by querying Postgres
# is a job nobody checks.


async def ingest_forecast(ctx: dict, site_id: str | None = None) -> dict[str, Any]:
    """Pull the 10-day daily and 1-day hourly forecast into ``weather_forecast``."""
    from . import store, world

    ingest, site = _ingest_for(ctx, site_id)
    report = await ingest.forecast(site)
    connection = ctx.get("connection")
    if connection is not None and report.forecasts:
        await store.write_forecasts(connection, site.id, report.forecasts)
    _ = world  # imported for symmetry with the other jobs; see _ingest_for
    return report.to_dict()


async def ingest_observations(ctx: dict, site_id: str | None = None) -> dict[str, Any]:
    """Pull recent actuals into ``weather_obs``, and refresh the day's rollup.

    The exit criterion is readings stored every 5–15 minutes. Open-Meteo
    publishes hourly, so running this every ten minutes re-reads the same hours
    and replaces them as they firm up from modelled to measured — which is why
    the write replaces a window rather than appending to it (see ``store``).
    """
    from . import store

    ingest, site = _ingest_for(ctx, site_id)
    report = await ingest.observations(site)
    connection = ctx.get("connection")
    if connection is not None and report.observations:
        await store.write_observations(connection, site.id, report.observations)
        touched = sorted({row.time.date() for row in report.observations})
        await store.refresh_aggregates(connection, touched[0], touched[-1])
    return report.to_dict()


async def ingest_history(
    ctx: dict, site_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    """Backfill ``weather_obs`` from the archive, then refresh the rollups.

    Run once when a site is added and nightly after that. The scheduled
    continuous-aggregate policies would eventually cover the same ground, but
    "eventually" is an hour, and a new site with an empty Almanac for an hour
    looks broken rather than busy.
    """
    from . import store
    from .ingest import backfill_window

    ingest, site = _ingest_for(ctx, site_id)
    start, end = backfill_window(days)
    report = await ingest.history(site, start=start, end=end)
    connection = ctx.get("connection")
    if connection is not None and report.observations:
        await store.write_observations(connection, site.id, report.observations)
        await store.refresh_aggregates(connection, start, end)
    return report.to_dict() | {"window": [start.isoformat(), end.isoformat()]}


async def ingest_advisories(ctx: dict, site_id: str | None = None) -> dict[str, Any]:
    """Pull active NWS watches, warnings and advisories into ``weather_alert``."""
    from . import store

    ingest, site = _ingest_for(ctx, site_id)
    report = await ingest.advisories(site)
    connection = ctx.get("connection")
    if connection is not None and report.advisories:
        await store.write_advisories(connection, site.id, report.advisories)
    return report.to_dict() | {
        "frost_advisories": [a.event for a in report.advisories if a.is_frost]
    }


async def evaluate_water_balance(
    ctx: dict, day: date | str | None = None
) -> dict[str, Any]:
    """Advance every outdoor specimen's deficit and write ``water_balance``.

    Indoor specimens are skipped: they use interval rules, not this engine.
    """
    from . import store, world

    settings = ctx.get("settings")
    contexts = world.specimen_contexts(settings)
    weather = world.weather_days(settings)
    if day is not None:
        target = date.fromisoformat(day) if isinstance(day, str) else day
        weather = [entry for entry in weather if entry.day <= target]
    latitude = world.site(settings).latitude

    rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for context in contexts.values():
        if not context.is_outdoor:
            continue
        series = run_balance(
            weather,
            k_c=context.k_c,
            capacity=context.capacity_mm,
            cover_factor=context.cover_factor,
            latitude=latitude,
            sensor_override_pct=context.sensor_override_pct,
        )
        if series.days:
            last = series.days[-1]
            rows.append(
                # Including the confidence and the named reasons for it (design decision
                # 0020 §4). A stored deficit that cannot say what it was worth
                # is the same defect as an uncited care value, one table along.
                store.water_balance_row(
                    day=last.day,
                    specimen_id=context.specimen_id,
                    series=series,
                    last=last,
                    cover_factor=context.cover_factor,
                    sensor_override_pct=context.sensor_override_pct,
                )
            )
        summary.append(
            {
                "specimen_id": context.specimen_id,
                "deficit_mm": round(series.deficit_mm, 2),
                "is_due": series.is_due,
                "status": series.status,
                "confidence": series.assessment.confidence,
                "degradations": [d.code for d in series.assessment.degradations],
            }
        )

    connection = ctx.get("connection")
    if connection is not None and rows:
        await store.write_water_balance(connection, rows)

    return {
        "evaluated": len(summary),
        "due": sum(1 for row in summary if row["is_due"]),
        "satisfied": sum(1 for row in summary if row["status"] == "satisfied"),
        # Counted and returned rather than merely logged: "how many of today's
        # watering decisions rest on a degraded input" is the number that says
        # whether this engine is still worth trusting.
        "degraded": sum(1 for row in summary if row["degradations"]),
        "specimens": summary,
    }


async def evaluate_frost_guard(ctx: dict) -> dict[str, Any]:
    """The 72h lookahead, against the forecast and any NWS advisory."""
    from . import world

    settings = ctx.get("settings")
    contexts = world.specimen_contexts(settings)
    nights = world.frost_nights(settings)
    advisories = ctx.get("advisories") or world.scenario_advisories(settings)

    report = frost_alerts(
        nights,
        [context.frost_subject() for context in contexts.values()],
        advisories=advisories,
        lookahead_hours=(settings or _settings()).frost_lookahead_hours,
    )
    return {
        "alerts": [alert.to_dict() for alert in report.alerts],
        # Never dropped quietly: a plant whose risk cannot be judged is named.
        "unassessable": [
            {"specimen_id": specimen_id, "reason": reason}
            for specimen_id, reason in report.unassessable
        ],
    }


def _settings() -> Any:
    from .settings import get_settings

    return get_settings()


def _ingest_for(ctx: dict, site_id: str | None) -> tuple[Any, Any]:
    """The ingest and the site a job should work on.

    ``ctx`` may carry a prepared ``ingest`` (the API does, so one process keeps
    one HTTP client); otherwise one is built from the settings.
    """
    from . import world
    from .factory import get_ingest

    ingest = ctx.get("ingest") or get_ingest()
    site = ctx.get("site") or world.site(ctx.get("settings"))
    if site_id and site.id != site_id:
        site = replace(site, id=site_id)
    return ingest, site


class WorkerSettings(metaclass=ArqBootstrap):
    """Arq entrypoint.

    The schedules follow the releases's exit criterion — readings stored every
    5–15 minutes, forecast visible. Ten minutes for observations, hourly for
    the forecast, a quarter-hour for advisories because a Freeze Warning issued
    at 2 PM for that night is not something to learn about at 3.
    """

    functions: ClassVar[list] = [
        ingest_forecast,
        ingest_observations,
        ingest_history,
        ingest_advisories,
        evaluate_water_balance,
        evaluate_frost_guard,
    ]

    cron_jobs: ClassVar[list] = []


def _build_cron_jobs() -> list[Any]:
    """Built lazily so importing this module never requires Arq to be installed.

    The engines are imported by the API and by the scenario suite, neither of
    which runs jobs. A missing scheduler dependency must not take the water
    balance down with it.
    """
    try:
        from arq import cron
    except ImportError:  # pragma: no cover - arq is a declared dependency
        return []

    return [
        cron(ingest_observations, minute=set(range(0, 60, 10)), run_at_startup=True),
        cron(ingest_forecast, minute={3}, run_at_startup=True),
        cron(ingest_advisories, minute={7, 22, 37, 52}, run_at_startup=True),
        cron(ingest_history, hour={4}, minute={15}),
        # After the forecast and the observations have landed, not before.
        cron(evaluate_water_balance, hour={5}, minute={0}),
        cron(evaluate_frost_guard, minute={30}),
    ]


WorkerSettings.cron_jobs = _build_cron_jobs()
