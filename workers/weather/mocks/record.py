"""Re-record the payloads in ``recorded/`` from the live services.

    python -m workers.weather.mocks.record --live # everything
    python -m workers.weather.mocks.record --live --only nws

Runs the real sources through the real fetcher and writes each payload to the
path :func:`recording_name` will look for, so the recordings and the routing
cannot drift apart. Nothing is edited on the way in: what the service said is
what lands on disk.

Note what it does **not** do — write a payload for a service that would not
answer. Open-Meteo's success payloads are missing from ``recorded/`` today
because its free tier answered this project with "Daily API request limit
exceeded" (that 429 body *is* recorded, and the ingest is tested against it).
The mock fetcher synthesises Open-Meteo's shape from the frozen fixtures
instead, stamped ``_synthetic``, and prefers a real recording the moment one
appears here. Running this from a host with quota is what makes one appear.

Without ``--live`` it reports what is on disk and what is missing, and touches
nothing — a dry run is the safe default for a script whose whole job is to
overwrite evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ..settings import get_settings
from ..sources.base import SourceUnavailable
from ..sources.http import HttpFetcher
from ..sources.openmeteo import DAILY_VARIABLES, HOURLY_VARIABLES
from .fetcher import RECORDED_DIR

#: The site everything is recorded for (``fixtures/site.json``).
LATITUDE = 39.7684
LONGITUDE = -86.1581

#: The NWS grid cell those coordinates resolve to. Hard-coded rather than
#: looked up so a re-record does not silently move to another cell — if NWS
#: re-grids, the ``/points`` recording is what should show it first.
GRID = "IND/58,69"
STATION = "KIND"

#: ``(relative path, kind, url, params)``. The zone here is the one the site's
#: coordinates actually resolve to; ``fixtures/site.json`` names INZ050, which
#: is a different county — see PROVENANCE.md.
TARGETS: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "nws/points__the-grounds.json",
        "nws",
        f"https://api.weather.gov/points/{LATITUDE},{LONGITUDE}",
        {},
    ),
    (
        "nws/forecast__the-grounds.json",
        "nws",
        f"https://api.weather.gov/gridpoints/{GRID}/forecast",
        {},
    ),
    (
        "nws/forecast-hourly__the-grounds.json",
        "nws",
        f"https://api.weather.gov/gridpoints/{GRID}/forecast/hourly",
        {},
    ),
    (
        "nws/observation__kind-latest.json",
        "nws",
        f"https://api.weather.gov/stations/{STATION}/observations/latest",
        {},
    ),
    (
        "nws/alerts__inz047.json",
        "nws",
        "https://api.weather.gov/alerts/active",
        {"zone": "INZ047"},
    ),
    (
        # Nationwide, filtered to the event: the site's own zone is quiet
        # almost every day, so this is the only way to keep a *populated*
        # advisory payload under test. It is a real NWS advisory; it simply
        # covers somebody else's county, and the tests say so where it matters.
        "nws/alerts__frost-advisory-active.json",
        "nws",
        "https://api.weather.gov/alerts/active",
        {"event": "Frost Advisory"},
    ),
    (
        "open_meteo/forecast__the-grounds.json",
        "open_meteo",
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "timezone": "UTC",
            "forecast_days": 10,
            "wind_speed_unit": "kmh",
            "hourly": ",".join(HOURLY_VARIABLES),
            "daily": ",".join(DAILY_VARIABLES),
        },
    ),
    (
        "open_meteo/recent__the-grounds.json",
        "open_meteo",
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "timezone": "UTC",
            "past_days": 2,
            "forecast_days": 1,
            "wind_speed_unit": "kmh",
            "hourly": ",".join(HOURLY_VARIABLES),
        },
    ),
)

#: Trimmed on the way in, because the live response is 160 kB of repetition and
#: a recording nobody can read in a diff is a recording nobody reviews. The trim
#: is declared inside the file it applies to.
TRIM_PERIODS = {"nws/forecast-hourly__the-grounds.json": 48}


async def record(only: str | None, recorded_dir: Path) -> int:
    """Fetch every target and write it. Returns the number of failures."""
    settings = get_settings()
    failures = 0
    async with HttpFetcher(settings) as fetcher:
        for relative, kind, url, params in TARGETS:
            if only and not relative.startswith(only):
                continue
            try:
                result = await fetcher.get_json(kind, url, params)
            except SourceUnavailable as exc:
                # Recorded as a failure in the log, never as an empty payload:
                # a source that is down must not leave a file that looks like a
                # source that said nothing.
                print(f"  FAILED  {relative}: {exc}")
                failures += 1
                continue

            payload = _trim(relative, result.payload)
            path = recorded_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=1) + "\n")
            print(f"  wrote   {relative}  ({path.stat().st_size:,} bytes)")
    return failures


def _trim(relative: str, payload: Any) -> Any:
    limit = TRIM_PERIODS.get(relative)
    if limit is None or not isinstance(payload, dict):
        return payload
    properties = payload.get("properties")
    if not isinstance(properties, dict) or not isinstance(
        properties.get("periods"), list
    ):
        return payload
    full = len(properties["periods"])
    properties["periods"] = properties["periods"][:limit]
    properties["_trimmed"] = {
        "note": (
            f"Recording trimmed to the first {limit} hourly periods; the live "
            f"response carried {full}. Shape is unchanged."
        )
    }
    return payload


def report(recorded_dir: Path) -> None:
    """What is on disk, and what a ``--live`` run would add."""
    print(f"Recordings in {recorded_dir}:")
    for relative, _kind, _url, _params in TARGETS:
        path = recorded_dir / relative
        state = f"{path.stat().st_size:,} bytes" if path.exists() else "MISSING"
        print(f"  {relative:44} {state}")
    print("\nNothing was fetched. Pass --live to re-record.")
    print("See recorded/PROVENANCE.md for why the Open-Meteo successes are absent.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually fetch and overwrite. Without it, nothing is written.",
    )
    parser.add_argument(
        "--only", help="limit to one prefix, e.g. 'nws' or 'open_meteo'"
    )
    parser.add_argument("--dir", type=Path, default=RECORDED_DIR)
    args = parser.parse_args(argv)

    if not args.live:
        report(args.dir)
        return 0

    print("Re-recording from the live services. Update PROVENANCE.md and")
    print("RECORDED_ON in fetcher.py afterwards — a citation that claims to be")
    print("fresh when it is not is worse than no citation.\n")
    failures = asyncio.run(record(args.only, args.dir))
    if failures:
        print(f"\n{failures} target(s) did not answer. Nothing was written for them.")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - a command, not a library
    sys.exit(main())
