"""Today's rounds and tonight's frost, with no API running — the hub.

The build-against-mocks rule: every service ships a mock matching the contract, so no agent waits on
another and the whole stack runs offline. the earlier version of this was
:mod:`workers.hub.mocks.fetcher`, which synthesises Home Assistant. This is the
other side: what the *Ministry* would have told the notification jobs, in the
shapes ``contracts/openapi/openapi.yaml`` specifies for ``MorningRounds`` and
``FrostReport``.

## This is not a second scheduler, and must never become one

The scheduler owns care rules, and the no-invented-plant-facts rule forbids inventing plant facts.
So
nothing here decides what a plant needs. Every synthesised task is stamped:

* ``confidence: "unknown"``,
* ``degraded: true``,
* a ``degradations[]`` entry that says in plain words it is mock data.

Which means the mock stack demonstrates the notification path **through the
hedging branch** — the notification a household sees in mock mode reads "this
is an estimate", because that is exactly what it is. A mock that produced
confident-looking tasks would be this package quietly asserting care facts it
has no citation for, and would test the one code path that must not be the
default.

## The frost half is read, not invented

``fixtures/scenarios/frost.json`` is the test suite's and already contains the
nights, the temperatures and an NWS Freeze Warning headline. The alerts here
are derived from that file against the outdoor specimens in
``fixtures/specimens/specimens.json``, with the scenario's own ``expect`` block
as the rule — not a frost model of this package's own.

## One derivation this package would rather not be making

``fixtures/`` has no ``members`` file, and ``api/inventory``'s mock repository
carries a single in-code Keeper whose ``notify_prefs`` is ``{}``. A household
with no notify service configured receives nothing, correctly — and a mock
stack that can never demonstrate a notification is a mock stack nobody can
review the feature in. So :meth:`MockMinistryReader.members` returns the inventory API's Keeper,
with the inventory API's id and the inventory API's name, and attaches a synthetic ``notify_prefs``
marked as
such. A ``fixtures/members/members.json`` would replace it; that is a request
to the maintainers and the test suite, in the releases note.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..settings import HubSettings, get_settings

#: The member ``api/inventory``'s fixture repository serves, copied rather than
#: invented so the mock stack agrees with itself across two parts of the project.
KEEPER_ID = "01890050-0000-7000-8000-000000000001"
KEEPER_NAME = "Keeper"

#: The notify service the mock Keeper is given. ``mobile_app_<device>`` is Home
#: Assistant's own naming for a companion-app target, and this one is plainly
#: not a real device.
MOCK_NOTIFY_SERVICE = "notify.mobile_app_mock_device"

#: Why every synthesised task is hedged. The sentence is written to be read by
#: whoever gets the notification, because ``Degradation.detail`` is specified
#: as "a plain sentence, written to be shown to the reader as-is".
MOCK_DEGRADATION = {
    "code": "mock_schedule",
    "detail": (
        "These tasks come from the offline fixtures, not from the scheduler, "
        "so treat them as a demonstration rather than as advice."
    ),
    "caps_at": "unknown",
}


def _synthetic(source: str) -> dict[str, Any]:
    return {
        "_synthetic": {
            "from": source,
            "note": (
                "Mock mode. Built in the contract's shape from the frozen "
                "fixtures, not fetched from the Ministry API."
            ),
        }
    }


@lru_cache
def _read(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else []


class MockMinistryReader:
    """A :class:`~workers.hub.notify.state.MinistryReader` that opens no socket."""

    is_mock = True

    def __init__(
        self, settings: HubSettings | None = None, today: date | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self._today = today

    # ------------------------------------------------------------- fixtures

    def _fixture(self, *parts: str) -> Any:
        return _read(self.settings.fixtures_dir.joinpath(*parts))

    def _specimens(self) -> list[dict[str, Any]]:
        rows = self._fixture("specimens", "specimens.json")
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    def _species_names(self) -> dict[str, str]:
        rows = self._fixture("species", "species.json")
        if not isinstance(rows, list):
            return {}
        return {
            str(row.get("id")): str(
                row.get("common_name") or row.get("scientific_name") or ""
            )
            for row in rows
            if isinstance(row, Mapping)
        }

    def today(self) -> date:
        return self._today or datetime.now(UTC).date()

    # ------------------------------------------------------------- the reads

    async def members(self) -> list[dict[str, Any]]:
        """The inventory API's Keeper, with a notify service attached and labelled as mock."""
        return [
            {
                "id": KEEPER_ID,
                "name": KEEPER_NAME,
                "role": "keeper",
                "notify_prefs": {
                    "home_assistant": {
                        "service": MOCK_NOTIFY_SERVICE,
                        "rounds": True,
                        "frost": True,
                        "health": True,
                        "rounds_hour": 7,
                        "quiet_hours": [22, 7],
                    },
                    **_synthetic("workers/hub/mocks/ministry.py"),
                },
            }
        ]

    async def specimens(self) -> list[dict[str, Any]]:
        """The fixture specimens, as ``GET /specimens`` would list them."""
        return [
            {"id": str(row["id"]), "status": row.get("status") or "healthy"}
            for row in self._specimens()
            if row.get("id")
        ]

    async def rounds(self) -> dict[str, Any]:
        """Three indoor waterings and one plant nobody could schedule.

        The last one is the point of the fixture rather than padding. A plant
        with no interval anywhere gets no task, and a plant with no task looks
        exactly like a plant that needs nothing — so the mock world contains
        one, and the notification the mock stack produces has to account for it.
        """
        names = self._species_names()
        specimens = [row for row in self._specimens() if not row.get("is_outdoor")]
        due: list[dict[str, Any]] = []
        for index, row in enumerate(specimens[:3]):
            due.append(self._task(row, names, index))
        unscheduled = [
            {
                "specimen_id": str(row["id"]),
                "reason": "no watering interval is cited for this species",
            }
            for row in specimens[3:4]
        ]
        return {
            "date": self.today().isoformat(),
            "greeting": "Good morning. The rounds await.",
            "due": due,
            "satisfied": [],
            "alerts": [],
            "unscheduled": unscheduled,
            **_synthetic("fixtures/specimens/specimens.json"),
        }

    async def frost(self) -> dict[str, Any]:
        """The frost scenario's coldest night, against the outdoor specimens."""
        scenario = self._fixture("scenarios", "frost.json")
        scenario = scenario if isinstance(scenario, Mapping) else {}
        days = [day for day in (scenario.get("days") or ()) if isinstance(day, Mapping)]
        coldest = min(
            (day for day in days if isinstance(day.get("tmin_c"), (int, float))),
            key=lambda day: float(day["tmin_c"]),
            default=None,
        )
        if coldest is None:
            return {
                "alerts": [],
                "unassessable": [],
                **_synthetic("fixtures/scenarios/frost.json"),
            }

        headline = ""
        for advisory in scenario.get("advisories") or ():
            if isinstance(advisory, Mapping) and advisory.get("headline"):
                headline = str(advisory["headline"])
                break

        names = self._species_names()
        outdoor = [row for row in self._specimens() if row.get("is_outdoor")]
        alerts = [
            {
                "id": f"01890090-0000-7000-8000-{index:012d}",
                "specimen": self._brief(row, names),
                "night_of": str(coldest.get("date")),
                "forecast_low_c": float(coldest["tmin_c"]),
                # the design frost guard uses a margin above freezing; the
                # number here is the scenario's, not a threshold this package
                # computed.
                "threshold_c": 0.0,
                "action": "bring_indoors" if row.get("in_container") else "cover",
                "advisory": headline or None,
                "task_id": None,
                "state": "open",
                "confidence": "medium",
                "degraded": True,
                "degradations": [MOCK_DEGRADATION],
            }
            for index, row in enumerate(outdoor[:4])
        ]
        return {
            "alerts": alerts,
            "unassessable": [],
            **_synthetic("fixtures/scenarios/frost.json"),
        }

    # -------------------------------------------------------------- helpers

    def _brief(
        self, row: Mapping[str, Any], names: Mapping[str, str]
    ) -> dict[str, Any]:
        species = names.get(str(row.get("species_id")), "")
        return {
            "id": str(row.get("id")),
            "nickname": row.get("nickname") or None,
            "display_name": str(row.get("nickname") or species or "a plant"),
            "species": species or None,
        }

    def _task(
        self, row: Mapping[str, Any], names: Mapping[str, str], index: int
    ) -> dict[str, Any]:
        brief = self._brief(row, names)
        display = str(brief["display_name"])
        subject = display if row.get("nickname") else f"the {display.lower()}"
        due_at = datetime.combine(
            self.today(), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=7)
        return {
            "id": f"01890080-0000-7000-8000-{index:012d}",
            "specimen": brief,
            "task_type": "water",
            "due_at": due_at.isoformat(),
            "all_day": True,
            "status": "due",
            "satisfied_by": None,
            "amount_ml": None,
            "priority": "normal",
            # The original-theme rule pair, in the scheduler's own wording. Not re-themed here:
            # ``api/tending/titles.py`` is where the pairing lives and a second
            # copy of it is a second thing to drift.
            "title": f"Tend {subject}",
            "plain_title": f"Water {subject}",
            "detail": MOCK_DEGRADATION["detail"],
            "deep_link": f"/specimen/{brief['id']}/tending",
            "confidence": "unknown",
            "degraded": True,
            "degradations": [MOCK_DEGRADATION],
        }
