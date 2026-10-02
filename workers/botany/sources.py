"""Source records: where a fact came from, and the raw payload it came in.

the design is blunt about this — a citation has to be auditable and a synthesis has
to be repeatable without going back to the network, so the payload that produced
a value is kept on the ``source`` row beside the URL, licence and retrieval time.
Everything a connector returns carries one of these.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: A stable namespace, so the same URL fetched in two processes gets the same
#: source id and the ``source`` table does not grow a duplicate per worker.
SOURCE_NAMESPACE = uuid.UUID("6f0b6f5e-6a1b-5f3a-9a3f-0d0f5a2b7c11")

#: Licence and display title per source kind. Taken from the frozen
#: ``fixtures/species/sources.json`` so a live citation and a fixture citation
#: read the same in the UI. A kind we have no licence for says so rather than
#: guessing one.
SOURCE_META: dict[str, tuple[str, str | None]] = {
    "powo": ("Plants of the World Online", "CC BY 4.0"),
    "gbif": ("GBIF Backbone Taxonomy", "CC BY 4.0"),
    "wikipedia": ("Wikipedia", "CC BY-SA 4.0"),
    "wikidata": ("Wikidata", "CC0"),
    "usda": ("USDA PLANTS Database", "Public domain"),
    "perenual": ("Perenual plant care API", "Perenual terms"),
    "plantnet": ("Pl@ntNet identification", None),
    "other": ("Other source", None),
}


def source_id_for(kind: str, url: str) -> str:
    return str(uuid.uuid5(SOURCE_NAMESPACE, f"{kind}|{url}"))


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One ``source`` row: the citation, plus the payload it was read from."""

    kind: str
    title: str
    url: str | None
    license: str | None
    retrieved_at: datetime
    #: The response exactly as it arrived. Kept so a later synthesis can be redone
    #: without re-fetching, and so a citation can be audited.
    payload: Any = None
    id: str = ""
    #: True when the payload came from a recording rather than the live service.
    is_mock: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id", source_id_for(self.kind, self.url or self.title)
            )

    def to_ref(self) -> dict[str, Any]:
        """The contract's ``SourceRef`` — citation only, no payload."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "license": self.license,
            "retrieved_at": self.retrieved_at.astimezone(UTC).isoformat(),
        }

    def to_row(self) -> dict[str, Any]:
        """The ``source`` table row, payload included, ready to persist."""
        return {**self.to_ref(), "payload": self.payload}


def build_source(
    kind: str,
    url: str | None,
    payload: Any,
    *,
    title_suffix: str | None = None,
    retrieved_at: datetime | None = None,
    is_mock: bool = False,
) -> SourceRecord:
    """Make a source row for a fetched payload, titled the way the fixtures are."""
    base_title, licence = SOURCE_META.get(kind, SOURCE_META["other"])
    title = f"{base_title} — {title_suffix}" if title_suffix else base_title
    if is_mock:
        title = f"{title} (recorded)"
    return SourceRecord(
        kind=kind,
        title=title,
        url=url,
        license=licence,
        retrieved_at=retrieved_at or datetime.now(UTC),
        payload=payload,
        is_mock=is_mock,
    )


@dataclass
class SourceCache:
    """In-process cache of raw payloads, keyed by the request that produced them.

    Species facts do not change hourly and neither POWO nor GBIF owes us a burst
    of identical calls. The durable cache is ``source.payload`` in the database;
    this one only keeps a single worker run polite.
    """

    ttl_s: float = 24 * 60 * 60
    _entries: dict[str, tuple[float, SourceRecord]] = field(default_factory=dict)

    @staticmethod
    def key(kind: str, url: str, params: dict[str, Any] | None = None) -> str:
        blob = json.dumps(params or {}, sort_keys=True, default=str)
        return f"{kind}|{url}|{blob}"

    def get(self, key: str, *, now: float | None = None) -> SourceRecord | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, record = entry
        clock = now if now is not None else datetime.now(UTC).timestamp()
        if clock - stored_at > self.ttl_s:
            del self._entries[key]
            return None
        return record

    def put(self, key: str, record: SourceRecord, *, now: float | None = None) -> None:
        clock = now if now is not None else datetime.now(UTC).timestamp()
        self._entries[key] = (clock, record)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
