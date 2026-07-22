"""Process configuration — environment and secrets.

Deliberately *not* in `ax.core`. `core/config.py` holds tunable economics
(pure constants, no I/O); this holds deployment wiring (URLs, tokens) read
from the environment. Keeping them apart is what lets `core/` stay pure
under `tests/test_core_purity.py`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Managed Postgres providers (Railway, Heroku, Render, Fly) all emit
# `postgresql://...`, and some still emit the legacy `postgres://`.
# SQLAlchemy maps both to psycopg2, which this project does not install —
# it uses psycopg 3 — so an unmodified provider URL fails at connect time
# with `ModuleNotFoundError: No module named 'psycopg2'`.
_DRIVERLESS_PREFIXES = ("postgresql://", "postgres://")
_TARGET_PREFIX = "postgresql+psycopg://"


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

    resend_api_key: str = ""
    # Resend's shared sandbox sender. Works with zero setup but Resend
    # restricts it to the account owner's own inbox — swap in a verified
    # custom domain address before this needs to reach real users.
    email_from_address: str = "Artist Exchange <onboarding@resend.dev>"

    # "console" writes magic links to `email_log_path` instead of sending
    # them — local dev and Playwright's magic-link-recovery spec use this
    # to get a real, consumable token with no inbox and no Resend quota.
    # Nothing in the Railway config ever sets this; `get_email_provider`
    # (`api/deps.py`) additionally refuses it outright whenever
    # `is_production` is true, so a misconfigured production environment
    # can't silently stop delivering real magic links.
    email_provider: Literal["resend", "console"] = "resend"
    email_log_path: str = "/tmp/ax-email-log.jsonl"

    # Bearer token for /internal/jobs/*. Empty is refused at request time
    # rather than at import time, so tests and `--help` still work without it.
    internal_job_token: str = ""
    # HMAC key for session/magic-link token hashing (ax.core.auth.hash_token).
    session_secret: str = ""

    environment: Literal["local", "test", "production"] = "local"

    # Origin allowed to make credentialed cross-origin requests. The web
    # app is a static export served from a different host than the API, so
    # it is cross-origin even in production. Configured rather than
    # hardcoded because the deployed URL is not knowable from the repo.
    web_origin: str = "http://localhost:3000"

    @field_validator("database_url")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Normalize a provider-supplied URL to the psycopg 3 driver.

        Railway exposes `DATABASE_URL` as `postgresql://...`, which
        SQLAlchemy resolves to psycopg2 — not installed here. Rewriting it
        at the boundary means the Railway variable can be referenced
        directly, with no hand-edited copy of the connection string to
        drift out of sync when credentials rotate.
        """
        for prefix in _DRIVERLESS_PREFIXES:
            if value.startswith(prefix):
                return _TARGET_PREFIX + value[len(prefix) :]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
