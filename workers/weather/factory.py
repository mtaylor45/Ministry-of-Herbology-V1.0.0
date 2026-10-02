"""Wiring: which fetcher, which sources, for this deployment.

One place decides whether the worker talks to Open-Meteo and NWS or replays
``mocks/recorded/``, and it decides on ``mock_mode`` alone. Every other module
takes a ``Fetcher`` and does not care which it got — that is what lets the
whole stack run offline without a branch in the engines.
"""

from __future__ import annotations

from functools import lru_cache

from .ingest import WeatherIngest
from .settings import WeatherSettings, get_settings
from .sources.base import Fetcher


def build_fetcher(settings: WeatherSettings | None = None) -> Fetcher:
    settings = settings or get_settings()
    if settings.mock_mode:
        from .mocks.fetcher import RecordedFetcher

        return RecordedFetcher(settings)

    from .sources.http import HttpFetcher

    return HttpFetcher(settings)


def build_ingest(settings: WeatherSettings | None = None) -> WeatherIngest:
    settings = settings or get_settings()
    return WeatherIngest(build_fetcher(settings), settings)


@lru_cache
def get_ingest() -> WeatherIngest:
    """One ingest per process, so one HTTP client and one resolved NWS grid."""
    return build_ingest()
