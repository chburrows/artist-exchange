"""Required-email signup (request -> consume), session cookie, and
magic-link recovery, end to end through the real app -- these are the
auth guarantees that everything else (trades, portfolio) trusts blindly,
so they're exercised at the HTTP layer rather than just unit-tested
against the pure helpers.
"""

import secrets
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ax.core.auth import hash_token, pending_signup_expiry
from ax.core.config import STARTING_BALANCE_CENTS
from ax.db.models import BalanceCache, PendingSignup, Transaction, User
from ax.settings import Settings
from tests.conftest import FakeEmailProvider, complete_signup


def test_signup_request_consume_grants_exactly_once(
    client: TestClient, session: Session, email_provider: FakeEmailProvider
) -> None:
    request = client.post(
        "/auth/signup", json={"email": "scout99@example.com", "username": "scout99"}
    )
    assert request.status_code == 202
    # Anti-enumeration: the request step never reveals account state.
    assert request.json() == {"detail": "check your email to continue"}

    consume = client.post("/auth/signup/consume", json={"token": email_provider.last_token()})
    assert consume.status_code == 201
    body = consume.json()
    assert body["cash_cents"] == STARTING_BALANCE_CENTS
    assert body["user"]["username"] == "scout99"
    assert body["user"]["email"] == "scout99@example.com"
    assert "ax_session" in consume.cookies

    user = session.scalars(select(User).where(User.username == "scout99")).one()
    grants = session.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.kind == "GRANT")
    ).all()
    assert len(grants) == 1
    assert grants[0].cash_delta_cents == STARTING_BALANCE_CENTS

    balance = session.get(BalanceCache, user.id)
    assert balance is not None
    assert balance.cash_cents == STARTING_BALANCE_CENTS


def test_signup_rejects_invalid_email(client: TestClient) -> None:
    response = client.post("/auth/signup", json={"email": "not-an-email", "username": "a-ok"})
    assert response.status_code == 422


def test_signup_rejects_invalid_username(client: TestClient) -> None:
    response = client.post("/auth/signup", json={"email": "a@example.com", "username": "a"})
    assert response.status_code == 422


