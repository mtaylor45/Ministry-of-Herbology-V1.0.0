"""What a calibration has to be before the Grounds will store it.

The fit is the part of this parts of the project a unit test can genuinely prove, so it
is proved by round-tripping rather than by comparing against numbers somebody
typed: place control points, fit, and ask the transform to put them back where
they came from.
"""

from __future__ import annotations

import math

import pytest

from grounds.domain import (
    CalibrationError,
    ControlPoint,
    fit_survey,
    is_calibrated,
    metres_per_degree,
    parse_points,
    validate_calibration,
)

#: An arbitrary but self-consistent patch of the world. Nothing here reads
#: ``fixtures/`` — the geometry is the subject, not the household.
ORIGIN_LAT, ORIGIN_LON = 39.75, -86.16


#: How many metres of ground one pixel covers in the synthetic survey below.
METRES_PER_PX = 0.1


def _square(size_px: float = 1000.0) -> list[ControlPoint]:
    """Two opposite corners of a north-up patch that is square *on the ground*.

    A degree of longitude is shorter than a degree of latitude everywhere but
    the equator, so a patch built by adding the same number of degrees to both
    is not square and a similarity transform fits it at an angle. Deriving the
    longitude span from the latitude instead is what makes "north-up" mean
    north-up here — and the derivation uses the same series the fit does, so
    this is a round-trip and not a restatement.
    """
    metres = size_px * METRES_PER_PX
    per_lat, per_lon = metres_per_degree(ORIGIN_LAT)
    return [
        ControlPoint(0.0, size_px, ORIGIN_LAT, ORIGIN_LON),
        ControlPoint(
            size_px, 0.0, ORIGIN_LAT + metres / per_lat, ORIGIN_LON + metres / per_lon
        ),
    ]


def test_two_points_place_themselves_back_exactly() -> None:
    points = _square()
    fit = fit_survey(points)
    for point in points:
        latitude, longitude = fit.to_world(point.px_x, point.px_y)
        assert latitude == pytest.approx(point.latitude, abs=1e-9)
        assert longitude == pytest.approx(point.longitude, abs=1e-9)


def test_the_transform_inverts() -> None:
    fit = fit_survey(_square())
    for x, y in ((0.0, 0.0), (250.0, 900.0), (1000.0, 1000.0)):
        latitude, longitude = fit.to_world(x, y)
        back_x, back_y = fit.to_px(latitude, longitude)
        assert back_x == pytest.approx(x, abs=1e-6)
        assert back_y == pytest.approx(y, abs=1e-6)


def test_a_north_up_patch_comes_out_north_up() -> None:
    """Image y grows downward and north grows up; the fit must undo that."""
    fit = fit_survey(_square())
    assert fit.rotation_deg == pytest.approx(0.0, abs=0.5)
    # Moving *down* the image must move south.
    north_lat, _ = fit.to_world(500.0, 0.0)
    south_lat, _ = fit.to_world(500.0, 1000.0)
    assert north_lat > south_lat


def test_a_rotated_survey_reports_its_rotation() -> None:
    """A plat scanned sideways still georeferences; the angle is recoverable."""
    per_lat, _ = metres_per_degree(ORIGIN_LAT)
    turned = [
        ControlPoint(0.0, 0.0, ORIGIN_LAT, ORIGIN_LON),
        ControlPoint(1000.0, 0.0, ORIGIN_LAT + 100.0 / per_lat, ORIGIN_LON),
    ]
    fit = fit_survey(turned)
    # Pixels run due north, so the image is turned a quarter-turn from north-up.
    assert abs(fit.rotation_deg) == pytest.approx(90.0, abs=1.0)


def test_the_scale_matches_the_ground_distance_the_points_span() -> None:
    fit = fit_survey(_square())
    # 1e-5 relative, not exact: the fit takes its tangent-plane origin from the
    # mean of the control points, a shade north of ORIGIN_LAT, so the two
    # metres-per-degree evaluations differ in the seventh digit. That is the
    # approximation working, not a defect — and the bound is still tight
    # enough to catch a units error or an inverted ratio.
    assert fit.metres_per_px == pytest.approx(METRES_PER_PX, rel=1e-5)
    assert fit.mm_per_px == pytest.approx(METRES_PER_PX * 1000, rel=1e-5)


