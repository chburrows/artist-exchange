"""Shared FastAPI dependencies."""

import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from ax.providers.base import MetricProvider, ProviderAuthError
from ax.providers.lastfm import LastfmProvider
from ax.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_metric_provider(settings: SettingsDep) -> Iterator[MetricProvider]:
    """The data source the snapshot job reads from.

    A dependency rather than a direct construction inside the route so
    tests can substitute a fake and exercise the real endpoint — auth,
    serialization, DB writes, idempotency — without touching the network
    or spending rate-limit budget.
    """
    try:
        provider = LastfmProvider(settings.lastfm_api_key)
    except ProviderAuthError as exc:
        # 503, not 500: the service is misconfigured, not broken. That
        # distinction tells whoever is on call whether to check the
        # secrets or check the code.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        yield provider
    finally:
        provider.close()


MetricProviderDep = Annotated[MetricProvider, Depends(get_metric_provider)]


def require_job_token(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token guard for `/internal/jobs/*`.

    `secrets.compare_digest` rather than `==`: the comparison is against a
    static secret that an attacker can probe repeatedly, which is exactly
    the shape a timing attack needs.

    An unset token is refused rather than treated as "auth disabled". The
    dangerous version of this function is the one where a missing
    environment variable in production silently opens the endpoint to
    anyone.
    """
    if not settings.internal_job_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_JOB_TOKEN is not configured",
        )

    scheme, _, token = (authorization or "").partition(" ")
    # Compared as bytes, not str. `compare_digest` raises TypeError on
    # non-ASCII strings, and Starlette decodes headers as latin-1 — so a
    # single high byte in the Authorization header (`Bearer \xf1`) turns a
    # 401 into an unhandled 500 on a public endpoint. Encoding first makes
    # every possible input comparable while keeping the constant-time
    # property.
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token.encode("utf-8"), settings.internal_job_token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