def test_signup_without_a_username_generates_one(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    request = client.post("/auth/signup", json={"email": "noname@example.com"})
    assert request.status_code == 202

    consume = client.post("/auth/signup/consume", json={"token": email_provider.last_token()})
    assert consume.status_code == 201
    username = consume.json()["user"]["username"]
    assert 3 <= len(username) <= 24


def test_consume_with_a_taken_username_409s_without_consuming_the_token(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "onlyone", email="onlyone@example.com")

    request = client.post(
        "/auth/signup", json={"email": "second@example.com", "username": "second-hopeful"}
    )
    assert request.status_code == 202
    token = email_provider.last_token()

    collide = client.post("/auth/signup/consume", json={"token": token, "username": "onlyone"})
    assert collide.status_code == 409

    # The token is still good -- a username collision isn't proof the
    # caller doesn't own the inbox, so it must not be burned.
    retry = client.post(
        "/auth/signup/consume", json={"token": token, "username": "second-claimant"}
    )
    assert retry.status_code == 201
    assert retry.json()["user"]["username"] == "second-claimant"


def test_consume_rejects_an_unknown_token(client: TestClient) -> None:
    response = client.post("/auth/signup/consume", json={"token": "not-a-real-token"})
    assert response.status_code == 400


def test_consume_is_single_use(client: TestClient, email_provider: FakeEmailProvider) -> None:
    client.post("/auth/signup", json={"email": "singleuse@example.com", "username": "singleuse"})
    token = email_provider.last_token()

    first = client.post("/auth/signup/consume", json={"token": token})
    assert first.status_code == 201

    second = client.post("/auth/signup/consume", json={"token": token})
    assert second.status_code == 400


def test_signup_for_an_email_that_already_has_a_verified_account_sends_a_login_link(
    client: TestClient, email_provider: FakeEmailProvider, session: Session
) -> None:
    complete_signup(client, email_provider, "existing", email="existing@example.com")
    users_before = session.scalars(select(User)).all()

    request = client.post(
        "/auth/signup", json={"email": "existing@example.com", "username": "existing-again"}
    )
    assert request.status_code == 202
    assert request.json() == {"detail": "check your email to continue"}

    users_after = session.scalars(select(User)).all()
    assert len(users_after) == len(users_before)

    # The link sent is a login link, not a signup-consume link.
    consume = client.post("/auth/magic-link/consume", json={"token": email_provider.last_token()})
    assert consume.status_code == 200
    assert consume.json()["user"]["username"] == "existing"


def test_a_second_signup_request_for_the_same_email_invalidates_the_first_token(
    client: TestClient, email_provider: FakeEmailProvider, session: Session
) -> None:
    first = client.post(
        "/auth/signup", json={"email": "flip-flop@example.com", "username": "first-try"}
    )
    assert first.status_code == 202
    first_token = email_provider.last_token()

    second = client.post(
        "/auth/signup", json={"email": "flip-flop@example.com", "username": "second-try"}
    )
    assert second.status_code == 202

    live = session.scalars(
        select(PendingSignup).where(PendingSignup.email == "flip-flop@example.com")
    ).all()
    assert len(live) == 1

    consume_stale = client.post("/auth/signup/consume", json={"token": first_token})
    assert consume_stale.status_code == 400


def test_concurrent_signup_requests_for_the_same_email_cannot_both_stay_live(
    session: Session, test_settings: Settings
) -> None:
    """The DB-level counterpart to
    `test_a_second_signup_request_for_the_same_email_invalidates_the_first_token`:
    even bypassing the app's own delete-then-insert (inserting a second
    live row directly, as a true concurrent request would), the partial
    unique index on `pending_signups.email` (scoped to `consumed_at IS
    NULL`) rejects it outright rather than silently allowing two live
    tokens for one address."""
    now = datetime.now(UTC)
    secret = test_settings.session_secret.encode("utf-8")
    session.add(
        PendingSignup(
            email="racer@example.com",
            requested_username="racer-one",
            token_hash=hash_token(secret, secrets.token_urlsafe(32)),
            expires_at=pending_signup_expiry(now),
        )
    )
    session.commit()

    session.add(
        PendingSignup(
            email="racer@example.com",
            requested_username="racer-two",
            token_hash=hash_token(secret, secrets.token_urlsafe(32)),
            expires_at=pending_signup_expiry(now),
        )
    )
    try:
        session.flush()
        raised = False
    except IntegrityError:
        raised = True
    finally:
        session.rollback()
    assert raised


def test_consume_email_collision_is_not_misreported_as_username_taken(
    client: TestClient, session: Session, test_settings: Settings
) -> None:
    """A `users.email` uniqueness violation at consume time (the shape a
    genuine request-time race would produce, before the partial unique
    index above closed off the app-level path that used to create it)
    must not be reported as "username already taken" -- the caller would
    retry with a new username forever and never fix the real problem."""
    now = datetime.now(UTC)
    session.add(User(username="race-winner", email="race@example.com"))
    session.flush()

    raw_token = secrets.token_urlsafe(32)
    session.add(
        PendingSignup(
            email="race@example.com",
            requested_username="race-loser",
            token_hash=hash_token(test_settings.session_secret.encode("utf-8"), raw_token),
            expires_at=pending_signup_expiry(now),
        )
    )
    session.commit()

    response = client.post(
        "/auth/signup/consume", json={"token": raw_token, "username": "someone-new"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "an account for this email already exists"


def test_users_email_not_null_is_a_db_backstop(session: Session) -> None:
    session.add(User(username="no-email-allowed", email=None))  # type: ignore[arg-type]
    try:
        session.flush()
        raised = False
    except IntegrityError:
        raised = True
    finally:
        session.rollback()
    assert raised


def test_me_requires_a_session(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_signup_then_me_round_trips(client: TestClient, email_provider: FakeEmailProvider) -> None:
    complete_signup(client, email_provider, "roundtrip", email="roundtrip@example.com")

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == "roundtrip"


def test_logout_clears_the_session(client: TestClient, email_provider: FakeEmailProvider) -> None:
    complete_signup(client, email_provider, "loggingout", email="loggingout@example.com")
    assert client.get("/auth/me").status_code == 200

    logout = client.post("/auth/logout")
    assert logout.status_code == 204

    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_session_is_a_no_op(client: TestClient) -> None:
    assert client.post("/auth/logout").status_code == 204


def test_update_username_requires_auth(client: TestClient) -> None:
    response = client.patch("/auth/username", json={"username": "newname"})
    assert response.status_code == 401


def test_update_username_changes_it_and_frees_the_old_one(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "oldname", email="rename@example.com")

    response = client.patch("/auth/username", json={"username": "newname"})
    assert response.status_code == 200
    assert response.json()["username"] == "newname"
    assert client.get("/auth/me").json()["username"] == "newname"

    client.post("/auth/logout")
    # The old username is claimable again.
    reclaim = client.post(
        "/auth/signup", json={"email": "reclaimer@example.com", "username": "oldname"}
    )
    assert reclaim.status_code == 202


def test_update_username_rejects_a_collision(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "taken", email="taken@example.com")
    client.post("/auth/logout")
    complete_signup(client, email_provider, "renamer", email="renamer@example.com")

    response = client.patch("/auth/username", json={"username": "taken"})
    assert response.status_code == 409


def test_magic_link_recovery_logs_into_the_right_account(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "recoverme", email="recoverme@example.com")
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401

    recovery = client.post("/auth/magic-link", json={"email": "recoverme@example.com"})
    assert recovery.status_code == 202

    recovery_token = email_provider.last_token()
    consume = client.post("/auth/magic-link/consume", json={"token": recovery_token})
    assert consume.status_code == 200
    assert consume.json()["user"]["username"] == "recoverme"

    assert client.get("/auth/me").json()["username"] == "recoverme"


def test_magic_link_recovery_for_unregistered_email_is_silent(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    response = client.post("/auth/magic-link", json={"email": "nobody@example.com"})

    assert response.status_code == 202
    assert email_provider.sent == []


def test_magic_link_consume_rejects_an_unknown_token(client: TestClient) -> None:
    response = client.post("/auth/magic-link/consume", json={"token": "not-a-real-token"})
    assert response.status_code == 400


def test_email_send_failure_surfaces_as_502(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    email_provider.fail = True

    response = client.post(
        "/auth/signup", json={"email": "unlucky@example.com", "username": "unlucky"}
    )

    assert response.status_code == 502
