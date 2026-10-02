"""The one place this package asks the weather engine what the world is doing.

The plan's handoff is "weather engine → scheduler: daily deficit and frost flags feed task
generation". This module is that handoff and nothing else lives in it, so the
scheduling engine stays a pure function of its arguments and there is exactly
one import of somebody else's module to review.

Nothing here computes a deficit, an ET₀ figure or a rain total. the design made
The weather engine's answers carry their own confidence precisely so that a consumer could pass
it on; a second, quieter copy of the water-balance equation in this package
would be the failure the design warns about, built on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from tending.domain import Caveat, Environment, Outlook, weakest

#: **The invented number.** How much of a container's volume is water a plant
#: can actually get at — the fraction that turns "half a litre went in" into
#: millimetres of relieved deficit.
#:
#: A peat-based potting medium's plant-available water fraction is a real,
#: citable horticultural quantity. This repository has no citation for it:
#: ``fixtures/species/sources.json`` carries none, and 0.25 is a plausible
#: mid-range figure and nothing more. Under the no-invented-plant-facts rule that makes every
#: deficit
#: computed with it worth ``unknown``, which is what
#: :data:`IRRIGATION_UNCITED` says and what it caps the answer at.
#:
#: What replaces it: a cited available-water fraction for the growing medium —
#: ideally per medium, since bark, coir and peat differ — carried as a
#: ``source_id`` the way every other care value is. On the day that arrives,
#: this constant changes, the degradation below stops being emitted, and the
#: confidence ceiling lifts on its own. Nothing else moves.
AVAILABLE_WATER_FRACTION = 0.25

#: Why a deficit that counts a logged watering is worth ``unknown``, in words
#: written to be shown to a reader as they are. One code, because it is one
#: doubt — the ml→mm conversion — and four ways it bites: the term is in the
#: deficit and uncited, or it is omitted for want of a pot, for want of a
#: logged volume, or because the balance could not be worked out again.
IRRIGATION_UNCITED = "irrigation_uncited"

_MODELLED_DETAIL = (
    "This deficit counts a watering somebody logged. Turning millilitres "
    "poured into millimetres of soil needs to know how much of the pot's "
    "compost holds water the plant can actually reach, and that fraction is "
    "not cited anywhere in this app — so how deep this watering soaked is an "
    "estimate, not a measurement. That somebody watered the plant is recorded "
    "fact; only the depth is modelled, and nothing here has measured the soil."
)

_NO_POT_DETAIL = (
    "Somebody logged a watering for this plant and this deficit does not "
    "count it. The plant is not in a container, so there is no pot volume to "
    "turn millilitres into millimetres of soil with, and a made-up one would "
    "be a garden fact nobody attested. The deficit shown is therefore drier "
    "than the plant is. The watering is recorded and the job is done either "
    "way — only the model is missing it."
)

_NO_VOLUME_DETAIL = (
    "Somebody logged a watering for this plant without saying how much water "
    "went in, so this deficit does not count it and reads drier than the "
    "plant is. The job is recorded as done regardless. Logging the amount "
    "next time is what lets the model see it."
)

_NOT_COUNTED_DETAIL = (
    "Somebody logged a watering for this plant and this deficit does not "
    "count it: the water balance could not be worked out again with the "
    "watering in it, so the figure shown is the one from before and reads "
    "drier than the plant is. The job is recorded as done regardless."
)

_AFTER_THE_WEATHER_DETAIL = (
    " The watering also happened after the last day the weather records "
    "reach, so it is counted on that last day rather than on the day it "
    "happened."
)


def _uncited(detail: str) -> Caveat:
    """The one degradation, capped at ``unknown`` (a ceiling — the design)."""
    return Caveat(code=IRRIGATION_UNCITED, detail=detail, caps_at="unknown")


@dataclass(frozen=True, slots=True)
class Waterings:
    """What somebody actually did to one plant, and the pot it went into.

    The *fact* half of millilitres per day as they were logged, with
    no model in them anywhere. ``container_litres`` is a fact about the pot,
    not about the plant, and is ``None`` for anything growing in the ground.
    """

    by_day: dict[date, float] = field(default_factory=dict)
    container_litres: float | None = None


def irrigation_mm(
    amount_ml: float, *, capacity_mm: float, container_litres: float | None
) -> float | None:
    """the design conversion, and ``None`` where there is not one.

    ``irrigation_mm = capacity_mm × (amount_ml / refill_ml)``, with
    ``refill_ml = container_litres × 1000 × AVAILABLE_WATER_FRACTION``.

    Expressed against ``capacity_mm``, which the weather engine's engine already
    computes, rather than against a root-zone area that would need to know the
    shape of the pot. A watering that would refill the buffer relieves the whole
    buffer; half of it relieves half. Over-watering credits nothing extra,
    because ``step_deficit`` clamps the deficit at zero — the water that leaves
    the drainage holes was never available to the plant.

    ``None`` when there is no honest conversion: no container means ``refill_ml``
    is undefined, and the term is **omitted rather than guessed**.
    """
    if not container_litres or container_litres <= 0.0 or capacity_mm <= 0.0:
        return None
    refill_ml = container_litres * 1000.0 * AVAILABLE_WATER_FRACTION
    return capacity_mm * (amount_ml / refill_ml)


def _caveats(payload: dict[str, Any]) -> tuple[Caveat, ...]:
    return tuple(
        Caveat(
            code=str(row.get("code") or "unknown"),
            detail=str(row.get("detail") or ""),
            caps_at=str(row.get("caps_at") or "medium"),
        )
        for row in payload.get("degradations") or []
    )


def _newest_day(payload: dict[str, Any]) -> date | None:
    days = payload.get("days") or []
    if not days:
        return None
    try:
        return date.fromisoformat(str(days[-1]["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def from_water_balance(
    payload: dict[str, Any] | None, *, added: tuple[Caveat, ...] = ()
) -> Environment:
    """The weather engine's ``WaterBalance`` response, as the scheduler's view of one plant.

    ``applies`` is the weather engine's own word for "this engine has an opinion here": an indoor
    pot gets a deficit for reference only, and scheduling a watering from it
    would be inventing weather in a study.

    ``added`` is this package's own doubt, beside the weather engine's rather than blended into
    it — the :class:`~tending.domain.Caveat` docstring's bargain. Today it is
    only ever :data:`IRRIGATION_UNCITED`, because the irrigation term this
    package fills is the one part of the answer the weather engine did not compute and cannot
    vouch for. Its ``caps_at`` is applied here: the design made ``caps_at`` a
    ceiling on the confidence, and E already folded its own degradations into
    the ``confidence`` it reports, so a caveat added after the fact has to lower
    that ceiling itself or it would be a warning nobody acted on.
    """
    if not payload:
        return Environment()
    confidence = str(payload.get("confidence") or "unknown")
    return Environment(
        applies=bool(payload.get("applies")),
        balance_status=payload.get("status"),
        satisfied_by=payload.get("satisfied_by"),
        is_due=bool(payload.get("is_due")),
        confidence=weakest(confidence, *(caveat.caps_at for caveat in added)),
        degradations=_caveats(payload) + added,
        newest_day=_newest_day(payload),
    )


def fixture_environments(
    specimen_ids: list[str], waterings: dict[str, Waterings] | None = None
) -> dict[str, Environment]:
    """Mock mode: ask the Almanac, which reads the same fixtures everyone does.

    Wrapped in a broad ``except`` on purpose. The weather engine's engine deciding it cannot
    answer for one plant must leave that plant unscheduled and the other eleven
    scheduled — not take Morning Rounds down for the household.

    ``waterings`` is the design seam, from the side that owns the completion
    log. The weather engine must not read ``api/tending/`` — a cycle between the scheduler and
    the engine is how "why is this plant due?" stops having an answer anybody
    can trace — so the waterings are handed *in*, converted here, and passed on
    through ``water_balance(irrigation=...)``.

    A plant that was watered is read twice, and only such a plant. The
    conversion needs ``capacity_mm``, which is the weather engine's to compute and arrives on the
    response; it does not depend on the irrigation series, so the second read is
    exact rather than an approximation. The alternative was importing the weather engine's
    ``world`` module to get at the figure directly, which would be a second seam
    where the design names one.
    """
    from almanac import service as almanac

    waterings = waterings or {}
    out: dict[str, Environment] = {}
    for specimen_id in specimen_ids:
        try:
            payload = almanac.water_balance(specimen_id)
        except Exception:  # noqa: BLE001 — one plant's engine, not the app's
            payload = None
        added: tuple[Caveat, ...] = ()
        logged = waterings.get(specimen_id)
        if payload and payload.get("applies") and logged and logged.by_day:
            applied, added = _irrigation_series(logged, payload)
            if applied:
                try:
                    payload = (
                        almanac.water_balance(specimen_id, irrigation=applied)
                        or payload
                    )
                except Exception:  # noqa: BLE001
                    # The deficit stands as E last gave it, so the caveat must
                    # stop saying the watering is in it.
                    added = (_uncited(_NOT_COUNTED_DETAIL),)
        out[specimen_id] = from_water_balance(payload, added=added)
    return out


def _irrigation_series(
    logged: Waterings, payload: dict[str, Any]
) -> tuple[dict[date, float], tuple[Caveat, ...]]:
    """Millimetres of relief per day, and the caveat that says what it is worth.

    Two ways the conversion cannot honestly happen, each of which leaves the
    deficit reading drier than the plant is, and each of which says so rather
    than passing for a clean answer: no container to convert through, and no
    volume logged to convert. The task is ``done`` in both cases — §1 does not
    depend on any of this.

    A watering logged *after* the last day the weather records reach is counted
    on that last day. The balance is a replay and its final deficit is what the
    app calls "now", so water that is in the pot now has nowhere else honest to
    go; the alternative is dropping it in silence, which is the bug the design is
    about wearing a different hat. The detail sentence says when this happened.

    One limit, raised with the maintainers in the pull request rather than papered over: a
    watering older than the whole replay is not counted, because the replay has
    no day for it to act on. It cannot arise today — a completion is stamped at
    the moment it happens and the shipped records end in the past, so every
    logged watering is at or after the last day, never before the first.
    """
    capacity_mm = float(payload.get("capacity_mm") or 0.0)
    if not sum(logged.by_day.values()):
        return {}, (_uncited(_NO_VOLUME_DETAIL),)

    # The newest day the balance covers. ``days`` is trimmed for the screen and
    # the trim takes the *tail*, so the last entry is the replay's last day even
    # though the first entry is not its first.
    last = next(
        (
            parsed
            for row in reversed(payload.get("days") or [])
            if (parsed := _as_day(row.get("day"))) is not None
        ),
        None,
    )
    if last is None:
        return {}, (_uncited(_NOT_COUNTED_DETAIL),)

    applied: dict[date, float] = {}
    clamped = False
    for day, amount_ml in sorted(logged.by_day.items()):
        if not amount_ml:
            continue
        relief = irrigation_mm(
            amount_ml,
            capacity_mm=capacity_mm,
            container_litres=logged.container_litres,
        )
        if relief is None:
            return {}, (_uncited(_NO_POT_DETAIL),)
        on = day
        if day > last:
            on, clamped = last, True
        applied[on] = applied.get(on, 0.0) + relief

    if not applied:
        return {}, (_uncited(_NO_VOLUME_DETAIL),)
    detail = _MODELLED_DETAIL + (_AFTER_THE_WEATHER_DETAIL if clamped else "")
    return applied, (_uncited(detail),)


def _as_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def fixture_frost_alerts() -> list[dict[str, Any]]:
    """Open frost alerts: the ``alerts`` half of Morning Rounds, and now the
    input the frost guard's tasks are raised from.

    Still read, never raised here. The weather engine's engine decides which plant is at risk on
    which night and against what threshold; an earlier release adds only the *task* that answers
    it (``tending.frost``) and the link between the two.
    """
    from almanac import service as almanac

    try:
        return list(almanac.frost())
    except Exception:  # noqa: BLE001
        return []


def fixture_weather_today() -> dict[str, Any] | None:
    """The day's forecast point, as the contract's ``ForecastPoint``."""
    from almanac import service as almanac

    try:
        days = almanac.forecast("", "daily")
    except Exception:  # noqa: BLE001
        return None
    return days[0] if days else None


def fixture_outlook() -> Outlook:
    """The nights ahead and the sunsets that end the days, from the weather engine's forecast.

    One reading of one endpoint, because the frost guard needs both and they must
    describe the same week: a deadline taken from one forecast and a mild-night
    run taken from another is how a plant gets carried out on the strength of a
    night that was never in the same document.

    Empty when E cannot answer, and an empty outlook is handled rather than
    guessed around: the task falls back to the rounds hour for its deadline and
    the return suggestion is withheld with a reason (``tending.frost``).

    One honest wrinkle, raised with the maintainers and the weather engine in the pull request:
    under
    ``MOH_SCENARIO`` the frost guard reads the frost recording's *own* first day
    as today while the forecast starts at ``MOH_SCENARIO_DAY``, so in a
    deployment with no scenario selected the guard warns about October nights
    that the baseline forecast has never heard of. The sunsets are then unknown
    and the fallback above is what a reader sees.
    """
    from almanac import service as almanac

    try:
        days = almanac.forecast("", "daily")
    except Exception:  # noqa: BLE001 — a forecast nobody can read is not a crash
        return Outlook()

    lows: dict[date, float] = {}
    sunsets: dict[date, datetime] = {}
    for day in days:
        try:
            when = datetime.fromisoformat(str(day["time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if day.get("temp_min_c") is not None:
            lows[when.date()] = float(day["temp_min_c"])
        sunset = day.get("sunset")
        if sunset:
            try:
                sunsets[when.date()] = datetime.fromisoformat(
                    str(sunset).replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
    return Outlook(lows_c=lows, sunsets=sunsets)


def from_balance_row(row: Any, *, today: date) -> Environment:
    """Live mode: one ``water_balance`` row, which is all the table can say.

    The table stores the deficit and the threshold. It does **not** store the
    confidence or the degradations the design put on the API response, so this
    path cannot pass through what it cannot read — it reports a modelled
    deficit at ``medium``, which is what ``workers/weather/quality.py`` itself
    calls a modelled figure worth, and adds the staleness it *can* verify.

    That gap is real and is raised with the maintainers in the pull request: the
    honest fix is columns on ``water_balance``, not a guess here.
    """
    if row is None:
        return Environment()
    deficit = float(row.deficit_mm)
    threshold = float(row.threshold_mm)
    override = row.sensor_override_pct
    # A probe outranks the model. No hardware drives this today.
    is_due = float(override) < 30.0 if override is not None else deficit >= threshold
    return Environment(
        applies=True,
        balance_status="due" if is_due else "ok",
        satisfied_by=None,
        is_due=is_due,
        confidence="medium",
        degradations=(),
        newest_day=row.day if isinstance(row.day, date) else today,
    )
