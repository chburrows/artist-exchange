"""Shared FastAPI dependencies."""

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ax.core.auth import hash_token
from ax.db.models import Session as SessionModel
from ax.db.models import User
from ax.db.session import get_db
from ax.providers.base import MetricProvider, ProviderAuthError
from ax.providers.email import EmailAuthError, EmailProvider, ResendEmailProvider
from ax.providers.lastfm import LastfmProvider
from ax.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]

# Shared with api/routers/auth.py, which is the only other place that
# reads or writes this cookie.
SESSION_COOKIE_NAME = "ax_session"

DbDep = Annotated[DbSession, Depends(get_db)]


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


def get_email_provider(settings: SettingsDep) -> Iterator[EmailProvider]:
    """The channel magic links go out on. A dependency for the same
    reason `get_metric_provider` is: auth routes' tests substitute a fake
    and exercise signup/attach/recovery without a real network call."""
    try:
        provider = ResendEmailProvider(settings.resend_api_key, settings.email_from_address)
    except EmailAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        yield provider
    finally:
        provider.close()


EmailProviderDep = Annotated[EmailProvider, Depends(get_email_provider)]


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


def require_session_secret(settings: SettingsDep) -> bytes:
    """The HMAC key every session/magic-link token is hashed with
    (`ax.core.auth.hash_token`). Same "refuse, don't silently degrade"
    shape as `require_job_token`: an unset secret must not quietly hash
    every token under an empty key."""
    if not settings.session_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SESSION_SECRET is not configured",
        )
    return settings.session_secret.encode("utf-8")


SessionSecretDep = Annotated[bytes, Depends(require_session_secret)]


def get_current_user(
    db: DbDep,
    session_secret: SessionSecretDep,
    ax_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Resolves the session cookie to its user. 401 on anything short of a
    live, unrevoked, unexpired session — a missing cookie and a garbage
    one get the same response, so neither leaks which case it was."""
    if not ax_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    token_hash = hash_token(session_secret, ax_session)
    now = datetime.now(UTC)
    stmt = (
        select(User)
        .join(SessionModel, SessionModel.user_id == User.id)
        .where(
            SessionModel.token_hash == token_hash,
            SessionModel.revoked_at.is_(None),
            SessionModel.expires_at > now,
        )
    )
    user = db.scalars(stmt).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
