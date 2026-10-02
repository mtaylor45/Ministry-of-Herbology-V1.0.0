"""The calendar-push overlay that ``make stack-deploy`` adds. The deployment.

``docker stack deploy`` resets a service to what its files list, so a
``moh_caldav_<feed_id>`` secret added to the API by hand is dropped by the next
deploy unless something lists it. ``scripts/caldav_overlay.sh`` is that
something; these check what it lists and what it leaves alone.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "caldav_overlay.sh"
FEED_A = "moh_caldav_0189a0f0-0000-7000-8000-000000000001"
FEED_B = "moh_caldav_0189a0f0-0000-7000-8000-000000000002"


def overlay(names: list[str]) -> str:
    return subprocess.run(
        ["sh", str(SCRIPT)],
        input="".join(f"{n}\n" for n in names),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_every_feed_secret_is_listed_on_the_api_and_declared_external() -> None:
    doc = yaml.safe_load(overlay(["moh_db_password", FEED_A, "moh_ha_token", FEED_B]))
    assert doc["services"] == {"api": {"secrets": [FEED_A, FEED_B]}}
    assert doc["secrets"] == {FEED_A: {"external": True}, FEED_B: {"external": True}}


def test_no_feed_secret_means_no_overlay_at_all() -> None:
    assert overlay(["moh_db_password", "moh_tls_cert"]) == ""
    assert overlay([]) == ""


def test_only_the_exact_name_shape_is_taken() -> None:
    """A name with spaces or YAML in it is not a feed's, and is not echoed."""
    out = overlay(
        ["moh_caldav_", "moh_caldav_x: {}", "xmoh_caldav_1", "moh_caldav_ok-1"]
    )
    assert yaml.safe_load(out)["services"]["api"]["secrets"] == ["moh_caldav_ok-1"]
