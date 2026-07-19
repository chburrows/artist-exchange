"""Process configuration — environment and secrets.

Deliberately *not* in `ax.core`. `core/config.py` holds tunable economics
(pure constants, no I/O); this holds deployment wiring (URLs, tokens) read
from the environment. Keeping them apart is what lets `core/` stay pure
under `tests/test_core_purity.py`.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Both paths are tried so the same code works whether you run from the
    # repo root (the documented way) or from services/api. Later entries
    # win. In the container neither file exists and real environment
    # variables are used, which is exactly what Railway injects.
    model_config = SettingsConfigDict(
        env_file=(".env", "services/api/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange"

    lastfm_api_key: str = ""
    lastfm_shared_secret: str = ""

    # Bearer token for /internal/jobs/*. Empty is refused at request time
    # rather than at import time, so tests and `--help` still work without it.
    internal_job_token: str = ""
    session_secret: str = ""

    environment: Literal["local", "test", "production"] = "local"

    # Origin allowed to make credentialed cross-origin requests. The web
    # app is a static export served from a different host than the API, so
    # it is cross-origin even in production. Configured rather than
    # hardcoded because the deployed URL is not knowable from the repo.
    web_origin: str = "http://localhost:3000"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
