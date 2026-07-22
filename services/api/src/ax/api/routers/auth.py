"""Required-email signup, session cookie, magic-link recovery (PLAN.md
Phase 7 — no passwords, still the locked decision).

**Nothing in `users` exists until an emailed link is clicked.** `POST
/auth/signup` only ever writes a `PendingSignup` row; `POST
/auth/signup/consume` is what creates the user, grants
`STARTING_BALANCE_CENTS`, and opens the session, all in one transaction —
this is what makes eager signup-spam (squatting usernames, or triggering
grants, without ever proving inbox ownership) structurally impossible
rather than merely discouraged.

**`users.email` is mandatory and always verified.** Phase 4's `POST
/auth/email` (attach an email after a username-only signup) is gone —
there is no longer a "signed up but unverified/no email" state to attach
one to. `magic_links` now exists solely for returning-user login/recovery.

**Magic links always resolve to a `user_id` chosen at creation time**,
never by looking up `email` at consume time — see `MagicLink` in
`db/models.py` for the (now mostly historical, but still load-bearing)
reasoning.

**Both consume endpoints are `POST`, not `GET`.** A state-changing `GET`
was accepted in Phase 4 as a rarely-hit recovery path, but signup
consumption is about to become the primary way every account gets
created — worth closing the "an email-scanning proxy prefetches the link
and silently burns the token" gap for both at once, since this file was
already open for exactly that reason.
"""

import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ax.api.deps import (
    SESSION_COOKIE_NAME,
    CurrentUserDep,
    DbDep,
    EmailProviderDep,
    SessionSecretDep,
    SettingsDep,
)
from ax.api.username_gen import random_username
from ax.core.auth import hash_token, magic_link_expiry, pending_signup_expiry, session_expiry
from ax.core.config import STARTING_BALANCE_CENTS
from ax.core.ledger import grant_entries
from ax.db.ledger import lock_balance_cache, write_entries
from ax.db.models import MagicLink, PendingSignup, User
from ax.db.models import Session as SessionModel
from ax.providers.email import EmailMessage, EmailSendError
from ax.settings import Settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,24}$"
# Not RFC 5322 -- just enough to reject obvious garbage before it reaches
# the email provider. The link itself is the real verification.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# Size of the candidate batch `_pick_username` generates and checks in one
# query. `random_username()`'s collision odds are low (20 * 20 * 100
# candidates) but not zero, and a caller-supplied name isn't batched at all
# -- see `consume_signup`.
_MAX_USERNAME_GENERATION_ATTEMPTS = 5


def _normalize_username(value: str | None) -> str | None:
    """Blank or omitted both mean "the caller didn't choose one" --
    treated identically so a client that submits an empty string instead
    of leaving the field out doesn't get a 422 where it should instead
    fall back to a server-generated name."""
    if not value:
        return None
    if not re.fullmatch(_USERNAME_PATTERN, value):
        raise ValueError(f"username must match {_USERNAME_PATTERN}")
    return value


class UserOut(BaseModel):
    id: int
    username: str
    email: str


class SignupRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN)
    username: str | None = None

    _normalize = field_validator("username")(_normalize_username)


class SignupConsumeRequest(BaseModel):
    token: str
    username: str | None = None

    _normalize = field_validator("username")(_normalize_username)


class SignupResponse(BaseModel):
    user: UserOut
    cash_cents: int


class UsernameUpdateRequest(BaseModel):
    username: str = Field(pattern=_USERNAME_PATTERN)


class EmailRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN)


class MagicLinkConsumeRequest(BaseModel):
    token: str


class DetailResponse(BaseModel):
    detail: str


class ConsumeResponse(BaseModel):
    user: UserOut


class _CookieAttrs(NamedTuple):
    secure: bool
    samesite: Literal["none", "lax"]


def _cookie_attrs(settings: Settings) -> _CookieAttrs:
    """Shared by `_set_session_cookie` and `logout`: a browser only clears
    a cookie via `Set-Cookie` if the clearing response's `Secure`/
    `SameSite`/`Path` match the original exactly, so these can't be two
    independent copies that might drift.

    The web app is always cross-origin from the API (static export on a
    different host, per CLAUDE.md), so a cross-site cookie needs
    `SameSite=None` -- which browsers only honor alongside `Secure`,
    hence the pairing with `is_production` rather than a fixed value.
    Local/test runs over plain HTTP, where `Secure` cookies wouldn't be
    sent at all, fall back to `Lax` (same-site is realistic there:
    localhost talking to localhost)."""
    return _CookieAttrs(
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
    )


