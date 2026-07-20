"""Signup, session cookie, and magic-link flows, end to end through the
real app -- these are the auth guarantees that everything else (trades,
portfolio) trusts blindly, so they're exercised at the HTTP layer rather
than just unit-tested against the pure helpers.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.core.config import STARTING_BALANCE_CENTS
from ax.db.models import BalanceCache, Transaction, User
from tests.conftest import FakeEmailProvider


def test_signup_grants_exactly_once(client: TestClient, session: Session) -> None:
    response = client.post("/auth/signup", json={"username": "scout99"})

    assert response.status_code == 201
    body = response.json()
    assert body["cash_cents"] == STARTING_BALANCE_CENTS
    assert body["user"]["username"] == "scout99"
    assert "ax_session" in response.cookies

    user = session.scalars(select(User).where(User.username == "scout99")).one()
    grants = session.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.kind == "GRANT")
    ).all()
    assert len(grants) == 1
    assert grants[0].cash_delta_cents == STARTING_BALANCE_CENTS

    balance = session.get(BalanceCache, user.id)
    assert balance is not None
    assert balance.cash_cents == STARTING_BALANCE_CENTS


def test_signup_rejects_duplicate_username(client: TestClient) -> None:
    first = client.post("/auth/signup", json={"username": "onlyone"})
    assert first.status_code == 201

    second = client.post("/auth/signup", json={"username": "onlyone"})
    assert second.status_code == 409


def test_signup_rejects_invalid_username(client: TestClient) -> None:
    response = client.post("/auth/signup", json={"username": "a"})
    assert response.status_code == 422


def test_me_requires_a_session(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_signup_then_me_round_trips(client: TestClient) -> None:
    client.post("/auth/signup", json={"username": "roundtrip"})

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == "roundtrip"


def test_logout_clears_the_session(client: TestClient) -> None:
    client.post("/auth/signup", json={"username": "loggingout"})
    assert client.get("/auth/me").status_code == 200

    logout = client.post("/auth/logout")
    assert logout.status_code == 204

    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_session_is_a_no_op(client: TestClient) -> None:
    assert client.post("/auth/logout").status_code == 204


def test_email_attach_requires_auth(client: TestClient) -> None:
    response = client.post("/auth/email", json={"email": "scout@example.com"})
    assert response.status_code == 401


def test_email_attach_and_consume_confirms_the_address(
    client: TestClient, email_provider: FakeEmailProvider, session: Session
) -> None:
    client.post("/auth/signup", json={"username": "attacher"})

    attach = client.post("/auth/email", json={"email": "attacher@example.com"})
    assert attach.status_code == 202
    assert len(email_provider.sent) == 1
    assert email_provider.sent[0].to == "attacher@example.com"

    me_before = client.get("/auth/me").json()
    assert me_before["email"] is None

    token = email_provider.last_token()
    consume = client.get(f"/auth/magic-link/consume?token={token}")
    assert consume.status_code == 200
    assert consume.json()["user"]["email"] == "attacher@example.com"

    user = session.scalars(select(User).where(User.username == "attacher")).one()
    assert user.email == "attacher@example.com"


def test_consume_rejects_an_unknown_token(client: TestClient) -> None:
    response = client.get("/auth/magic-link/consume?token=not-a-real-token")
    assert response.status_code == 400


def test_consume_is_single_use(client: TestClient, email_provider: FakeEmailProvider) -> None:
    client.post("/auth/signup", json={"username": "singleuse"})
    client.post("/auth/email", json={"email": "singleuse@example.com"})
    token = email_provider.last_token()

    first = client.get(f"/auth/magic-link/consume?token={token}")
    assert first.status_code == 200

    second = client.get(f"/auth/magic-link/consume?token={token}")
    assert second.status_code == 400


def test_email_attach_rejects_address_already_on_another_account(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    client.post("/auth/signup", json={"username": "first-owner"})
    client.post("/auth/email", json={"email": "shared@example.com"})
    token = email_provider.last_token()
    client.get(f"/auth/magic-link/consume?token={token}")
    client.post("/auth/logout")

    client.post("/auth/signup", json={"username": "second-claimant"})
    response = client.post("/auth/email", json={"email": "shared@example.com"})

    assert response.status_code == 409


def test_magic_link_recovery_logs_into_the_right_account(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    client.post("/auth/signup", json={"username": "recoverme"})
    client.post("/auth/email", json={"email": "recoverme@example.com"})
    token = email_provider.last_token()
    client.get(f"/auth/magic-link/consume?token={token}")
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401

    recovery = client.post("/auth/magic-link", json={"email": "recoverme@example.com"})
    assert recovery.status_code == 202

    recovery_token = email_provider.last_token()
    consume = client.get(f"/auth/magic-link/consume?token={recovery_token}")
    assert consume.status_code == 200
    assert consume.json()["user"]["username"] == "recoverme"

    assert client.get("/auth/me").json()["username"] == "recoverme"


def test_magic_link_recovery_for_unregistered_email_is_silent(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    response = client.post("/auth/magic-link", json={"email": "nobody@example.com"})

    assert response.status_code == 202
    assert email_provider.sent == []


def test_email_send_failure_surfaces_as_502(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    client.post("/auth/signup", json={"username": "unlucky"})
    email_provider.fail = True

    response = client.post("/auth/email", json={"email": "unlucky@example.com"})

    assert response.status_code == 502
