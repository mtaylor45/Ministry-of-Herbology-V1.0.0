"""Every parts of the project must be able to run the whole stack on mocks."""


def test_morning_rounds_answers(client):
    body = client.get("/api/v1/tending/rounds").json()
    assert "due" in body and "satisfied" in body and "alerts" in body


def test_every_task_pairs_a_themed_title_with_a_plain_one(client):
    """the design, checked on the wire and not just in the schema."""
    body = client.get("/api/v1/tending/rounds").json()
    for task in body["due"] + body["satisfied"]:
        assert task["title"] and task["plain_title"]
        assert task["title"] != task["plain_title"], task


def test_rain_satisfied_waterings_are_shown_not_hidden(client):
    """The plan is explicit: rain marks a task satisfied, it does not delete it."""
    body = client.get("/api/v1/tending/rounds").json()
    for task in body["satisfied"]:
        assert task["status"] == "satisfied"
        assert task["satisfied_by"] == "rain"


def test_register_lists_specimens_with_display_names(client):
    body = client.get("/api/v1/specimens").json()
    assert body["total"] == 12
    assert all(item["display_name"] for item in body["items"])


def test_register_filters_by_location_and_outdoors(client):
    outdoor = client.get("/api/v1/specimens", params={"outdoor": True}).json()
    assert outdoor["total"] > 0
    assert all(item["is_outdoor"] for item in outdoor["items"])


def test_toxicity_filter_works(client):
    """Toxicity flags for children and pets are a safety feature, not a nicety."""
    toxic = client.get("/api/v1/specimens", params={"toxic_to_pets": True}).json()
    assert toxic["total"] > 0
    for item in toxic["items"]:
        detail = client.get(f"/api/v1/species/{item['species']['id']}").json()
        assert detail["toxic_to_pets"] is True


def test_care_values_carry_sources_and_confidence(client):
    species = client.get("/api/v1/species").json()
    seen_unknown = False
    for entry in species:
        for value in client.get(f"/api/v1/species/{entry['id']}/care-values").json():
            assert value["confidence"] in {"high", "medium", "low", "unknown"}
            if value["source"] is None:
                assert value["confidence"] == "unknown"
                seen_unknown = True
            else:
                assert value["source"]["url"]
    assert seen_unknown, "fixtures should exercise the uncited case too"


def test_covered_locations_do_not_collect_rain(client):
    """f_cover = 0 under a porch; the water balance must reflect it."""
    specimens = client.get("/api/v1/specimens", params={"outdoor": True}).json()[
        "items"
    ]
    covered = [s for s in specimens if s["location"]["is_covered"]]
    assert covered, "fixtures must include a covered outdoor location"
    balance = client.get(f"/api/v1/almanac/water-balance/{covered[0]['id']}").json()
    assert all(day["precip_mm"] == 0 for day in balance["days"])


def test_uncovered_outdoor_plants_do_collect_rain(client):
    specimens = client.get("/api/v1/specimens", params={"outdoor": True}).json()[
        "items"
    ]
    open_air = [s for s in specimens if not s["location"]["is_covered"]]
    balance = client.get(f"/api/v1/almanac/water-balance/{open_air[0]['id']}").json()
    assert any(day["precip_mm"] > 0 for day in balance["days"])


def test_almanac_serves_forecast_and_all_three_history_windows(client, repo_root):
    import json

    site_id = json.loads((repo_root / "fixtures" / "site.json").read_text())["id"]
    daily = client.get(
        "/api/v1/almanac/forecast", params={"site_id": site_id, "horizon": "daily"}
    ).json()
    assert len(daily) == 10, "the plan calls for a 10-day forecast"
    hourly = client.get(
        "/api/v1/almanac/forecast", params={"site_id": site_id, "horizon": "hourly"}
    ).json()
    assert len(hourly) == 24, "the plan calls for a 1-day forecast"
    for window, expected in (("1d", 1), ("7d", 7), ("30d", 30)):
        series = client.get("/api/v1/almanac/history", params={"window": window}).json()
        assert len(series["times"]) == expected == len(series["values"])


def test_frost_alerts_only_ever_name_outdoor_plants(client):
    for alert in client.get("/api/v1/almanac/frost").json()["alerts"]:
        assert alert["specimen"]["is_outdoor"], alert
        assert alert["action"] in {"bring_indoors", "cover", "monitor"}


def test_a_plant_the_frost_guard_cannot_judge_is_still_named(client):
    """the design envelope earns its keep here.

    Silence from the frost guard has two very different meanings — "nothing is
    at risk" and "I could not tell" — and a bare list of alerts renders both the
    same way. Every unassessable entry carries the reason it could not be judged.
    """
    report = client.get("/api/v1/almanac/frost").json()
    assert set(report) == {"alerts", "unassessable"}
    for row in report["unassessable"]:
        assert row["specimen_id"], row
        assert row["reason"].strip(), "a plant is never set aside without a reason"


def test_calendar_feed_is_a_parseable_vcalendar_with_stable_uids(client):
    feeds = client.get("/api/v1/tending/feeds").json()
    assert feeds[0]["webcal_url"].startswith("webcal://")
    body = client.get(feeds[0]["https_url"].replace("http://localhost:8000", "")).text
    assert body.startswith("BEGIN:VCALENDAR")
    assert body.rstrip().endswith("END:VCALENDAR")
    uids = [line for line in body.splitlines() if line.startswith("UID:")]
    assert uids and len(uids) == len(set(uids)), "ICS UIDs must be unique and stable"


def test_every_specimen_has_a_pin_on_a_layer(client):
    layers = {layer["id"] for layer in client.get("/api/v1/grounds/layers").json()}
    pins = client.get("/api/v1/grounds/pins").json()
    specimens = client.get("/api/v1/specimens").json()
    assert len(pins) == specimens["total"]
    for pin in pins:
        assert pin["layer_id"] in layers
        assert pin["px"]["x"] > 0 and pin["px"]["y"] > 0


def test_a_nickname_is_not_given_an_article(client):
    """ "Tend Sour Bertram", not "Tend the Sour Bertram"."""
    body = client.get("/api/v1/tending/rounds").json()
    for task in body["due"] + body["satisfied"]:
        specimen = client.get(f"/api/v1/specimens/{task['specimen']['id']}").json()
        if specimen["nickname"]:
            assert f"the {specimen['nickname']}" not in task["plain_title"], task[
                "plain_title"
            ]
            assert specimen["nickname"] in task["plain_title"]


def test_a_frost_alert_reports_the_night_it_actually_names(client, repo_root):
    """An alert whose stated low belongs to a different night teaches distrust."""
    import json

    scenario = json.loads(
        (repo_root / "fixtures" / "scenarios" / "frost.json").read_text()
    )
    lows = {day["date"]: day["tmin_c"] for day in scenario["days"]}
    for alert in client.get("/api/v1/almanac/frost").json()["alerts"]:
        assert alert["forecast_low_c"] == lows[alert["night_of"]]
        assert (
            alert["forecast_low_c"] <= alert["threshold_c"]
        ), "an alert must only fire below its own threshold"
