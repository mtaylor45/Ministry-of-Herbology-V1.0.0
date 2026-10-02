"""Pins, and the releases's exit criterion.

an earlier release exits when **every specimen can be pinned, and tapping a pin opens its
Specimen page**. The first half is a property of this API and is asserted
here against whatever the Register holds, rather than against a count
somebody wrote down. The second half is the app's screens' route and is asserted
in ``web/src/lib/map/`` by the deep link the pin carries.
"""

from __future__ import annotations

from typing import Any

import pytest


def _pins(client: Any, **params: str) -> list[dict[str, Any]]:
    response = client.get("/api/v1/grounds/pins", params=params)
    assert response.status_code == 200, response.text
    return list(response.json())


def test_every_pin_names_a_layer_that_exists_and_lands_on_it(
    client: Any, layers: list[dict[str, Any]]
) -> None:
    by_id = {layer["id"]: layer for layer in layers}
    for pin in _pins(client):
        layer = by_id.get(pin["layer_id"])
        assert layer is not None, f"pin on unknown layer {pin['layer_id']}"
        assert 0 <= pin["px"]["x"] <= layer["image_width_px"]
        assert 0 <= pin["px"]["y"] <= layer["image_height_px"]


def test_every_pin_carries_the_brief_a_cross_link_needs(client: Any) -> None:
    """The app's screens' map-to-Specimen link is built from these three fields."""
    pins = _pins(client)
    assert pins
    for pin in pins:
        brief = pin["specimen"]
        assert brief is not None
        assert brief["id"] == pin["specimen_id"]
        assert brief["display_name"].strip()
        assert isinstance(brief["is_outdoor"], bool)


def test_filtering_by_layer_returns_that_layer_and_nothing_else(
    client: Any, floor_plan: dict[str, Any], survey: dict[str, Any]
) -> None:
    indoor = _pins(client, layer_id=floor_plan["id"])
    outdoor = _pins(client, layer_id=survey["id"])
    assert {pin["layer_id"] for pin in indoor} == {floor_plan["id"]}
    assert {pin["layer_id"] for pin in outdoor} == {survey["id"]}
    assert len(indoor) + len(outdoor) == len(_pins(client))


def test_an_unknown_layer_filter_is_empty_rather_than_an_error(client: Any) -> None:
    assert _pins(client, layer_id="01890070-0000-7000-8000-00000000dead") == []


# ------------------------------------------------------- the exit criterion


def test_every_specimen_in_the_register_can_be_pinned(
    client: Any, floor_plan: dict[str, Any]
) -> None:
    """The earlier exit criterion, asserted against the Register rather than a count."""
    register = client.get("/api/v1/specimens", params={"limit": 200}).json()["items"]
    assert register, "the Register is empty; this test would prove nothing"

    middle = {
        "x": floor_plan["image_width_px"] / 2,
        "y": floor_plan["image_height_px"] / 2,
    }
    for specimen in register:
        response = client.put(
            "/api/v1/grounds/pins",
            json={
                "specimen_id": specimen["id"],
                "layer_id": floor_plan["id"],
                "px": middle,
            },
        )
        assert response.status_code == 200, f"{specimen['id']}: {response.text}"

    placed = _pins(client, layer_id=floor_plan["id"])
    assert {pin["specimen_id"] for pin in placed} == {s["id"] for s in register}


def test_a_pin_reads_back_where_it_was_put(
    client: Any, a_specimen: dict[str, Any], survey: dict[str, Any]
) -> None:
    target = {
        "x": survey["image_width_px"] * 0.25,
        "y": survey["image_height_px"] * 0.75,
    }
    written = client.put(
        "/api/v1/grounds/pins",
        json={"specimen_id": a_specimen["id"], "layer_id": survey["id"], "px": target},
    )
    assert written.status_code == 200, written.text
    assert written.json()["px"] == target

    read_back = next(
        pin for pin in _pins(client) if pin["specimen_id"] == a_specimen["id"]
    )
    assert read_back["layer_id"] == survey["id"]
    assert read_back["px"] == target


def test_moving_a_pin_to_another_layer_leaves_none_behind(
    client: Any,
    a_specimen: dict[str, Any],
    floor_plan: dict[str, Any],
    survey: dict[str, Any],
) -> None:
    for layer in (floor_plan, survey):
        client.put(
            "/api/v1/grounds/pins",
            json={
                "specimen_id": a_specimen["id"],
                "layer_id": layer["id"],
                "px": {"x": 10, "y": 10},
            },
        )
    mine = [pin for pin in _pins(client) if pin["specimen_id"] == a_specimen["id"]]
    assert len(mine) == 1
    assert mine[0]["layer_id"] == survey["id"]


