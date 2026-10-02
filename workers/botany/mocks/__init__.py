"""Fixture- and recording-backed stand-ins for the source APIs.

The build-against-mocks rule of the working agreement: every service ships a mock matching the
contract, so nobody waits on anybody and the whole stack runs offline. The build-against-mocks rule
also says mocks are driven by ``fixtures/``, and this one is — for any name the
recordings do not cover, it answers out of ``fixtures/species/species.json`` so
the botany mock tells the same story as every other parts of the project's.

The recordings live in ``recorded/`` and are replayed through the *same* parsers
the live connectors use, so mock mode exercises the real code path rather than a
parallel one. ``recorded/PROVENANCE.md`` says where each payload came from.
"""

from .fetcher import (
    RecordedFetcher,
    build_mock_connectors,
    build_mock_enrichment_connectors,
)

__all__ = [
    "RecordedFetcher",
    "build_mock_connectors",
    "build_mock_enrichment_connectors",
]
