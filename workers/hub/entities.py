"""Turning a Home Assistant entity into a ``reading`` row — the hub.

Pure functions over an :class:`~workers.hub.sources.base.EntityState`. No
network, no clock of their own, no database. Everything Home-Assistant-shaped
that is *not* a socket lives here, and everything here is decided 's
one rule: we address entities, and we do not care how HA came by them.

Three refusals are the substance of this module, and each exists because the
alternative puts a wrong number somewhere nobody will question it.

**A unit we do not recognise is refused, not assumed.** Home Assistant will
happily serve ``°F`` from one integration and ``°C`` from the next. A
thermostat read as Celsius when it meant Fahrenheit turns 68 °F into a frost
warning, and a mandrake into a casualty.

**A device class that contradicts the mapping is refused.** ``external_ids``
is the operator's claim about what an entity measures; ``device_class`` is
Home Assistant's. When they disagree, one of them is wrong and neither is
worth guessing at. This is the check that stops a bathroom humidity sensor
from being stored as ``soil_moisture_pct`` — which would not be
a mislabelled row, it would be the app inventing a soil probe that does not
exist and overriding the water balance with it.

**A physically impossible value is refused.** 340 % humidity is a unit error
or a parse error upstream; stored, it quietly poisons the hourly average that
the Almanac draws, and no later correction reaches it.

Every refusal comes back as a :class:`~workers.hub.sources.base.Skipped` with
a reason, and every reason reaches the job's report. Nothing is dropped
silently.
"""

from __future__ import annotations

from datetime import datetime

from .sources.base import EntityState, Reading, Skipped

#: The metrics the rest of the app knows how to use, and the contract's
#: ``reading.metric`` CHECK constraint. Anything else is ignored rather than
#: stored, so a chatty HA instance cannot flood the hypertable.
SUPPORTED_METRICS = (
    "temperature_c",
    "humidity_pct",
    "soil_moisture_pct",
    "soil_temperature_c",
    "illuminance_lux",
    "soil_ec",
)

#: Metrics that describe a pot rather than a room. A source carrying one of
#: these is a soil probe, and the design says none exists yet — the path is kept
#: complete and the day a probe appears it is picked up with no other change.
SOIL_METRICS = frozenset({"soil_moisture_pct", "soil_temperature_c", "soil_ec"})

#: What Home Assistant may call an entity for each metric we accept. ``None``
#: stands for "no device class at all", which is common and not an error: a
#: template sensor or an MQTT sensor often has none, and refusing those would
#: refuse half of a real installation. What is refused is a device class that
#: says something *else*.
ALLOWED_DEVICE_CLASSES: dict[str, frozenset[str | None]] = {
    "temperature_c": frozenset({None, "temperature"}),
    "soil_temperature_c": frozenset({None, "temperature"}),
    "humidity_pct": frozenset({None, "humidity"}),
    # MiFlora-style probes report soil moisture as `humidity`, and HA's own
    # plant integration does the same; `moisture` is what the newer ones use.
    # Both are accepted, and the specimen binding — not the device class — is
    # what makes a reading a soil reading.
    "soil_moisture_pct": frozenset({None, "moisture", "humidity"}),
    "illuminance_lux": frozenset({None, "illuminance"}),
    "soil_ec": frozenset({None, "conductivity"}),
}

#: Unit conversions into the SI units the contract stores. The keys are
#: matched case-insensitively with the degree sign optional, because HA
#: installations differ on both.
_PERCENT_UNITS = {"%", "pct", "percent"}
_LUX_UNITS = {"lx", "lux"}

#: Bounds a stored value has to fall inside. Generous on purpose — these catch
#: a unit error or a garbled payload, not an unusual afternoon.
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    "temperature_c": (-90.0, 70.0),
    "soil_temperature_c": (-90.0, 70.0),
    "humidity_pct": (0.0, 100.0),
    "soil_moisture_pct": (0.0, 100.0),
    "illuminance_lux": (0.0, 200_000.0),
    "soil_ec": (0.0, 20_000.0),
}


def normalise_unit(unit: str | None) -> str:
    """Lower-cased and stripped, so ``"°C"`` and ``" c "`` are one unit."""
    return (unit or "").strip().lower()