def test_a_null_position_lifts_the_pin_off_the_map(
    client: Any, a_specimen: dict[str, Any], floor_plan: dict[str, Any]
) -> None:
    """A plant can be in the Register and not yet placed; that is not an error."""
    response = client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": a_specimen["id"],
            "layer_id": floor_plan["id"],
            "px": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["px"] is None
    assert a_specimen["id"] not in {pin["specimen_id"] for pin in _pins(client)}


@pytest.mark.parametrize("corner", [(-1, 10), (10, -1), (0, 0)])
def test_the_sheet_edge_is_inside_and_a_step_past_it_is_not(
    client: Any, a_specimen: dict[str, Any], floor_plan: dict[str, Any], corner: tuple
) -> None:
    x, y = corner
    response = client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": a_specimen["id"],
            "layer_id": floor_plan["id"],
            "px": {"x": x, "y": y},
        },
    )
    expected = 200 if x >= 0 and y >= 0 else 422
    assert response.status_code == expected, response.text


def test_a_pin_past_the_far_edge_is_refused_with_the_size_in_the_message(
    client: Any, a_specimen: dict[str, Any], floor_plan: dict[str, Any]
) -> None:
    response = client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": a_specimen["id"],
            "layer_id": floor_plan["id"],
            "px": {"x": floor_plan["image_width_px"] + 1, "y": 0},
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert str(floor_plan["image_width_px"]) in detail
    assert str(floor_plan["image_height_px"]) in detail


def test_a_pin_on_an_unknown_layer_is_refused(
    client: Any, a_specimen: dict[str, Any]
) -> None:
    response = client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": a_specimen["id"],
            "layer_id": "01890070-0000-7000-8000-00000000dead",
            "px": {"x": 1, "y": 1},
        },
    )
    assert response.status_code == 422
    assert "map layer" in response.json()["detail"]


def test_a_pin_for_an_unknown_specimen_is_refused(
    client: Any, floor_plan: dict[str, Any]
) -> None:
    response = client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": "01890040-0000-7000-8000-00000000dead",
            "layer_id": floor_plan["id"],
            "px": {"x": 1, "y": 1},
        },
    )
    assert response.status_code == 422
    assert "specimen" in response.json()["detail"]


# ------------------------------------------------------ calibration, on HTTP


def test_calibrating_a_plan_updates_the_layer_and_its_scale(
    client: Any, floor_plan: dict[str, Any]
) -> None:
    response = client.put(
        f"/api/v1/grounds/layers/{floor_plan['id']}/calibration",
        json={"scale_mm_per_px": 8.25},
    )
    assert response.status_code == 200, response.text
    layer = response.json()
    assert layer["scale_mm_per_px"] == 8.25
    assert layer["calibration"] == {"scale_mm_per_px": 8.25, "points": []}

    listed = next(
        row
        for row in client.get("/api/v1/grounds/layers").json()
        if row["id"] == floor_plan["id"]
    )
    assert listed["scale_mm_per_px"] == 8.25


def test_calibrating_a_survey_stores_its_points_and_derives_a_scale(
    client: Any, survey: dict[str, Any]
) -> None:
    assert survey["calibration"]["points"] == [], "the survey should start uncalibrated"
    points = [
        {
            "px": [survey["image_width_px"] * 0.1, survey["image_height_px"] * 0.9],
            "world": [39.7678, -86.1589],
        },
        {
            "px": [survey["image_width_px"] * 0.9, survey["image_height_px"] * 0.1],
            "world": [39.7690, -86.1573],
        },
    ]
    response = client.put(
        f"/api/v1/grounds/layers/{survey['id']}/calibration", json={"points": points}
    )
    assert response.status_code == 200, response.text
    layer = response.json()
    assert len(layer["calibration"]["points"]) == 2
    assert layer["scale_mm_per_px"] > 0


def test_calibrating_a_layer_that_does_not_exist_is_a_404(client: Any) -> None:
    response = client.put(
        "/api/v1/grounds/layers/01890070-0000-7000-8000-00000000dead/calibration",
        json={"scale_mm_per_px": 1.0},
    )
    assert response.status_code == 404


def test_the_image_of_a_layer_that_does_not_exist_is_a_404(client: Any) -> None:
    response = client.get(
        "/api/v1/grounds/layers/01890070-0000-7000-8000-00000000dead/image"
    )
    assert response.status_code == 404


def test_recalibrating_does_not_move_a_pin(
    client: Any, a_specimen: dict[str, Any], floor_plan: dict[str, Any]
) -> None:
    """pins stay in layer pixels, so a new scale re-places them all."""
    target = {"x": 120.0, "y": 240.0}
    client.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": a_specimen["id"],
            "layer_id": floor_plan["id"],
            "px": target,
        },
    )
    client.put(
        f"/api/v1/grounds/layers/{floor_plan['id']}/calibration",
        json={"scale_mm_per_px": 99.0},
    )
    after = next(
        pin
        for pin in client.get("/api/v1/grounds/pins").json()
        if pin["specimen_id"] == a_specimen["id"]
    )
    assert after["px"] == target
