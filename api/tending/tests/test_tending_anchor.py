"""an earlier release: a new plant is counted from the day it was registered, not from 2024.

The maintainer's call of 2 Oct. ``anchor_for`` fell back from the last
completion to ``acquired_on`` to ``EPOCH`` (2024-01-01), so a plant added today
with no acquired date arrived some 640 days overdue. The registration day —
``specimen.created_at`` in the site's timezone — now sits before ``EPOCH``.

The fixture household must not move: every fixture plant carries an acquired
date, so giving each one a registration day changes nothing, and the last test
here holds the whole mock round to that, byte for byte.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tending import schemas, service
from tending.domain import (
    EPOCH,
    Rule,
    Subject,
    anchor_for,
    generate,
    registered_on,
)
from tending.repository import TaskQuery

TODAY = date(2026, 10, 2)
WEEKLY = Rule(id="rule-7", task_type="water", base_interval_days=7)


def newcomer(**overrides: Any) -> Subject:
    base: dict[str, Any] = {
        "specimen_id": "01890040-0000-7000-8000-0000000000aa",
        "display_name": "Newcomer",
        "has_nickname": True,
        "is_outdoor": False,
        "in_container": True,
        "container_litres": 5.0,
        "acquired_on": None,
        "added_on": TODAY,
    }
    base.update(overrides)
    return Subject(**base)


def test_a_plant_added_today_on_a_weekly_rule_is_due_in_seven_days():
    occurrences = generate(
        newcomer(), [WEEKLY], today=TODAY, horizon_days=30, latitude=39.77
    )
    assert occurrences
    assert occurrences[0].due_on == TODAY + timedelta(days=7)
    assert all(o.due_on > TODAY for o in occurrences), "nothing is overdue"


def test_before_s10_the_same_plant_was_hundreds_of_days_overdue():
    """The bug, kept as a test so the fallback cannot quietly return."""
    occurrences = generate(
        newcomer(added_on=None), [WEEKLY], today=TODAY, horizon_days=30, latitude=0
    )
    assert occurrences[0].anchor == EPOCH
    assert occurrences[0].due_on <= TODAY
    assert (TODAY - EPOCH).days > 600


def test_the_anchor_order_is_completion_acquisition_registration_epoch():
    completed, acquired, added = date(2026, 9, 1), date(2025, 5, 5), date(2026, 3, 3)
    assert anchor_for(newcomer(acquired_on=acquired, added_on=added), completed) == (
        completed
    )
    assert anchor_for(newcomer(acquired_on=acquired, added_on=added), None) == acquired
    assert anchor_for(newcomer(added_on=added), None) == added
    assert anchor_for(newcomer(added_on=None), None) == EPOCH


def test_the_registration_day_is_the_sites_calendar_day():
    late_evening = datetime(2026, 10, 2, 1, 30, tzinfo=UTC)  # 9:30 pm on 1 Oct
    assert registered_on(late_evening, "America/Indiana/Indianapolis") == date(
        2026, 10, 1
    )
    assert registered_on(late_evening, "Europe/London") == date(2026, 10, 2)
    assert registered_on(late_evening, None) == date(2026, 10, 2)
    assert registered_on(late_evening, "Not/AZone") == date(2026, 10, 2)
    assert registered_on(None, "Europe/London") is None


def test_the_registration_anchor_is_stable_across_regenerations():
    """The reason the anchor is never "today": identities must not move."""
    first = generate(newcomer(), [WEEKLY], today=TODAY, horizon_days=30, latitude=0)
    later = generate(
        newcomer(),
        [WEEKLY],
        today=TODAY + timedelta(days=3),
        horizon_days=30,
        latitude=0,
    )
    shared = {o.task_id for o in first} & {o.task_id for o in later}
    assert shared, "the same occurrences keep the same ids a few days on"


# -------------------------------------------- the fixture household is unmoved


def _mock_round(*, registered: datetime | None) -> str:
    """The full mock round and task list on three days, as one JSON string."""
    from tending.fixture_repository import FixtureRepository

    async def collect() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for day in (date(2026, 10, 2), date(2026, 1, 15), date(2026, 6, 1)):
            repo = FixtureRepository()
            if registered is not None:
                for specimen in repo._specimens:
                    specimen["created_at"] = registered.isoformat()
            out[day.isoformat()] = await service.morning_rounds(repo, on=day)
            out[f"{day.isoformat()}/tasks"] = [
                schemas.task_out(row) for row in await repo.tasks(TaskQuery())
            ]
        return out

    return json.dumps(asyncio.run(collect()), sort_keys=True, default=str)


def test_every_fixture_plant_carries_an_acquired_date():
    """The precondition the next test depends on, stated rather than assumed."""
    from app import fixtures

    assert all(specimen.get("acquired_on") for specimen in fixtures.specimens())


def test_the_fixture_households_round_is_byte_identical_with_registration_days():
    """Registered today, every fixture plant still schedules as it did.

    Today is the hardest case: the registration day is as far from each
    acquired date as it can be, so if the new fallback leaked past
    ``acquired_on`` anywhere it would move every anchor in the household.
    """
    unregistered = _mock_round(registered=None)
    registered_today = _mock_round(registered=datetime.now(UTC))
    assert registered_today == unregistered
