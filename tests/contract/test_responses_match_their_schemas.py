"""Every response body the app serves must match the schema it declares.

gap the hard way: ``Task.completed_by`` was a bare ``$ref`` to ``Member``, every
unfinished task has served ``null`` since 1.0.0, and **nothing noticed for five
releases**. The rest of ``tests/contract/`` checks that the document is legal
OpenAPI and that the routes match what it declares — it never once opened a
response body and compared it to its schema, which is the one thing a contract
is actually for.

This module closes that. It calls every implemented endpoint the contract
declares, finds the schema for the status it answered with, and validates the
real payload. A route that nothing here calls fails :func:`
test_every_implemented_route_is_exercised_or_excused`, so the coverage cannot
quietly rot the way the validation itself did.

The client is function-scoped and resets both in-memory stores, because the
calls below create, patch and delete: the session-scoped ``client`` every other
contract module shares must not inherit a specimen this one invented.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from jsonschema import Draft202012Validator

#: Routes the contract declares, the app serves, and this module deliberately
#: does not validate a JSON body for. Each needs a reason, and the reason has to
#: be about the response rather than about the effort.
NOT_EXERCISED: dict[tuple[str, str], str] = {
    ("get", "/calendar/{token}.ics"): (
        "text/calendar, not JSON. The document's shape is asserted by "
        "tests/contract/test_mock_stack.py and tests/e2e/, which parse it."
    ),
    ("get", "/grounds/layers/{layer_id}/image"): (
        "image/png or image/jpeg, not JSON — the operator's own uploaded bytes, "
        "served back unchanged, so there is no document to validate. What does "
        "need asserting is asserted elsewhere: that the bytes come back "
        "byte-identical and under the media type the upload's magic bytes "
        "identified rather than the one the client claimed "
        "(api/grounds/tests/)."
    ),
    ("get", "/specimens/{specimen_id}/photos/{photo_id}/image"): (
        "image/png or image/jpeg, not JSON — the third image route, declared in "
        "1.8.0 on the reasoning of the two above. That the bytes "
        "come back unchanged, under the media type their magic bytes name, and "
        "only under their own specimen's path, is asserted in api/inventory/tests/."
    ),
    ("get", "/journal/plates/{plate_id}/image"): (
        "image/png or image/jpeg, not JSON — the same case as the map layer "
        "above, declared in 1.6.0 on the same reasoning. That the "
        "media type comes from the stored file's magic bytes and that a missing "
        "file is a 404 rather than a stand-in are asserted in "
        "workers/plates/tests/."
    ),
}


# ------------------------------------------------------------------ plumbing


@pytest.fixture
def api() -> Iterator[Any]:
    """A mock-mode client whose stores start and finish at the fixtures."""
    from app.main import app
    from fastapi.testclient import TestClient
    from grounds.fixture_repository import reset_fixture_repository as reset_grounds
    from inventory.fixture_repository import (
        reset_fixture_repository as reset_inventory,
    )
    from tending.fixture_repository import reset_fixture_repository as reset_tending

    from workers.hub.office import reset_mock_store as reset_hub
    from workers.hub.router import loopback_reader, rounds_reader
    from workers.plates.fixture_repository import (
        reset_fixture_repository as reset_journal,
    )

    reset_grounds()
    reset_hub()
    reset_inventory()
    reset_tending()
    reset_journal()
    # The Lunette reads the scheduler's round over HTTP from `MOH_API_URL`. Here that
    # request is carried back into this app, so the feed is built from the
    # real round rather than from a "could not reach" fallback.
    app.dependency_overrides[rounds_reader] = loopback_reader(app)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(rounds_reader, None)
    reset_inventory()
    reset_tending()


def standalone(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """One schema out of the spec, as a JSON Schema that resolves on its own.

    ``$ref`` targets are rewritten from OpenAPI's ``#/components/schemas/`` to
    ``#/$defs/`` and the component section is inlined under ``$defs``, which is
    what lets a plain ``Draft202012Validator`` resolve them with no registry and
    no network. OpenAPI 3.1 *is* JSON Schema 2020-12, so nothing else has to be
    translated — including the ``if``/``then`` the design added to ``Task``.
    """
    defs = copy.deepcopy(spec["components"]["schemas"])
    out = copy.deepcopy(schema)
    out["$defs"] = defs
    return _rewrite_refs(out)


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: (
                value.replace("#/components/schemas/", "#/$defs/")
                if key == "$ref" and isinstance(value, str)
                else _rewrite_refs(value)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_rewrite_refs(item) for item in node]
    return node


def response_schema(
    spec: dict[str, Any], method: str, path: str, status: int
) -> dict[str, Any] | None:
    """The declared schema for one status, or ``None`` if there is no JSON body."""
    responses = spec["paths"][path][method].get("responses") or {}
    declared = responses.get(str(status))
    assert declared is not None, (
        f"{method.upper()} {path} answered {status}, which the contract does "
        f"not declare (it declares {sorted(responses)})"
    )
    body = (declared.get("content") or {}).get("application/json")
    return None if body is None else dict(body["schema"])


def check(spec: dict[str, Any], response: Any, method: str, path: str) -> None:
    """Validate one real response against the contract, or explain why not."""
    schema = response_schema(spec, method, path, response.status_code)
    if schema is None:
        return
    payload = response.json()
    validator = Draft202012Validator(standalone(schema, spec))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        [f"{method.upper()} {path} -> {response.status_code}:"]
        + [
            f"  {list(error.path) or '<root>'}: {error.message}"
            for error in errors[:20]
        ]
    )


# --------------------------------------------------------------- the calls

#: How to exercise each route: contract path -> a callable taking the client and
#: a small world of discovered ids, returning ``(response, expected_status)``.
#: Written out rather than generated, because a generated call that quietly
#: 422s validates the error body and calls it a pass.
Call = Callable[[Any, dict[str, str]], Any]

SITE_ID = "01890000-0000-7000-8000-000000000001"
KEEPER_ID = "01890050-0000-7000-8000-000000000001"
A_SPECIMEN = "01890040-0000-7000-8000-000000000004"
A_LOCATION = "01890010-0000-7000-8000-000000000007"


def _world(client: Any) -> dict[str, Any]:
    """Ids this module needs that only the running app can hand it."""
    species = client.get("/api/v1/species").json()
    rounds = client.get("/api/v1/tending/rounds").json()
    tasks = rounds["due"] + rounds["satisfied"]
    feed = client.post(
        "/api/v1/tending/feeds",
        json={"member_id": KEEPER_ID, "name": "Contract suite", "filters": {}},
    ).json()
    created = client.post(
        "/api/v1/specimens",
        json={
            "name": "Monstera deliciosa",
            "species_id": species[0]["id"],
            "location_id": A_LOCATION,
            "nickname": "Contract suite specimen",
            "in_container": True,
            "container_litres": 5,
        },
    )
    assert created.status_code == 201, created.text
    created = created.json()
    layers = client.get("/api/v1/grounds/layers").json()
    survey = next(layer for layer in layers if layer["kind"] == "survey")
    plan = next(layer for layer in layers if layer["kind"] == "floor_plan")
    waiting = client.get("/api/v1/journal/plates", params={"approved": "false"}).json()
    # One of A_SPECIMEN's own photographs, so the log entry below can cite it
    # and a served `LogEntry.photo` is a `Photo` rather than always null.
    photos = client.get(f"/api/v1/specimens/{A_SPECIMEN}/photos").json()
    return {
        "a_photo_id": str(photos[0]["id"]),
        "species_id": str(species[0]["id"]),
        "waiting_plate_id": str(waiting[0]["id"]),
        "task_id": str(tasks[0]["id"]),
        "feed_id": str(feed["id"]),
        "token": str(feed["https_url"]).rsplit("/", 1)[-1].removesuffix(".ics"),
        "scratch_specimen": str(created["id"]),
        "survey_layer_id": str(survey["id"]),
        "floor_plan_layer_id": str(plan["id"]),
        # Two control points on the survey's own corners, read off the layer
        # rather than written down. The coordinates are arbitrary but
        # consistent: this test asks whether the response matches its schema,
        # not where on Earth the fixture household is.
        "calibration_points": [
            {
                "px": [survey["image_width_px"] * 0.1, survey["image_height_px"] * 0.9],
                "world": [40.0, -86.0],
            },
            {
                "px": [survey["image_width_px"] * 0.9, survey["image_height_px"] * 0.1],
                "world": [40.001, -85.9988],
            },
        ],
        "a_pin_position": {
            "x": plan["image_width_px"] / 2,
            "y": plan["image_height_px"] / 2,
        },
    }


CALLS: dict[tuple[str, str], Call] = {
    # --- the inventory API, inventory
    ("get", "/specimens"): lambda c, w: c.get("/api/v1/specimens"),
    ("get", "/specimens/{specimen_id}"): lambda c, w: c.get(
        f"/api/v1/specimens/{A_SPECIMEN}"
    ),
    ("get", "/specimens/{specimen_id}/log"): lambda c, w: c.get(
        f"/api/v1/specimens/{A_SPECIMEN}/log"
    ),
    ("get", "/specimens/{specimen_id}/photos"): lambda c, w: c.get(
        f"/api/v1/specimens/{A_SPECIMEN}/photos"
    ),
    # Multipart, like `POST /grounds/layers`: the route sniffs magic bytes, so
    # the file is a real PNG. `caption` is the one form field the contract
    # declares; the rest are additive and left out here on purpose.
    ("post", "/specimens/{specimen_id}/photos"): lambda c, w: c.post(
        f"/api/v1/specimens/{A_SPECIMEN}/photos",
        files={"file": ("contract.png", _a_png(), "image/png")},
        data={"caption": "Contract suite photograph."},
    ),
    # `photo_id` is one of this specimen's own (the no-invented-plant-facts rule; another plant's is
    # a
    # 422), and `member_id` is additive as on the journal's notes.
    ("post", "/specimens/{specimen_id}/log"): lambda c, w: c.post(
        f"/api/v1/specimens/{A_SPECIMEN}/log",
        json={
            "kind": "growth",
            "body": "Contract suite: one entry.",
            "photo_id": w["a_photo_id"],
            "member_id": KEEPER_ID,
        },
    ),
    ("post", "/specimens"): lambda c, w: c.post(
        "/api/v1/specimens",
        json={
            "name": "Monstera deliciosa",
            "species_id": w["species_id"],
            "location_id": A_LOCATION,
            "nickname": "Second contract specimen",
        },
    ),
    ("patch", "/specimens/{specimen_id}"): lambda c, w: c.patch(
        f"/api/v1/specimens/{w['scratch_specimen']}", json={"status": "struggling"}
    ),
    ("delete", "/specimens/{specimen_id}"): lambda c, w: c.delete(
        f"/api/v1/specimens/{w['scratch_specimen']}"
    ),
    ("get", "/locations"): lambda c, w: c.get("/api/v1/locations"),
    ("post", "/locations"): lambda c, w: c.post(
        "/api/v1/locations",
        json={"name": "Contract suite shelf", "kind": "room", "is_outdoor": False},
    ),
    # A full body, because the contract declares `LocationCreate` here rather
    # than a partial: this PATCH is a replacement in all but name. Noted for the maintainers
    # and C rather than changed — `contracts/` is not the test suite's, and the app and the
    # document agree with each other, which is what this module checks.
    ("patch", "/locations/{location_id}"): lambda c, w: c.patch(
        f"/api/v1/locations/{A_LOCATION}",
        json={
            "name": "Back Terrace",
            "kind": "zone",
            "is_outdoor": True,
            "is_covered": False,
            "sun_exposure": "full_sun",
        },
    ),
    ("get", "/members"): lambda c, w: c.get("/api/v1/members"),
    # --- the botany worker, botany
    ("get", "/species"): lambda c, w: c.get("/api/v1/species"),
    ("get", "/species/{species_id}"): lambda c, w: c.get(
        f"/api/v1/species/{w['species_id']}"
    ),
    ("get", "/species/{species_id}/care-values"): lambda c, w: c.get(
        f"/api/v1/species/{w['species_id']}/care-values"
    ),
    ("post", "/taxon/resolve"): lambda c, w: c.post(
        "/api/v1/taxon/resolve", json={"name": "Monstera deliciosa"}
    ),
    # --- the weather engine, almanac
    ("get", "/almanac/forecast"): lambda c, w: c.get(
        "/api/v1/almanac/forecast", params={"site_id": SITE_ID, "horizon": "daily"}
    ),
    ("get", "/almanac/history"): lambda c, w: c.get(
        "/api/v1/almanac/history", params={"window": "30d", "metric": "temperature_c"}
    ),
    ("get", "/almanac/water-balance/{specimen_id}"): lambda c, w: c.get(
        f"/api/v1/almanac/water-balance/{A_SPECIMEN}"
    ),
    ("get", "/almanac/frost"): lambda c, w: c.get("/api/v1/almanac/frost"),
    # --- the scheduler, tending
    ("get", "/tending/rounds"): lambda c, w: c.get("/api/v1/tending/rounds"),
    ("get", "/tending/tasks"): lambda c, w: c.get("/api/v1/tending/tasks"),
    ("post", "/tending/tasks/{task_id}/complete"): lambda c, w: c.post(
        f"/api/v1/tending/tasks/{w['task_id']}/complete",
        json={"completed_by": KEEPER_ID},
    ),
    ("post", "/tending/tasks/complete-batch"): lambda c, w: c.post(
        "/api/v1/tending/tasks/complete-batch",
        json={"task_ids": [w["task_id"]], "completed_by": KEEPER_ID},
    ),
    ("get", "/tending/care-rules"): lambda c, w: c.get("/api/v1/tending/care-rules"),
    ("post", "/tending/care-rules"): lambda c, w: c.post(
        "/api/v1/tending/care-rules",
        json={
            "specimen_id": A_SPECIMEN,
            "task_type": "fertilize",
            "base_interval_days": 30,
        },
    ),
    ("get", "/tending/feeds"): lambda c, w: c.get("/api/v1/tending/feeds"),
    ("post", "/tending/feeds"): lambda c, w: c.post(
        "/api/v1/tending/feeds",
        json={"member_id": KEEPER_ID, "name": "Second contract feed"},
    ),
    ("post", "/tending/feeds/{feed_id}/revoke"): lambda c, w: c.post(
        f"/api/v1/tending/feeds/{w['feed_id']}/revoke"
    ),
    # --- the deployment, platform
    ("get", "/healthz"): lambda c, w: c.get("/api/v1/healthz"),
    # --- the maps module, grounds
    ("get", "/grounds/layers"): lambda c, w: c.get("/api/v1/grounds/layers"),
    ("get", "/grounds/pins"): lambda c, w: c.get("/api/v1/grounds/pins"),
    ("post", "/grounds/layers"): lambda c, w: c.post(
        "/api/v1/grounds/layers",
        files={"file": ("plat.png", _a_png(), "image/png")},
        data={"name": "Contract plat", "kind": "survey"},
    ),
    ("put", "/grounds/layers/{layer_id}/calibration"): lambda c, w: c.put(
        f"/api/v1/grounds/layers/{w['survey_layer_id']}/calibration",
        json={"points": w["calibration_points"]},
    ),
    ("put", "/grounds/pins"): lambda c, w: c.put(
        "/api/v1/grounds/pins",
        json={
            "specimen_id": A_SPECIMEN,
            "layer_id": w["floor_plan_layer_id"],
            "px": w["a_pin_position"],
        },
    ),
    # --- the journal, journal
    ("get", "/journal/plates"): lambda c, w: c.get("/api/v1/journal/plates"),
    # Reaches `PlateCoverageEntry.specimen`, which is why the UNREACHED entry
    # below is struck: a live response now carries it.
    ("get", "/journal/coverage"): lambda c, w: c.get("/api/v1/journal/coverage"),
    ("get", "/journal/{specimen_id}/notes"): lambda c, w: c.get(
        f"/api/v1/journal/{A_SPECIMEN}/notes"
    ),
    # `member_id` is additive — the frozen body requires only `body`. Sent here
    # on purpose: it is what makes a served `FieldNote.written_by` reachable,
    # which is how the UNREACHED entry below came to be struck.
    ("post", "/journal/{specimen_id}/notes"): lambda c, w: c.post(
        f"/api/v1/journal/{A_SPECIMEN}/notes",
        json={"body": "Contract suite: one observation.", "member_id": KEEPER_ID},
    ),
    # 1.6.0. The plate is one mock mode leaves waiting, so this
    # is a real state change and not a no-op on an already-approved row.
    ("post", "/journal/plates/{plate_id}/approve"): lambda c, w: c.post(
        f"/api/v1/journal/plates/{w['waiting_plate_id']}/approve",
        json={"member_id": KEEPER_ID},
    ),
    # --- the hub, hub
    ("get", "/hub/integrations"): lambda c, w: c.get("/api/v1/hub/integrations"),
    ("get", "/hub/sensors"): lambda c, w: c.get("/api/v1/hub/sensors"),
    # A thermostat in a room, mapped by reading kind. Mock mode
    # checks the entity id's shape and says so in `X-Hub-Check`.
    ("post", "/hub/sensors"): lambda c, w: c.post(
        "/api/v1/hub/sensors",
        json={
            "name": "Contract suite thermostat",
            "adapter": "home_assistant",
            "external_ids": {"temperature_c": "sensor.contract_suite_temperature"},
            "location_id": A_LOCATION,
        },
    ),
    ("get", "/hub/lunette"): lambda c, w: c.get("/api/v1/hub/lunette"),
    # --- the maintainers, the household's sign-in. This suite runs with
    # no passphrase configured, so these are the demo's open-mode answers; the
    # signed-in shapes are asserted in api/app/tests/test_auth_signin.py.
    ("get", "/auth/session"): lambda c, w: c.get("/api/v1/auth/session"),
    ("post", "/auth/session"): lambda c, w: c.post(
        "/api/v1/auth/session", json={"passphrase": "not configured here"}
    ),
    ("get", "/auth/sessions"): lambda c, w: c.get("/api/v1/auth/sessions"),
    ("delete", "/auth/session"): lambda c, w: c.delete("/api/v1/auth/session"),
    ("delete", "/auth/sessions"): lambda c, w: c.delete("/api/v1/auth/sessions"),
}


def _a_png() -> bytes:
    """A real PNG for the multipart upload, because the endpoint sniffs magic bytes."""
    from grounds.mocks.plan_image import encode_greyscale_png

    return encode_greyscale_png(8, 8, [bytearray([0xEE]) * 8 for _ in range(8)])


@pytest.mark.parametrize(
    ("method", "path"), sorted(CALLS), ids=lambda value: str(value)
)
def test_the_response_matches_the_schema_it_declares(
    api: Any, spec: dict[str, Any], method: str, path: str
) -> None:
    world = _world(api)
    response = CALLS[(method, path)](api, world)
    assert response.status_code < 400, (
        f"{method.upper()} {path} answered {response.status_code}; this test "
        f"validates success bodies, so the call needs fixing: {response.text[:300]}"
    )
    check(spec, response, method, path)


def test_every_implemented_route_is_exercised_or_excused(
    api: Any, spec: dict[str, Any]
) -> None:
    """The coverage this module rests on, checked rather than assumed.

    Without this, a new endpoint joins the app validated by nothing and the
    five-releases silence the design describes starts again from zero.
    """
    from test_api_matches_spec import (  # type: ignore[import-not-found]
        NOT_YET_IMPLEMENTED,
        _implemented_routes,
    )

    contract_routes = {
        (method, path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    live = _implemented_routes(api) & contract_routes
    uncovered = live - set(CALLS) - set(NOT_EXERCISED) - set(NOT_YET_IMPLEMENTED)
    assert not uncovered, (
        "these routes are served and their responses are validated by nothing: "
        f"{sorted(uncovered)}. Add a call to CALLS, or an entry to "
        "NOT_EXERCISED with a reason about the response."
    )

    stale = set(NOT_EXERCISED) - live
    assert not stale, f"NOT_EXERCISED names routes nobody serves: {sorted(stale)}"
    overlap = set(CALLS) & set(NOT_EXERCISED)
    assert not overlap, f"both called and excused: {sorted(overlap)}"


# --------------------------------------------- the validator's own teeth

# A test that can only pass is not a test. These two run the schema against
# payloads it must reject and must accept, so a future refactor that quietly
# stops resolving `$ref` — and therefore stops checking anything — is caught.


def _task_validator(spec: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(standalone({"$ref": "#/components/schemas/Task"}, spec))


def _a_task(api: Any) -> dict[str, Any]:
    rounds = api.get("/api/v1/tending/rounds").json()
    return dict((rounds["due"] + rounds["satisfied"])[0])


def test_a_satisfied_task_with_no_stated_cause_is_rejected(
    api: Any, spec: dict[str, Any]
) -> None:
    """the design, as a schema rule rather than a request in prose.

    "Satisfied" with no cause is the failure the design was written about: an
    answer that reads as reassurance while carrying no information. A screen
    should never have to say "the API did not say what settled it".
    """
    validator = _task_validator(spec)
    task = _a_task(api)

    task["status"] = "satisfied"
    task["satisfied_by"] = "rain"
    assert not list(validator.iter_errors(task)), "a stated cause must be legal"

    task["satisfied_by"] = None
    assert list(validator.iter_errors(task)), (
        "a satisfied task with no stated cause was accepted — the `if`/`then` "
        "the design added is not being evaluated, so this module is checking "
        "less than it appears to"
    )

    del task["satisfied_by"]
    assert list(
        validator.iter_errors(task)
    ), "a satisfied task that omits `satisfied_by` entirely was accepted"


def test_an_unfinished_task_may_say_nobody_completed_it(
    api: Any, spec: dict[str, Any]
) -> None:
    """The defect the design found, pinned so it cannot come back.

    Every open task the app serves carries ``completed_by: null``. Until 1.4.0
    the contract typed it as a bare ``$ref`` to ``Member`` and rejected all of
    them; the app was right and the document was wrong.
    """
    validator = _task_validator(spec)
    task = _a_task(api)
    assert task["status"] != "done"
    task["completed_by"] = None
    assert not list(
        validator.iter_errors(task)
    ), "an open task cannot say that nobody has completed it"

    task["completed_by"] = {"id": KEEPER_ID, "name": "Keeper", "role": "keeper"}
    assert not list(validator.iter_errors(task))

    task["completed_by"] = "Keeper"
    assert list(
        validator.iter_errors(task)
    ), "the null branch was widened into anything at all"


def test_an_uncited_care_value_can_say_it_is_uncited(
    api: Any, spec: dict[str, Any]
) -> None:
    """the design worst case, in the fixture data that hits it.

    ``CareValue``'s own description says a value with no source must carry
    ``confidence: unknown``. Until 1.4.0 ``source`` was a bare ``$ref``, so the
    contract forbade expressing the exact state the no-invented-plant-facts rule exists to handle.
    """
    validator = Draft202012Validator(
        standalone({"$ref": "#/components/schemas/CareValue"}, spec)
    )
    uncited = []
    for species in api.get("/api/v1/species").json():
        for value in api.get(f"/api/v1/species/{species['id']}/care-values").json():
            assert not list(validator.iter_errors(value)), json.dumps(value)
            if value["source"] is None:
                assert value["confidence"] == "unknown", value
                uncited.append(value)
    assert uncited, (
        "the fixtures no longer carry an uncited care value, so nothing "
        "exercises the case the no-invented-plant-facts rule exists for"
    )


# ------------------------------- the audit the design asked to be checked

# §8 fixed four bare `$ref`s to object schemas and left the rest alone on
# purpose, because widening a frozen contract on suspicion lets a producer send
# `null` where a consumer must have a value — the same defect pointing the other
# way. It asked for a test to say which of them are actually wrong rather than
# have A guess from outside.
#
# A test cannot say that: whether absence is a normal state is a judgement about
# the domain. What it can say, and what the two below do, is *which of them any
# live response reaches at all* — because a property nothing exercises is one
# nobody can vouch for, and the parametrised validation above is only as strong
# as the payloads it sees.


def _admits_null(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    return any(
        _admits_null(branch)
        for branch in (schema.get("anyOf") or schema.get("oneOf") or [])
    )


def _is_object_shaped(schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    return (
        kind == "object"
        or (isinstance(kind, list) and "object" in kind)
        or "properties" in schema
    )


def bare_object_refs(spec: dict[str, Any]) -> set[str]:
    """``Schema.property`` for every bare ``$ref`` that cannot say "there isn't one".

    Enums and scalar ``$ref``s are excluded: ``Task.status`` is a bare ``$ref``
    too, and a task always has one.
    """
    schemas = spec["components"]["schemas"]
    out = set()
    for name, schema in schemas.items():
        for prop, definition in (schema.get("properties") or {}).items():
            if not isinstance(definition, dict) or not definition.get("$ref"):
                continue
            target = schemas.get(definition["$ref"].rsplit("/", 1)[-1], {})
            if not _admits_null(target) and _is_object_shaped(target):
                out.add(f"{name}.{prop}")
    return out


#: Bare-``$ref`` properties no response this module makes ever reaches, with the
#: reason. Each is a property whose nullability nobody can confirm from the
#: running app — which is exactly how ``Task.completed_by`` survived five
#: releases. Shrinking this list is how the audit finishes.
#:
#: Being *reached* is weaker than being right: it vouches only for the shapes
#: today's fixtures produce. ``MapLayer.calibration`` is the clearest example —
#: the design names it one of the two most likely to be wrong, and
#: ``GET /grounds/layers`` does reach it, but the maps module's an earlier release stub hard-codes
#: two *calibrated* layers, so the uncalibrated state the design is worried about
#: is still served by nothing. Those layers are in `api/grounds/router.py` and
#: not in `fixtures/`, so L cannot add the case; it is the maps module's to decide.
UNREACHED: dict[str, str] = {
    "UnassessableSpecimen.specimen": (
        "added in 1.4.0, optional until 2.0.0, and neither producer populates "
        "it yet (the weather engine is mid-releases on /almanac/frost; the scheduler serves /tending/rounds). "
        "When they do, an archived specimen is the case to check."
    ),
    "CalendarFeedCreate.filters": "a request body, never a response",
}


def _walk(
    value: Any,
    schema: Any,
    schemas: dict[str, Any],
    reached: set[str],
    name: str | None = None,
    depth: int = 0,
) -> None:
    """Record every ``Schema.property`` a live payload actually carries."""
    if depth > 12 or not isinstance(schema, dict):
        return
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        schema = schemas.get(name, {})
    for branch in schema.get("anyOf") or schema.get("oneOf") or []:
        _walk(value, branch, schemas, reached, name, depth + 1)
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for item in value:
                _walk(item, items, schemas, reached, None, depth + 1)
        return
    if isinstance(value, dict):
        for prop, definition in (schema.get("properties") or {}).items():
            if prop not in value:
                continue
            if name:
                reached.add(f"{name}.{prop}")
            _walk(value[prop], definition, schemas, reached, None, depth + 1)


def test_a_property_that_cannot_say_there_isnt_one_is_reached_or_named(
    api: Any, spec: dict[str, Any]
) -> None:
    """the design open audit, kept from going stale.

    Every bare ``$ref`` to an object schema is either exercised by a response
    this module validates — in which case the parametrised test above vouches
    for it on today's fixtures — or named in :data:`UNREACHED` with the reason
    nothing can.
    """
    schemas = spec["components"]["schemas"]
    world = _world(api)
    reached: set[str] = set()

    for (method, path), call in sorted(CALLS.items()):
        response = call(api, world)
        if response.status_code >= 400:
            continue
        schema = response_schema(spec, method, path, response.status_code)
        if schema is None:
            continue
        _walk(response.json(), schema, schemas, reached)

    candidates = bare_object_refs(spec)
    unvouched = candidates - reached - set(UNREACHED)
    assert not unvouched, (
        "these properties cannot express absence and no response this module "
        f"makes reaches them, so nobody can say whether that is right: "
        f"{sorted(unvouched)}. Exercise one, or name it in UNREACHED."
    )

    stale = set(UNREACHED) & reached
    assert (
        not stale
    ), f"UNREACHED names properties a live response does reach: {sorted(stale)}"
    gone = set(UNREACHED) - candidates
    assert (
        not gone
    ), f"UNREACHED names properties that are no longer bare $refs: {sorted(gone)}"


def test_the_audit_list_still_matches_the_document(spec: dict[str, Any]) -> None:
    """A count, so a thirteenth instance cannot arrive unannounced.

    the design catalogued eleven bare ``$ref``s it left alone; 1.4.0 then added
    ``UnassessableSpecimen.specimen``, a twelfth, and 1.6.0 added
    ``PlateCoverageEntry.specimen``, a thirteenth that is required and so never
    has an absence to express. Independently
    enumerated here from the document rather than copied from the design, so the
    two can be compared rather than agreeing by construction.
    """
    assert bare_object_refs(spec) == {
        "CalendarFeed.filters",
        "CalendarFeedCreate.filters",
        "FieldNote.written_by",
        "FrostAlert.specimen",
        "MapLayer.calibration",
        "MorningRounds.weather",
        "Pin.specimen",
        "PlateCoverageEntry.specimen",
        "Specimen.location",
        "Specimen.species",
        "Task.specimen",
        "TaxonCandidate.source",
        "UnassessableSpecimen.specimen",
    }, (
        "the set of properties that cannot say 'there isn't one' has changed. "
        "If one was added, decide whether absence is a normal state for it "
        "before 1.x ships; if one was fixed, drop it from this list."
    )