def _set_session_cookie(
    response: Response, settings: Settings, raw_token: str, now: datetime
) -> None:
    expires_at = session_expiry(now)
    attrs = _cookie_attrs(settings)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=int((expires_at - now).total_seconds()),
        httponly=True,
        secure=attrs.secure,
        samesite=attrs.samesite,
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


def _send_link(
    email_provider: EmailProviderDep,
    settings: SettingsDep,
    to: str,
    subject: str,
    path: str,
    raw_token: str,
) -> None:
    link = f"{settings.web_origin}/{path}?token={raw_token}"
    try:
        email_provider.send(
            EmailMessage(
                to=to,
                subject=subject,
                html=(
                    f'<p>Click to continue: <a href="{link}">{link}</a></p>'
                    f"<p>This link expires in 15 minutes and can only be used once.</p>"
                ),
            )
        )
    except EmailSendError as exc:
        log.warning("email send failed for %s: %s", to, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="could not send email, try again"
        ) from exc


def _issue_magic_link(
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    email_provider: EmailProviderDep,
    user: User,
    now: datetime,
) -> None:
    """Shared by `request_signup`'s existing-user branch and
    `request_magic_link` -- both are "send this already-known user a
    sign-in link", just reached from different callers."""
    raw_token = secrets.token_urlsafe(32)
    db.add(
        MagicLink(
            user_id=user.id,
            email=user.email,
            token_hash=hash_token(session_secret, raw_token),
            expires_at=magic_link_expiry(now),
        )
    )
    db.commit()
    _send_link(
        email_provider,
        settings,
        user.email,
        "Your Artist Exchange sign-in link",
        "auth/verify",
        raw_token,
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    """`users` has two unique constraints (`username`, `email`) -- a bare
    `IntegrityError` doesn't say which fired, but psycopg's `diag` does,
    via the constraint names `NAMING_CONVENTION` (`db/base.py`) assigns:
    `uq_users_username` / `uq_users_email`."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) if diag is not None else None


def _pick_username(db: DbDep) -> str:
    """A batch of generated candidates, filtered against `users` in one
    query -- cheaper than the old flush-per-guess loop, and avoids
    treating every retry as a database round trip. The tiny remaining
    race (another request takes the same candidate between this SELECT
    and the caller's INSERT) is left to that INSERT's own uniqueness
    check rather than guarded against here."""
    candidates = [random_username() for _ in range(_MAX_USERNAME_GENERATION_ATTEMPTS)]
    taken = set(db.scalars(select(User.username).where(User.username.in_(candidates))))
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    return candidates[-1]


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
def request_signup(
    body: SignupRequest,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    email_provider: EmailProviderDep,
) -> DetailResponse:
    """Request step of verify-before-create signup. Always 202 regardless
    of which branch below fires -- same anti-enumeration shape
    `/auth/magic-link` already uses, so a prober can't distinguish "this
    address already has an account" from "a new signup was queued"."""
    now = datetime.now(UTC)

    existing_user = db.scalars(select(User).where(User.email == body.email)).one_or_none()
    if existing_user is not None:
        # A verified account already owns this address -- this is a
        # login, not a signup. No second pending signup is created for
        # an address that will never consume one.
        _issue_magic_link(db, settings, session_secret, email_provider, existing_user, now)
        return DetailResponse(detail="check your email to continue")

    # At most one live pending signup per address -- an abandoned earlier
    # request must not linger once a second one comes in for the same
    # email, or "which token is current" becomes ambiguous. A single
    # `INSERT ... ON CONFLICT` against the `uq_pending_signups_email_live`
    # partial unique index (see `PendingSignup`) makes this atomic: two
    # concurrent requests for the same address can no longer both insert
    # a live row, which a separate delete-then-insert couldn't guarantee.
    raw_token = secrets.token_urlsafe(32)
    stmt = pg_insert(PendingSignup).values(
        email=body.email,
        requested_username=body.username,
        token_hash=hash_token(session_secret, raw_token),
        expires_at=pending_signup_expiry(now),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PendingSignup.email],
        index_where=PendingSignup.consumed_at.is_(None),
        set_={
            "requested_username": stmt.excluded.requested_username,
            "token_hash": stmt.excluded.token_hash,
            "expires_at": stmt.excluded.expires_at,
        },
    )
    db.execute(stmt)
    db.commit()

    _send_link(
        email_provider,
        settings,
        body.email,
        "Confirm your Artist Exchange signup",
        "auth/verify-signup",
        raw_token,
    )
    return DetailResponse(detail="check your email to continue")


@router.post("/signup/consume", status_code=status.HTTP_201_CREATED)
def consume_signup(
    body: SignupConsumeRequest,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
) -> SignupResponse:
    """Creates `users` + the `GRANT` ledger row + a `Session`, all in one
    transaction (the same shape Phase 4's one-shot signup used, just
    moved behind email verification).

    Username collision handling has one rule: a value nobody chose (this
    request omitted `username` *and* the original request did too) is
    the server's problem -- `_pick_username` pre-filters a batch of
    generated candidates against `users` so a real collision is rare;
    a value somebody chose -- typed at request time, or supplied again
    here -- is a 409 for the caller to resolve. Either way `consumed_at`
    is deliberately left unset on a 409 so the token (proof of inbox
    ownership) is still good for a retry against a different username.
    """
    now = datetime.now(UTC)
    token_hash = hash_token(session_secret, body.token)
    pending = db.scalars(
        select(PendingSignup).where(
            PendingSignup.token_hash == token_hash,
            PendingSignup.consumed_at.is_(None),
            PendingSignup.expires_at > now,
        )
    ).one_or_none()
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired signup link"
        )

    if body.username is not None:
        candidate, server_generated = body.username, False
    elif pending.requested_username is not None:
        candidate, server_generated = pending.requested_username, False
    else:
        candidate, server_generated = _pick_username(db), True

    user = User(username=candidate, email=pending.email)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) != "uq_users_username":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="an account for this email already exists",
            ) from None
        detail = (
            "could not generate a unique username, try again"
            if server_generated
            else "username already taken"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None

    pending.consumed_at = now
    balance = lock_balance_cache(db, user.id)
    write_entries(db, balance, user.id, grant_entries(STARTING_BALANCE_CENTS))

    raw_token = _create_session(db, session_secret, user.id, now)
    db.commit()

    _set_session_cookie(response, settings, raw_token, now)
    return SignupResponse(
        user=UserOut(id=user.id, username=user.username, email=user.email),
        cash_cents=balance.cash_cents,
    )


@router.patch("/username")
def update_username(
    body: UsernameUpdateRequest,
    db: DbDep,
    user: CurrentUserDep,
) -> UserOut:
    user.username = body.username
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="username already taken"
        ) from exc
    db.commit()
    return UserOut(id=user.id, username=user.username, email=user.email)


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

    attrs = _cookie_attrs(settings)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=attrs.secure,
        samesite=attrs.samesite,
    )


@router.get("/me")
def me(user: CurrentUserDep) -> UserOut:
    return UserOut(id=user.id, username=user.username, email=user.email)


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
def request_magic_link(
    body: EmailRequest,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
    email_provider: EmailProviderDep,
) -> DetailResponse:
    """Recovery on a new device: request a login link for an existing
    account. Always returns the same response whether or not the email
    is registered -- a differing response would let anyone probe which
    addresses have accounts."""
    user = db.scalars(select(User).where(User.email == body.email)).one_or_none()
    if user is not None:
        _issue_magic_link(db, settings, session_secret, email_provider, user, datetime.now(UTC))

    return DetailResponse(detail="if that email is registered, a link was sent")


@router.post("/magic-link/consume")
def consume_magic_link(
    body: MagicLinkConsumeRequest,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    session_secret: SessionSecretDep,
) -> ConsumeResponse:
    now = datetime.now(UTC)
    token_hash = hash_token(session_secret, body.token)
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

    raw_token = _create_session(db, session_secret, user.id, now)
    db.commit()

    _set_session_cookie(response, settings, raw_token, now)
    return ConsumeResponse(user=UserOut(id=user.id, username=user.username, email=user.email))
