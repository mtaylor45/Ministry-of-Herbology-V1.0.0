"""Reference evapotranspiration, and what to do when nobody supplies it.

the design. The water balance eats ET₀ every day. When Open-Meteo does not
supply it, the choice is between skipping the day — which leaves the deficit
frozen and the plant looking *better* watered than it is — and computing a
less accurate figure locally and saying so. The design decision chose the second, and the
sentence worth remembering from it is this: a silent gap in ET₀ makes the
deficit look healthier than it is.

So this module answers with three outcomes, never two:

``ingested``
    Open-Meteo's own ``et0_fao_evapotranspiration``. Always preferred; the
    fallback never overwrites it.
``hargreaves``
    Computed here from daily minimum and maximum temperature and the site
    latitude — all three already stored, so the fallback adds no new data
    dependency. Labelled, and it caps the day's confidence at ``medium``.
``unavailable``
    Not even a min and a max. The deficit does not advance and the Almanac
    says so, because an unknown day is not a zero-evaporation day.

## On the library the design names

The design decision specifies ``climate_indices`` for the Hargreaves step. It is not a
dependency of this repository: dependencies live in ``api/pyproject.toml``,
which the weather engine does not own, and the ownership rule says to escalate rather than work
around. Adding it is the maintainers' call and is requested in the earlier pull request.

Until then :func:`hargreaves_et0_mm` implements the same published method the
library does — FAO-56 Hargreaves, eq. 52, over FAO-56 eq. 21–25 for
extraterrestrial radiation — as a single pure function with the equations
written out. It is the one seam: when the dependency lands, that function's
body is what changes, and nothing above it moves.

Hargreaves is known to run high in humid continental climates, by roughly a
tenth against Penman-Monteith at this site. That is not a defect to correct
with a fudge factor; it is the documented cost of the fallback, which is why
the day is labelled rather than blended.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

#: Solar constant, MJ m⁻² min⁻¹ (FAO-56 §3).
SOLAR_CONSTANT = 0.0820

#: MJ m⁻² day⁻¹ → mm day⁻¹ of equivalent evaporation (FAO-56 table 1).
MJ_TO_MM = 0.408

#: FAO-56 eq. 52. Not a tuned parameter — the published coefficient.
HARGREAVES_COEFFICIENT = 0.0023

INGESTED = "ingested"
HARGREAVES = "hargreaves"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Et0Day:
    """One day's ET₀, and where it came from.

    ``mm`` is ``None`` only when ``method`` is ``unavailable``. Callers must
    handle that case rather than coercing it to zero: zero evaporation is a
    claim about the weather, and we would not have one to make.
    """

    day: date
    mm: float | None
    method: str
    source: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.method == HARGREAVES

    @property
    def is_missing(self) -> bool:
        return self.mm is None

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day.isoformat(),
            "et0_mm": None if self.mm is None else round(self.mm, 3),
            "et0_method": self.method,
            "et0_source": self.source,
        }


def extraterrestrial_radiation_mm(latitude_deg: float, day_of_year: int) -> float:
    """Ra for a day and a latitude, in mm/day of equivalent evaporation.

    FAO-56 eq. 21 with its inputs from eq. 23 (inverse relative Earth-Sun
    distance), eq. 24 (solar declination) and eq. 25 (sunset hour angle).
    """
    phi = math.radians(latitude_deg)
    seasonal = 2.0 * math.pi * day_of_year / 365.0
    inverse_distance = 1.0 + 0.033 * math.cos(seasonal)
    declination = 0.409 * math.sin(seasonal - 1.39)

    # Inside the polar circles the sun may never set or never rise, and
    # -tan(φ)·tan(δ) leaves [-1, 1]. Clamping gives 24 h or 0 h of daylight,
    # which is the physical answer; acos would simply raise.
    cos_sunset = max(-1.0, min(1.0, -math.tan(phi) * math.tan(declination)))
    sunset_angle = math.acos(cos_sunset)

    radiation = (
        (24.0 * 60.0 / math.pi)
        * SOLAR_CONSTANT
        * inverse_distance
        * (
            sunset_angle * math.sin(phi) * math.sin(declination)
            + math.cos(phi) * math.cos(declination) * math.sin(sunset_angle)
        )
    )
    return max(0.0, radiation) * MJ_TO_MM


def hargreaves_et0_mm(
    day: date, tmin_c: float, tmax_c: float, latitude_deg: float
) -> float:
    """FAO-56 eq. 52: ``ET₀ = 0.0023 · Ra · (Tmean + 17.8) · √(Tmax − Tmin)``.

    The single seam for the design ``climate_indices``; see the module note.
    """
    if tmax_c < tmin_c:
        tmin_c, tmax_c = tmax_c, tmin_c
    radiation = extraterrestrial_radiation_mm(latitude_deg, day.timetuple().tm_yday)
    mean_c = (tmin_c + tmax_c) / 2.0
    # A negative mean below -17.8 °the inventory API would flip the sign of the whole product
    # and credit the plant with rain it never had. Nothing evaporates from
    # frozen ground anyway.
    span = math.sqrt(max(0.0, tmax_c - tmin_c))
    return max(0.0, HARGREAVES_COEFFICIENT * radiation * (mean_c + 17.8) * span)


def resolve_et0(
    day: date,
    *,
    ingested_mm: float | None,
    tmin_c: float | None,
    tmax_c: float | None,
    latitude_deg: float,
    source: str | None = "open_meteo",
) -> Et0Day:
    """Pick the day's ET₀ 's order of preference."""
    if ingested_mm is not None and ingested_mm >= 0.0:
        return Et0Day(day=day, mm=float(ingested_mm), method=INGESTED, source=source)
    if tmin_c is not None and tmax_c is not None:
        return Et0Day(
            day=day,
            mm=hargreaves_et0_mm(day, tmin_c, tmax_c, latitude_deg),
            method=HARGREAVES,
            source="local_hargreaves",
        )
    return Et0Day(day=day, mm=None, method=UNAVAILABLE, source=None)
