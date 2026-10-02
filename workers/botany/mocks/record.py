"""Re-record the payloads in ``recorded/`` from the live services.

    python -m workers.botany.mocks.record # every species below
    python -m workers.botany.mocks.record "Rosa gallica" # just one

Runs the real connectors through the real fetcher and writes each payload to the
path ``RecordedFetcher`` will look for, so the recordings and the routing cannot
drift apart. Nothing is edited on the way in: what the service said is what
lands on disk.

Note what it does *not* do — invent a payload for a service that would not
answer. A source that returns nothing is recorded as returning nothing, because
that is the case synthesis has to get right.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..connectors.base import FetchResult, SpeciesRef
from ..connectors.http import HttpFetcher
from ..settings import get_settings
from .fetcher import RECORDED_DIR, recording_name

#: The fixture species, under the names the authorities accept for them, plus
#: one species whose USDA characteristics are actually populated — see
#: PROVENANCE.md for why that one is here.
SPECIES = [
    SpeciesRef(accepted_name="Monstera deliciosa"),
    SpeciesRef(accepted_name="Lavandula angustifolia"),
    SpeciesRef(accepted_name="Citrus limon"),
    SpeciesRef(accepted_name="Hosta sieboldiana"),
    SpeciesRef(accepted_name="Ocimum basilicum"),
    SpeciesRef(accepted_name="Dracaena trifasciata"),
    SpeciesRef(accepted_name="Rosa gallica"),
    SpeciesRef(accepted_name="Mandragora officinarum"),
    SpeciesRef(accepted_name="Abies balsamea"),
]


class RecordingFetcher:
    """Wraps the live fetcher and writes every payload it returns."""

    def __init__(self, inner: HttpFetcher, out_dir: Path) -> None:
        self.inner = inner
        self.out_dir = out_dir
        self.written: list[str] = []

    async def get_json(
        self, kind: str, url: str, params: Mapping[str, Any] | None = None
    ) -> FetchResult:
        result = await self.inner.get_json(kind, url, params)
        name = recording_name(kind, url, dict(params or {}))
        if name:
            path = self.out_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(result.payload, indent=2, ensure_ascii=False) + "\n"
            )
            self.written.append(name)
        return result


async def record(names: list[str]) -> int:
    from ..connectors.usda import UsdaConnector
    from ..connectors.wikidata import WikidataConnector
    from ..connectors.wikipedia import WikipediaConnector
    from ..connectors.wikipedia import wikidata_id as _wikidata_id

    wanted = [s for s in SPECIES if not names or s.accepted_name in names]
    if not wanted:
        print(
            f"No species matching {names}. Known: {[s.accepted_name for s in SPECIES]}"
        )
        return 1

    settings = get_settings()
    async with HttpFetcher(settings) as inner:
        fetcher = RecordingFetcher(inner, RECORDED_DIR)
        for species in wanted:
            print(f"--- {species.accepted_name}")
            page = await WikipediaConnector(fetcher).enrich(species)
            found = next(
                (
                    _wikidata_id(s.payload)
                    for s in page.sources
                    if isinstance(s.payload, dict) and _wikidata_id(s.payload)
                ),
                None,
            )
            resolved = replace(species, wikidata_id=found)
            for result in (
                await WikidataConnector(fetcher).enrich(resolved),
                await UsdaConnector(fetcher).enrich(resolved),
                page,
            ):
                state = result.error or f"{len(result.facts)} fact(s)"
                print(f"    {result.kind:10} {state}")
    print(f"\nwrote {len(fetcher.written)} file(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - a maintenance script
    raise SystemExit(asyncio.run(record(sys.argv[1:])))
