"""Calibration: what the numbers mean, and whether they mean anything.

the design fixes the model — a raster image plus control points — and the design
fixes the two map kinds. Both live in one :class:`Calibration` schema, which is
the contract's own decision and the right one: a survey derives a
``scale_mm_per_px`` from its control points, so the field is not plan-only, and
building two schemas would mean building two map components. What the contract
cannot say is that ``points`` is meaningless on a floor plan and insufficient
below two on a survey. That rule is enforced here, and the API is where it
belongs.

The survey fit is a **similarity transform** — one scale, one rotation, one
translation — from layer pixels into a local tangent plane in metres, and from
there to latitude and longitude. Two points determine it exactly. More points
over-determine it, and the residual is then a real measurement of how well the
operator's clicks agree with each other.

With exactly two points the residual is zero *by construction* and says nothing
at all about accuracy. :attr:`SurveyFit.residual_is_meaningful` exists so no
surface can quietly present that zero as survey-grade agreement, which is the
failure the design warned about in as many words.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, TypeGuard


#: Metres per degree, as the usual WGS84 series in the latitude of interest.
#: Good to well under a metre anywhere, which is far finer than a hand-placed
#: control point on a scanned plat.
def metres_per_degree(latitude_deg: float) -> tuple[float, float]:
    phi = math.radians(latitude_deg)
    per_lat = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
    per_lon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
    return per_lat, per_lon


class CalibrationError(ValueError):
    """Calibration the API will not store. The router answers 422."""


@dataclass(frozen=True, slots=True)
class ControlPoint:
    px_x: float
    px_y: float
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class SurveyFit:
    """A fitted pixel↔world transform, and how much to believe it."""

    origin_lat: float
    origin_lon: float
    #: The complex similarity coefficient, in metres per pixel.
    scale_rotation: complex
    offset_east_m: float
    offset_north_m: float
    point_count: int
    rms_error_m: float
    worst_error_m: float

    @property
    def metres_per_px(self) -> float:
        return abs(self.scale_rotation)

    @property
    def mm_per_px(self) -> float:
        return self.metres_per_px * 1000.0

    @property
    def rotation_deg(self) -> float:
        """How far the image is turned from north-up, positive anticlockwise."""
        return math.degrees(
            math.atan2(self.scale_rotation.imag, self.scale_rotation.real)
        )

    @property
    def residual_is_meaningful(self) -> bool:
        """Two points fit exactly; a zero residual from two points is not evidence."""
        return self.point_count > 2

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        """Layer pixels to (latitude, longitude)."""
        q = self.scale_rotation * complex(x, -y) + complex(
            self.offset_east_m, self.offset_north_m
        )
        per_lat, per_lon = metres_per_degree(self.origin_lat)
        return self.origin_lat + q.imag / per_lat, self.origin_lon + q.real / per_lon

    def to_px(self, latitude: float, longitude: float) -> tuple[float, float]:
        """(latitude, longitude) back to layer pixels."""
        per_lat, per_lon = metres_per_degree(self.origin_lat)
        q = complex(
            (longitude - self.origin_lon) * per_lon,
            (latitude - self.origin_lat) * per_lat,
        )
        p = (q - complex(self.offset_east_m, self.offset_north_m)) / self.scale_rotation
        return p.real, -p.imag


def fit_survey(points: list[ControlPoint]) -> SurveyFit:
    """Least-squares similarity from layer pixels to metres, then to degrees.

    Image y grows downward and north grows up, so the pixel side is conjugated
    on the way in: that single flip is what lets one complex coefficient carry
    scale and rotation without also needing a reflection term.
    """
    if len(points) < 2:
        raise CalibrationError(
            "A survey needs at least two pixel↔world points to be georeferenced "
            f"; {len(points)} given."
        )

    origin_lat = sum(p.latitude for p in points) / len(points)
    origin_lon = sum(p.longitude for p in points) / len(points)
    per_lat, per_lon = metres_per_degree(origin_lat)

    pixel = [complex(p.px_x, -p.px_y) for p in points]
    world = [
        complex(
            (p.longitude - origin_lon) * per_lon, (p.latitude - origin_lat) * per_lat
        )
        for p in points
    ]

    pixel_mean = sum(pixel) / len(pixel)
    world_mean = sum(world) / len(world)
    centred_pixel = [p - pixel_mean for p in pixel]
    centred_world = [w - world_mean for w in world]

    denominator = sum(abs(p) ** 2 for p in centred_pixel)
    if denominator == 0:
        raise CalibrationError(
            "Every control point sits on the same pixel, so no scale or "
            "rotation can be worked out from them. Place them apart."
        )
    coefficient = (
        sum(
            w * p.conjugate() for w, p in zip(centred_world, centred_pixel, strict=True)
        )
        / denominator
    )
    if coefficient == 0:
        raise CalibrationError(
            "Every control point names the same place on Earth, so the survey "
            "has no scale. Place them apart."
        )
    offset = world_mean - coefficient * pixel_mean

    residuals = [
        abs(w - (coefficient * p + offset)) for w, p in zip(world, pixel, strict=True)
    ]
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))

    return SurveyFit(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        scale_rotation=coefficient,
        offset_east_m=offset.real,
        offset_north_m=offset.imag,
        point_count=len(points),
        rms_error_m=rms,
        worst_error_m=max(residuals),
    )


# ------------------------------------------------------------------ validation


def _finite(value: Any) -> TypeGuard[float]:
    """A real number: not ``None``, not a bool, not a NaN or an infinity.

    A ``TypeGuard`` rather than a ``bool`` because every caller here is sifting
    values that arrived as JSON, and the narrowing is the point.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def parse_points(raw: Any) -> list[ControlPoint]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CalibrationError("`points` must be a list of {px, world} pairs.")
    points: list[ControlPoint] = []
    for index, item in enumerate(raw):
        where = f"points[{index}]"
        if not isinstance(item, dict):
            raise CalibrationError(f"{where} is not an object.")
        pairs: dict[str, tuple[float, float]] = {}
        for name in ("px", "world"):
            pair = item.get(name)
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise CalibrationError(f"{where}.{name} must be a pair of numbers.")
            if not all(_finite(value) for value in pair):
                raise CalibrationError(
                    f"{where}.{name} must be a pair of finite numbers."
                )
            pairs[name] = (float(pair[0]), float(pair[1]))
        px, world = pairs["px"], pairs["world"]
        latitude, longitude = world[0], world[1]
        if not -90.0 <= latitude <= 90.0:
            raise CalibrationError(
                f"{where}.world latitude {latitude} is outside ±90°."
            )
        if not -180.0 <= longitude <= 180.0:
            raise CalibrationError(
                f"{where}.world longitude {longitude} is outside ±180°."
            )
        points.append(ControlPoint(px[0], px[1], latitude, longitude))
    return points


