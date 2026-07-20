"""Claim-a-username auth: session cookie, optional email + magic-link
recovery (PLAN.md's locked decision — no passwords).

**Signup grants exactly once**, in the same transaction as the User
insert and the session it returns — a client that never sees the
response still has an account with a balance, never a balance-less
account or a duplicate grant on retry.

**Magic links always resolve to a `user_id` chosen at creation time**,
never by looking up `email` at consume time — see `MagicLink` in
`db/models.py` for why that distinction is load-bearing (it's what makes
attaching an unverified email safe). Consuming a link is the only thing
that ever writes `users.email`, which is what "attach" actually means:
proof of mailbox control, not just an unverified claim.

**`GET /auth/magic-link/consume` is a GET that changes state** (marks
the link used, creates a session). That's the standard shape for
"click the link in your email" and is accepted here — the trade-off is
that an email-scanning proxy that prefetches links could burn a token
before a real click. `MAGIC_LINK_TTL_MINUTES = 15` and the low stakes of
a play-money account make that an acceptable v1 risk, not a design flaw
to fix with a confirm-click page (that's a Phase 5 UI concern, not an
API one).
"""

import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ax.api.deps import (
    SESSION_COOKIE_NAME,
    CurrentUserDep,
    DbDep,
    EmailProviderDep,
    SessionSecretDep,
    SettingsDep,
)
from ax.core.auth import hash_token, magic_link_expiry, session_expiry
from ax.core.config import STARTING_BALANCE_CENTS
from ax.core.ledger import grant_entries
from ax.db.ledger import lock_balance_cache, write_entries
from ax.db.models import MagicLink, User
from ax.db.models import Session as SessionModel
from ax.providers.email import EmailMessage, EmailSendError
from ax.settings import Settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,24}$"
# Not RFC 5322 -- just enough to reject obvious garbage before it reaches
# Resend. The magic link itself is the real verification.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None


class SignupRequest(BaseModel):
    username: str = Field(pattern=_USERNAME_PATTERN)


class SignupResponse(BaseModel):
    user: UserOut
    cash_cents: int


class EmailRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN)


class DetailResponse(BaseModel):
    detail: str


class ConsumeResponse(BaseModel):
    user: UserOut


def _set_session_cookie(
    response: Response, settings: Settings, raw_token: str, now: datetime
) -> None:
    expires_at = session_expiry(now)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=int((expires_at - now).total_seconds()),
        httponly=True,
        secure=settings.is_production,
        # The web app is always cross-origin from the API (static export
        # on a different host, per CLAUDE.md), so a cross-site cookie
        # needs SameSite=None -- which browsers only honor alongside
        # Secure, hence the pairing with `is_production` above rather
        # than a fixed value. Local/test runs over plain HTTP, where
        # Secure cookies wouldn't be sent at all, so they fall back to
        # Lax (same-site is realistic there: localhost talking to
        # localhost).
        samesite="none" if settings.is_production else "lax",
        path="/",
    )


def _create_session(db: DbDep, session_secret: bytes, user_id: int, now: datetime) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(
        SessionModel(
            user_id=user_id,
            token_hash=hash_token(session_secret, raw_token),
            expires_at=session_expiry(now),
        )
    )
    db.flush()
    return raw_token


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
) -> SignupResponse:
    """Claim a username, grant `STARTING_BALANCE_CENTS`, and log in --
    one transaction, so a crash between "user created" and "grant
    written" is structurally impossible rather than merely unlikely."""
    now = datetime.now(UTC)
    user = User(username=body.username)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="username already taken"
        ) from exc

    balance = lock_balance_cache(db, user.id)
    write_entries(db, balance, user.id, grant_entries(STARTING_BALANCE_CENTS))

    raw_token = _create_session(db, session_secret, user.id, now)
    db.commit()

    _set_session_cookie(response, settings, raw_token, now)
    return SignupResponse(
        user=UserOut(id=user.id, username=user.username, email=user.email),
        cash_cents=balance.cash_cents,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    ax_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    """Idempotent and cookie-first: clears the cookie even if the session
    it names is already gone, expired, or was never valid -- a client
    retrying a logout that "failed" on the network must not get stuck
    unable to clear its own browser state."""
    if ax_session:
        token_hash = hash_token(session_secret, ax_session)
        stmt = select(SessionModel).where(SessionModel.token_hash == token_hash)
        row = db.scalars(stmt).one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            db.commit()

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
    )


