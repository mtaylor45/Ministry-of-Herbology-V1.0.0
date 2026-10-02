"""Whether the hub is actually answering — the hub.

the design made Home Assistant a hard dependency, so a silent adapter is this
parts of the project's failure mode. These tests are about the two ways silence can be
made visible: a status that is computed against a clock rather than read off
the presence of a value, and an error message that is safe to put on a screen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from workers.hub.health import (
    MASK,
    IntegrationHealth,
    SourceHealth,
    health_report,
    redact,
)
from workers.hub.mapping import SensorSource

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
TOKEN = "eyJhbGciOiJIUzI1NiJ9.aVeryLongLivedAccessToken.signaturegoeshere"


def integration(**kwargs) -> IntegrationHealth:
    defaults = {"id": "i-1", "kind": "home_assistant", "name": "Home Assistant"}
    return IntegrationHealth(**{**defaults, **kwargs})


def test_a_success_that_has_gone_cold_is_not_health():
    """The silent case: nothing failed, and nothing happened either.

    ``last_ok_at`` from four hours ago with no error since is not a working
    adapter — it is one that stopped running, which is exactly what a flat
    line in the Almanac looks like from the other end.
    """
    fresh = integration(last_ok_at=NOW - timedelta(minutes=5))
    cold = integration(last_ok_at=NOW - timedelta(hours=4))
    assert fresh.status(NOW) == "ok"
    assert cold.status(NOW) == "stale"


def test_an_error_a_later_success_survived_is_degraded_not_down():
    row = integration(last_ok_at=NOW - timedelta(minutes=2), last_error="one timeout")
    assert row.status(NOW) == "degraded"


def test_an_error_with_no_recent_success_is_down():
    row = integration(last_ok_at=NOW - timedelta(hours=4), last_error="refused")
    assert row.status(NOW) == "down"


def test_a_setup_step_is_not_a_fault():
    """Showing an unconfigured integration as broken trains people to ignore
    the row, which costs on the day it means something."""
    assert integration(configured=False).status(NOW) == "unconfigured"
    assert integration(enabled=False, last_error="boom").status(NOW) == "disabled"


def test_a_configured_integration_that_has_never_reported_is_unknown():
    assert integration().status(NOW) == "unknown"


def test_a_gap_reads_as_no_recent_reading_rather_than_as_a_flat_line():
    """the design asks for this phrase by name."""
    source = SourceHealth(
        source_id="s-1",
        name="Study",
        enabled=True,
        poll_seconds=300,
        last_seen_at=NOW - timedelta(hours=3),
    )
    assert source.status(NOW) == "no recent reading"


def test_a_poll_landing_a_second_late_does_not_make_a_healthy_room_flicker():
    """Three intervals, not one. The Office screen is looked at continuously."""
    source = SourceHealth(
        source_id="s-1",
        name="Study",
        enabled=True,
        poll_seconds=300,
        last_seen_at=NOW - timedelta(seconds=310),
    )
    assert source.status(NOW, floor_s=0.0) == "reporting"


def test_a_slow_probe_gets_a_proportionate_tolerance():
    """A probe that reports hourly must not be called dead at 31 minutes."""
    hourly = SourceHealth(
        source_id="s-1",
        name="Mandrake",
        enabled=True,
        poll_seconds=3600,
        last_seen_at=NOW - timedelta(minutes=45),
        specimen_id="specimen-1",
    )
    assert hourly.status(NOW, floor_s=1800.0) == "reporting"


def test_a_source_that_has_never_reported_says_so_distinctly():
    source = SourceHealth(
        source_id="s-1", name="Study", enabled=True, poll_seconds=300, last_seen_at=None
    )
    assert source.status(NOW) == "never reported"


def test_the_report_keeps_a_new_install_apart_from_a_broken_one():
    """A source configured four minutes ago and a thermostat that went quiet
    overnight must not share a list, or the alarming list is the one people
    learn to ignore."""
    report = health_report(
        [integration(last_ok_at=NOW)],
        [
            SourceHealth("s-1", "Study", True, 300, None),
            SourceHealth("s-2", "Kitchen Sill", True, 300, NOW - timedelta(hours=5)),
        ],
        now=NOW,
    )
    assert report["awaiting"] == ["Study"]
    assert report["problems"] == ["Kitchen Sill"]
    assert report["ok"] is False


def test_a_household_that_has_configured_nothing_is_not_broken():
    report = health_report([integration(configured=False)], [], now=NOW)
    assert report["ok"] is True
    assert report["configured"] is False


def test_a_configured_hub_that_has_never_reported_is_a_problem():
    """A worker that is not running looks exactly like this, and nothing else
    in the system will notice."""
    report = health_report([integration(last_ok_at=None)], [], now=NOW)
    assert report["problems"] == ["Home Assistant"]
    assert report["ok"] is False


@pytest.mark.parametrize(
    "message",
    [
        f"Authorization: Bearer {TOKEN}",
        f"GET http://user:{TOKEN}@hub.invalid/api/states failed",
        f"token={TOKEN}",
        f"connection refused; tried {TOKEN}",
    ],
)
def test_nothing_credential_shaped_reaches_the_column_the_office_renders(message):
    scrubbed = redact(message, [TOKEN])
    assert TOKEN not in scrubbed
    assert MASK in scrubbed


def test_a_credential_this_deployment_does_not_hold_is_still_caught():
    """The interesting case is the one nobody labelled — a credential somebody
    put in MOH_HA_BASE_URL, which we never see as a value of our own."""
    scrubbed = redact("GET https://admin:hunter2XYZ@hub.invalid/api failed", [])
    assert "hunter2XYZ" not in scrubbed
    assert "hub.invalid" in scrubbed


def test_redaction_leaves_an_ordinary_error_readable():
    """A scrub that mangles every message is a scrub people route around."""
    message = "home_assistant: Home Assistant has no sensor.study_temperature"
    assert redact(message, [TOKEN]) == message


def test_redaction_passes_none_and_empty_through():
    assert redact(None, [TOKEN]) is None
    assert redact("", [TOKEN]) == ""


def test_an_integration_row_reads_back_from_the_database_shape():
    row = IntegrationHealth.from_row(
        {
            "id": "i-1",
            "kind": "home_assistant",
            "name": "Home Assistant",
            "enabled": True,
            "last_ok_at": "2026-06-15T11:58:00+00:00",
            "last_error": None,
        }
    )
    assert row.status(NOW) == "ok"
    assert row.to_dict(NOW)["last_ok_at"] == "2026-06-15T11:58:00+00:00"


def test_source_health_is_built_from_the_mapping_row():
    source = SensorSource(
        id="s-1",
        name="Study",
        poll_seconds=600,
        last_seen_at=NOW - timedelta(minutes=5),
        location_id="location-1",
    )
    assert SourceHealth.from_source(source).status(NOW) == "reporting"


def test_a_missing_soil_sensor_is_never_reported_as_a_fault():
    """the model-only path is the shipping path, not a degraded one.

    A warning that fires on every plant every day is a warning nobody reads on
    the day it means something — the same rule the weather engine holds to in ``quality.py``.
    """
    report = health_report([integration(last_ok_at=NOW)], [], now=NOW)
    assert report["problems"] == []
    assert "soil" not in str(report).lower()