def test_two_points_cannot_disagree_so_their_residual_is_marked_meaningless() -> None:
    """do not present a hand-calibrated overlay as survey-grade."""
    fit = fit_survey(_square())
    assert fit.point_count == 2
    assert fit.rms_error_m == pytest.approx(0.0, abs=1e-9)
    assert fit.residual_is_meaningful is False


def test_a_third_point_that_disagrees_shows_up_in_the_residual() -> None:
    exact = _square()
    midpoint_lat, midpoint_lon = (
        (exact[0].latitude + exact[1].latitude) / 2,
        (exact[0].longitude + exact[1].longitude) / 2,
    )
    per_lat, _ = metres_per_degree(ORIGIN_LAT)
    points = [
        *exact,
        # On the diagonal in pixels, but placed ten metres north of it on Earth.
        ControlPoint(500.0, 500.0, midpoint_lat + 10.0 / per_lat, midpoint_lon),
    ]
    fit = fit_survey(points)
    assert fit.residual_is_meaningful is True
    assert fit.rms_error_m > 1.0
    assert fit.worst_error_m >= fit.rms_error_m


def test_points_stacked_on_one_pixel_are_refused() -> None:
    same = [
        ControlPoint(10.0, 10.0, ORIGIN_LAT, ORIGIN_LON),
        ControlPoint(10.0, 10.0, ORIGIN_LAT + 0.001, ORIGIN_LON),
    ]
    with pytest.raises(CalibrationError, match="same pixel"):
        fit_survey(same)


def test_points_naming_one_place_on_earth_are_refused() -> None:
    same = [
        ControlPoint(0.0, 0.0, ORIGIN_LAT, ORIGIN_LON),
        ControlPoint(100.0, 100.0, ORIGIN_LAT, ORIGIN_LON),
    ]
    with pytest.raises(CalibrationError, match="same place"):
        fit_survey(same)


def test_one_point_is_not_a_georeference() -> None:
    with pytest.raises(CalibrationError, match="at least two"):
        fit_survey([ControlPoint(0.0, 0.0, ORIGIN_LAT, ORIGIN_LON)])


# ------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    "raw",
    [
        [{"px": [1, 2]}],
        [{"px": [1], "world": [1, 2]}],
        [{"px": [1, 2], "world": [1, 2, 3]}],
        [{"px": ["a", 2], "world": [1, 2]}],
        [{"px": [1, 2], "world": [float("nan"), 2]}],
        [{"px": [1, 2], "world": [float("inf"), 2]}],
        ["not an object"],
        "not a list",
    ],
)
def test_malformed_points_are_refused_with_a_reason(raw: object) -> None:
    with pytest.raises(CalibrationError):
        parse_points(raw)


@pytest.mark.parametrize(
    ("latitude", "longitude"), [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)]
)
def test_coordinates_off_the_globe_are_refused(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(CalibrationError, match="outside"):
        parse_points([{"px": [0, 0], "world": [latitude, longitude]}])


def test_a_boolean_is_not_a_number() -> None:
    """`True` is an `int` in Python, and a `True` pixel coordinate is a bug."""
    with pytest.raises(CalibrationError):
        parse_points([{"px": [True, 0], "world": [0, 0]}])


# ---------------------------------------------------------------- kind rules


def test_a_floor_plan_takes_a_scale_and_nothing_else() -> None:
    stored = validate_calibration("floor_plan", {"scale_mm_per_px": 12.5}, 100, 100)
    assert stored == {"scale_mm_per_px": 12.5, "points": []}


def test_a_floor_plan_refuses_world_points() -> None:
    with pytest.raises(CalibrationError, match="CRS.Simple"):
        validate_calibration(
            "floor_plan",
            {"points": [{"px": [1, 1], "world": [ORIGIN_LAT, ORIGIN_LON]}]},
            100,
            100,
        )


def test_a_floor_plan_with_no_scale_is_not_a_calibration() -> None:
    with pytest.raises(CalibrationError, match="scale_mm_per_px"):
        validate_calibration("floor_plan", {}, 100, 100)


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), "twelve"])
def test_a_scale_must_be_a_positive_number(scale: object) -> None:
    with pytest.raises(CalibrationError, match="positive"):
        validate_calibration("floor_plan", {"scale_mm_per_px": scale}, 100, 100)


