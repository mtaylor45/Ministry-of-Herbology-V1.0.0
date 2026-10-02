"""Runtime configuration for the botany worker — the botany worker.

Mirrors ``api/app/settings.py`` so one ``.env`` configures both:
the same ``MOH_`` prefix, the same ``mock_mode`` default. The extra keys here are
The botany worker's own — feature flags for the sources that open decision 1 in
`the project notes` has not settled, and the manners a polite
API client owes a free service.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Sent on every outbound request. A real contact address is the price of using
#: someone else's free API; POWO and GBIF both ask for one.
DEFAULT_USER_AGENT = (
    "MinistryOfHerbology/1.0 (self-hosted plant care; "
    "+https://github.com/mtaylor45/Ministry-of-Herbology-V1.0.0)"
)


class BotanySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_", env_file=".env", extra="ignore"
    )

    #: With no network (or no database) the worker answers from recorded payloads
    #: and the frozen fixtures, so the whole stack runs offline.
    mock_mode: bool = True
    fixtures_dir: Path = REPO_ROOT / "fixtures"

    user_agent: str = DEFAULT_USER_AGENT
    http_timeout_s: float = 10.0
    #: Minimum gap between two calls to the same host. Species facts do not
    #: change hourly and neither service owes us a burst.
    min_request_interval_s: float = 0.2
    #: How long a cached raw payload stays fresh in memory. The durable cache is
    #: the ``source.payload`` column; this only saves repeat calls in one process.
    cache_ttl_s: float = 24 * 60 * 60

    powo_base_url: str = "https://powo.science.kew.org/api/2"
    gbif_base_url: str = "https://api.gbif.org/v1"

    #: the design settled this: free and openly licensed sources only. Perenual and
    #: Pl@ntNet stay behind their key, disabled, and the free path — POWO and
    #: GBIF here, Wikipedia, Wikidata and USDA — must be complete on its
    #: own rather than degraded-but-shipping. Setting a key is the whole flag.
    perenual_api_key: str | None = None
    plantnet_api_key: str | None = None

    @property
    def enable_perenual(self) -> bool:
        return bool(self.perenual_api_key)

    @property
    def enable_plantnet(self) -> bool:
        return bool(self.plantnet_api_key)


@lru_cache
def get_settings() -> BotanySettings:
    return BotanySettings()
