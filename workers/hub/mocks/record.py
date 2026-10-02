"""Record ``recorded/`` from a live Home Assistant — the hub.

    python -m workers.hub.mocks.record # dry run: what is missing
    python -m workers.hub.mocks.record --live # fetch and write

Runs the real source through the real fetcher and writes each payload to the
path :func:`workers.hub.mocks.fetcher.recording_name` will look for, so the
recordings and the routing cannot drift apart. Nothing is edited on the way in:
what Home Assistant said is what lands on disk.

Unlike the weather engine's equivalent, this one will be run against **your own
house**, which changes two things.

*It needs your credentials and does not want them anywhere else.*
``MOH_HA_BASE_URL`` and ``MOH_HA_TOKEN`` come from the environment. Nothing
here prints them, and ``--live`` refuses to start if either is missing rather
than producing a 401 payload that looks like a recording of something.

*What it writes is a map of your home.* Entity ids, room names, and every
device Home Assistant knows about. The script says so before it writes and
again after, because the natural next step is ``git add`` and this repository
is public.

Without ``--live`` it touches nothing. A dry run is the safe default for a
script whose whole job is to overwrite evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ..settings import get_settings
from ..sources.base import HubUnavailable
from ..sources.http import HomeAssistantFetcher
from .fetcher import RECORDED_DIR

#: ``(relative path, kind, request path)``. Matches ``recording_name``.
TARGETS: tuple[tuple[str, str, str], ...] = (
    ("home_assistant/api__root.json", "home_assistant", "/"),
    ("home_assistant/states__all.json", "home_assistant", "/states"),
)

WARNING = (
    "These files describe your home: every entity id, every room name, every "
    "device Home Assistant knows about. Read them before committing them."
)


def missing(recorded_dir: Path) -> list[str]:
    return [name for name, _, _ in TARGETS if not (recorded_dir / name).exists()]


async def record(recorded_dir: Path) -> int:
    settings = get_settings()
    if not settings.is_configured:
        print(
            "MOH_HA_BASE_URL and MOH_HA_TOKEN must both be set to record.",
            file=sys.stderr,
        )
        return 2

    written = 0
    async with HomeAssistantFetcher(settings) as fetcher:
        for name, kind, path in TARGETS:
            try:
                result = await fetcher.get_json(kind, path)
            except HubUnavailable as exc:
                # Printed and skipped rather than fatal: one endpoint a
                # deployment does not expose should not cost the others.
                print(f"  skip {name}: {exc}", file=sys.stderr)
                continue
            target = recorded_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_dump(result.payload))
            print(f"  wrote {name}")
            written += 1
    if written:
        print(f"\n{WARNING}")
    return 0 if written else 1


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually fetch and overwrite. Without it, nothing is written.",
    )
    parser.add_argument("--recorded-dir", type=Path, default=RECORDED_DIR)
    args = parser.parse_args(argv)

    if not args.live:
        absent = missing(args.recorded_dir)
        print(f"recordings directory: {args.recorded_dir}")
        for name, _, path in TARGETS:
            mark = "missing" if name in absent else "present"
            print(f"  [{mark}] {name}  <- GET /api{path}")
        print("\nRe-run with --live to fetch. " + WARNING)
        return 0
    return asyncio.run(record(args.recorded_dir))


if __name__ == "__main__":  # pragma: no cover - a command, not a library
    raise SystemExit(main())
