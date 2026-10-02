"""Which Home Assistant this process talks to — the hub.

One decision, in one place: with ``mock_mode`` on, or with nothing configured,
the worker answers from :mod:`workers.hub.mocks.fetcher`; otherwise it opens a
socket. Keeping it here rather than at each call site means a job never has to
ask, and a test never has to patch more than one thing.

The unconfigured case falls back to the mock **deliberately**. A fresh checkout
has no ``MOH_HA_BASE_URL``, and the alternative is every job failing at startup
with a connection error, which trains a new contributor to ignore a red log.
:class:`~workers.hub.health.IntegrationHealth` still reports that deployment as
*unconfigured* rather than *ok*, so nothing about the fallback makes an
unfinished setup look finished.
"""

from __future__ import annotations

from functools import lru_cache

from .settings import HubSettings, get_settings
from .sources.base import Fetcher
from .sources.home_assistant import HomeAssistantSource


def build_fetcher(settings: HubSettings | None = None) -> Fetcher:
    config = settings or get_settings()
    if config.mock_mode or not config.is_configured:
        from .mocks.fetcher import RecordedFetcher

        return RecordedFetcher(config)
    from .sources.http import HomeAssistantFetcher

    return HomeAssistantFetcher(config)


def build_source(settings: HubSettings | None = None) -> HomeAssistantSource:
    config = settings or get_settings()
    return HomeAssistantSource(build_fetcher(config), config)


@lru_cache
def get_source() -> HomeAssistantSource:
    """The process-wide source, so one process keeps one HTTP client."""
    return build_source()