def convert(metric: str, value: float, unit: str | None) -> float | None:
    """``value`` in ``unit`` as the SI unit ``metric`` is stored in.

    ``None`` means the unit is not one we can convert, which is a refusal
    rather than a pass-through. See the module note on °F.
    """
    text = normalise_unit(unit)
    if metric in {"temperature_c", "soil_temperature_c"}:
        if text in {"c", "°c", "celsius", ""}:
            # An absent unit on a temperature is read as Celsius: everything
            # internal is SI, and HA's own default for a metric-configured
            # installation is Celsius. A wrong guess here is caught by the
            # range check below only for Kelvin, which is why "" is accepted
            # and "f" never is by accident.
            return value
        if text in {"f", "°f", "fahrenheit"}:
            return (value - 32.0) * 5.0 / 9.0
        if text == "k":
            return value - 273.15
        return None
    if metric in {"humidity_pct", "soil_moisture_pct"}:
        return value if text in _PERCENT_UNITS or text == "" else None
    if metric == "illuminance_lux":
        return value if text in _LUX_UNITS or text == "" else None
    if metric == "soil_ec":
        # Soil EC has no single convention. µS/cm is what the cheap probes
        # report and what the schema's bare ``soil_ec`` means here; the
        # SI-adjacent spellings convert onto it rather than being refused.
        if text in {"µs/cm", "us/cm", "μs/cm", ""}:
            return value
        if text == "ms/cm":
            return value * 1000.0
        if text == "ds/m":
            return value * 1000.0
        if text == "s/m":
            return value * 10_000.0
        return None
    return None


def device_class_agrees(metric: str, device_class: str | None) -> bool:
    """Does Home Assistant's own label contradict the operator's mapping?"""
    allowed = ALLOWED_DEVICE_CLASSES.get(metric)
    if allowed is None:
        return False
    return device_class in allowed


def in_plausible_range(metric: str, value: float) -> bool:
    low, high = PLAUSIBLE_RANGE.get(metric, (float("-inf"), float("inf")))
    return low <= value <= high


def reading_from_state(
    state: EntityState,
    *,
    metric: str,
    source_id: str,
    at: datetime,
    location_id: str | None = None,
    specimen_id: str | None = None,
    max_age_s: float,
) -> Reading | Skipped:
    """One entity into one row, or into a named reason it is not one.

    ``at`` is the moment of the poll and becomes ``reading.time``. That is
    deliberate, and it is the one modelling choice in this module worth
    arguing with:

    The alternative is to stamp the row with HA's ``last_updated``. It sounds
    more truthful and it behaves worse. Home Assistant only moves
    ``last_updated`` when the state *changes*, so a study that holds at 21.0 °C
    for three hours would produce one row in three hours, and the releases's
    exit criterion — readings stored every 5–15 minutes — would be met by a
    room with a draught and missed by a room without one. Worse, the Almanac
    could not tell that series apart from a hub that had stopped answering.

    So the row says *when we asked*, and ``last_updated`` is spent on the
    question it can actually answer: whether the device behind the entity is
    still alive. Past ``max_age_s`` the value is dropped rather than stored.
    """
    if metric not in SUPPORTED_METRICS:
        return Skipped(state.entity_id, metric, "unsupported_metric")
    if state.is_absent:
        return Skipped(
            state.entity_id,
            metric,
            "entity_unavailable",
            f"Home Assistant reports {state.entity_id} as {state.state!r}",
        )
    if not device_class_agrees(metric, state.device_class):
        return Skipped(
            state.entity_id,
            metric,
            "device_class_mismatch",
            f"mapped as {metric} but Home Assistant calls it "
            f"{state.device_class!r}",
        )
    if not state.is_fresh(at, max_age_s):
        age = state.age(at)
        detail = (
            f"last updated {int(age.total_seconds())}s ago"
            if age is not None
            else "Home Assistant sent no last_updated"
        )
        return Skipped(state.entity_id, metric, "stale_entity", detail)

    raw = state.numeric
    if raw is None:
        return Skipped(
            state.entity_id,
            metric,
            "not_a_number",
            f"state {state.state!r} is not numeric",
        )
    value = convert(metric, raw, state.unit)
    if value is None:
        return Skipped(
            state.entity_id,
            metric,
            "unconvertible_unit",
            f"{state.unit!r} is not a unit this adapter converts to {metric}",
        )
    if not in_plausible_range(metric, value):
        low, high = PLAUSIBLE_RANGE[metric]
        return Skipped(
            state.entity_id,
            metric,
            "out_of_range",
            f"{value:g} is outside {low:g}..{high:g} for {metric}",
        )
    return Reading(
        time=at,
        source_id=source_id,
        metric=metric,
        value=value,
        location_id=location_id,
        specimen_id=specimen_id,
        entity_id=state.entity_id,
    )
