"""Runtime configuration. Owned by the deployment."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_", env_file=".env", extra="ignore"
    )

    database_url: str = (
        "postgresql+asyncpg://herbology:herbology@localhost:5432/herbology"
    )
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost:8000"

    #: With no database attached the API serves fixture-backed mocks, so every
    #: parts of the project can run the full stack before its dependencies exist.
    mock_mode: bool = True
    fixtures_dir: Path = REPO_ROOT / "fixtures"
    contracts_dir: Path = REPO_ROOT / "contracts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