@router.get("/me")
def me(user: CurrentUserDep) -> UserOut:
    return UserOut(id=user.id, username=user.username, email=user.email)


def _send_magic_link(
    email_provider: EmailProviderDep, settings: SettingsDep, to: str, raw_token: str
) -> None:
    link = f"{settings.web_origin}/auth/verify?token={raw_token}"
    try:
        email_provider.send(
            EmailMessage(
                to=to,
                subject="Your Artist Exchange sign-in link",
                html=(
                    f'<p>Click to continue: <a href="{link}">{link}</a></p>'
                    f"<p>This link expires in 15 minutes and can only be used once.</p>"
                ),
            )
        )
    except EmailSendError as exc:
        log.warning("magic-link send failed for %s: %s", to, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="could not send email, try again"
        ) from exc


@router.post("/email", status_code=status.HTTP_202_ACCEPTED)
def request_email_attach(
    body: EmailRequest,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    email_provider: EmailProviderDep,
    user: CurrentUserDep,
) -> DetailResponse:
    """Attach (or change) the current user's email. Nothing is written to
    `users.email` yet -- only consuming the resulting link proves mailbox
    control and actually attaches it (see module docstring)."""
    existing = db.scalars(
        select(User).where(User.email == body.email, User.id != user.id)
    ).one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already attached to another account"
        )

    now = datetime.now(UTC)
    raw_token = secrets.token_urlsafe(32)
    db.add(
        MagicLink(
            user_id=user.id,
            email=body.email,
            token_hash=hash_token(session_secret, raw_token),
            expires_at=magic_link_expiry(now),
        )
    )
    db.commit()

    _send_magic_link(email_provider, settings, body.email, raw_token)
    return DetailResponse(detail="check your email to confirm")


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
def request_magic_link(
    body: EmailRequest,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    email_provider: EmailProviderDep,
) -> DetailResponse:
    """Recovery on a new device: request a login link for an already-
    attached email. Always returns the same response whether or not the
    email is registered -- a differing response would let anyone probe
    which addresses have accounts."""
    user = db.scalars(select(User).where(User.email == body.email)).one_or_none()
    if user is not None:
        now = datetime.now(UTC)
        raw_token = secrets.token_urlsafe(32)
        db.add(
            MagicLink(
                user_id=user.id,
                email=body.email,
                token_hash=hash_token(session_secret, raw_token),
                expires_at=magic_link_expiry(now),
            )
        )
        db.commit()
        _send_magic_link(email_provider, settings, body.email, raw_token)

    return DetailResponse(detail="if that email is registered, a link was sent")


@router.get("/magic-link/consume")
def consume_magic_link(
    token: str,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
) -> ConsumeResponse:
    now = datetime.now(UTC)
    token_hash = hash_token(session_secret, token)
    stmt = select(MagicLink).where(
        MagicLink.token_hash == token_hash,
        MagicLink.used_at.is_(None),
        MagicLink.expires_at > now,
    )
    link = db.scalars(stmt).one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired link"
        )

    link.used_at = now
    user = db.get(User, link.user_id)
    assert user is not None, "magic_links.user_id is a NOT NULL FK to users"

    if user.email != link.email:
        user.email = link.email
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            # Someone else attached and confirmed this exact address
            # between the request and this click.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already attached to another account",
            ) from exc

    raw_token = _create_session(db, session_secret, user.id, now)
    db.commit()

    _set_session_cookie(response, settings, raw_token, now)
    return ConsumeResponse(user=UserOut(id=user.id, username=user.username, email=user.email))
