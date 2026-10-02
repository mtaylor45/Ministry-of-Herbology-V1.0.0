"""Shared setup for the journal's tests. Owner: The journal.

Every test here runs offline. Nothing in this directory may open a socket: the
connectors are exercised against payloads shaped like the documented API
responses, and mock mode draws its own images.

The repository-root ``conftest.py`` puts both source roots on ``sys.path``;
this file deliberately does not do it again — see the note in
``workers/botany/tests/conftest.py`` for what a second copy of that mechanism
cost last time.
"""

from __future__ import annotations

from typing import Any

import pytest

from workers.plates import config as plate_config
from workers.plates.config import PlateSettings


def plate_settings(**overrides: Any) -> PlateSettings:
    """Settings built from nothing but the overrides a test asks for.

    ``_env_file=None`` keeps a developer's stray ``.env`` out of the suite, and
    lives here rather than in forty call sites so the one ``type: ignore`` that
    pydantic-settings' private keyword needs is written once.
    """
    return PlateSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _forget_cached_plate_settings() -> None:
    """``get_plate_settings`` is cached; a test that sets an env var must not
    inherit a previous test's answer."""
    plate_config.get_plate_settings.cache_clear()