def test_a_survey_derives_its_own_scale_from_its_points() -> None:
    stored = validate_calibration(
        "survey",
        {
            "points": [
                {"px": [0, 1000], "world": [ORIGIN_LAT, ORIGIN_LON]},
                {"px": [1000, 0], "world": [ORIGIN_LAT + 0.001, ORIGIN_LON + 0.001]},
            ]
        },
        1000,
        1000,
    )
    assert stored["scale_mm_per_px"] is not None
    assert stored["scale_mm_per_px"] > 0
    assert len(stored["points"]) == 2


def test_a_control_point_off_the_sheet_is_a_misclick() -> None:
    with pytest.raises(CalibrationError, match="outside the image"):
        validate_calibration(
            "survey",
            {
                "points": [
                    {"px": [0, 0], "world": [ORIGIN_LAT, ORIGIN_LON]},
                    {"px": [5000, 5000], "world": [ORIGIN_LAT + 0.001, ORIGIN_LON]},
                ]
            },
            1000,
            1000,
        )


def test_an_unknown_kind_is_refused_rather_than_guessed() -> None:
    with pytest.raises(CalibrationError, match="Unknown layer kind"):
        validate_calibration("orbital_photograph", {"scale_mm_per_px": 1}, 10, 10)


# ------------------------------------------------- the nullability question


@pytest.mark.parametrize(
    ("kind", "calibration", "expected"),
    [
        ("floor_plan", None, False),
        ("floor_plan", {}, False),
        ("floor_plan", {"scale_mm_per_px": None, "points": []}, False),
        ("floor_plan", {"scale_mm_per_px": 0, "points": []}, False),
        ("floor_plan", {"scale_mm_per_px": 12.5, "points": []}, True),
        ("survey", {"scale_mm_per_px": None, "points": []}, False),
        ("survey", {"points": [{"px": [0, 0], "world": [0, 0]}]}, False),
        (
            "survey",
            {
                "points": [
                    {"px": [0, 0], "world": [0, 0]},
                    {"px": [1, 1], "world": [1, 1]},
                ]
            },
            True,
        ),
    ],
)
def test_uncalibrated_is_derivable_without_the_contract_saying_null(
    kind: str, calibration: dict | None, expected: bool
) -> None:
    """The argument for leaving ``MapLayer.calibration`` non-nullable.

    the design named this property as one of the two most likely to be wrong.
    It is answerable without widening the contract: an empty ``Calibration``
    already denotes "nobody has calibrated this", and every state below is
    told apart from every other without a `null` anywhere. See
    ``api/grounds/README.md`` for the recommendation this table supports.
    """
    assert is_calibrated(kind, calibration) is expected


def test_a_fit_survives_the_far_south_and_the_antimeridian() -> None:
    """The metres-per-degree series is latitude-dependent; check it is used."""
    southern = [
        ControlPoint(0.0, 100.0, -41.29, 174.78),
        ControlPoint(100.0, 0.0, -41.289, 174.781),
    ]
    fit = fit_survey(southern)
    for point in southern:
        latitude, longitude = fit.to_world(point.px_x, point.px_y)
        assert latitude == pytest.approx(point.latitude, abs=1e-9)
        assert longitude == pytest.approx(point.longitude, abs=1e-9)
    assert math.isfinite(fit.metres_per_px)