def check_points_within_image(
    points: list[ControlPoint], width_px: int, height_px: int
) -> None:
    """A control point off the sheet is a misclick, not a calibration."""
    for index, point in enumerate(points):
        if not (0 <= point.px_x <= width_px and 0 <= point.px_y <= height_px):
            raise CalibrationError(
                f"points[{index}].px ({point.px_x:g}, {point.px_y:g}) is outside the "
                f"image, which is {width_px}×{height_px} pixels."
            )


def validate_calibration(
    kind: str, payload: dict[str, Any], width_px: int, height_px: int
) -> dict[str, Any]:
    """Normalise a ``Calibration`` body for one layer kind, or explain the refusal.

    Returns the stored shape: ``{"scale_mm_per_px": float | None, "points": [...]}``.
    """
    scale = payload.get("scale_mm_per_px")
    points = parse_points(payload.get("points"))

    if scale is not None:
        if not _finite(scale) or scale <= 0:
            raise CalibrationError(
                "`scale_mm_per_px` must be a positive number of millimetres per pixel."
            )
        scale = float(scale)

    if kind == "floor_plan":
        if points:
            raise CalibrationError(
                "A floor plan is a flat drawing on CRS.Simple: it has a scale, not a "
                "place on Earth. Send `scale_mm_per_px` alone, with no `points`."
            )
        if scale is None:
            raise CalibrationError(
                "A floor plan is calibrated by `scale_mm_per_px` — how many "
                "millimetres of room one pixel of the drawing covers."
            )
        return {"scale_mm_per_px": scale, "points": []}

    if kind == "survey":
        check_points_within_image(points, width_px, height_px)
        fit = fit_survey(points)
        return {
            "scale_mm_per_px": scale if scale is not None else round(fit.mm_per_px, 6),
            "points": [
                {"px": [p.px_x, p.px_y], "world": [p.latitude, p.longitude]}
                for p in points
            ],
        }

    raise CalibrationError(f"Unknown layer kind {kind!r}.")


def is_calibrated(kind: str, calibration: dict[str, Any] | None) -> bool:
    """Whether a layer can place anything yet.

    This is derivable, and that is the argument against making
    ``MapLayer.calibration`` nullable: an empty ``Calibration`` already says
    "nobody has calibrated this", and `null` would be a second spelling of the
    same state for every consumer to handle. See this parts of the project's README.
    """
    if not calibration:
        return False
    if kind == "floor_plan":
        scale = calibration.get("scale_mm_per_px")
        return _finite(scale) and float(scale) > 0.0
    points = calibration.get("points") or []
    return len(points) >= 2
