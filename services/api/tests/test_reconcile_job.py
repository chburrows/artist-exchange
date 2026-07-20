"""`jobs/reconcile.py` -- rebuilding `balance_cache`/`position_cache`
from `transactions` and catching any drift between them.

Every trade already writes the cache atomically with its ledger append
(CLAUDE.md rule 8), so the "no drift after normal trading" tests below
are really an end-to-end check on that atomicity. The drift tests
simulate the failure this job exists to catch by corrupting a cache row
directly -- the only way to produce disagreement without a real bug in
the trade route.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ax.core.config import STARTING_BALANCE_CENTS
from ax.db.models import BalanceCache, PositionCache
from ax.jobs.reconcile import run_reconcile
from tests.conftest import ArtistFactory, ListArtist


def _signup(client: TestClient, username: str) -> int:
    body = client.post("/auth/signup", json={"username": username}).json()
    return int(body["user"]["id"])


def test_no_drift_after_a_clean_trade_history(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
) -> None:
    user_id = _signup(client, "clean-trader")
    artist = make_artist("Cleanly Traded")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 5})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 2})

    balance_before = session.get(BalanceCache, user_id).cash_cents
    position_before = session.get(PositionCache, (user_id, artist.id))

    result = run_reconcile(session, now=datetime.now(UTC))

    assert result.balance_mismatches == []
    assert result.position_mismatches == []
    assert session.get(BalanceCache, user_id).cash_cents == balance_before
    refreshed = session.get(PositionCache, (user_id, artist.id))
    assert refreshed.shares == position_before.shares
    assert refreshed.avg_cost_microcents == position_before.avg_cost_microcents
    assert refreshed.realized_pnl_cents == position_before.realized_pnl_cents


def test_repairs_corrupted_balance_cache(client: TestClient, session: Session) -> None:
    user_id = _signup(client, "corrupted-balance")

    balance = session.get(BalanceCache, user_id)
    balance.cash_cents = 1  # simulate drift
    session.flush()

    result = run_reconcile(session, now=datetime.now(UTC))

    assert len(result.balance_mismatches) == 1
    assert result.balance_mismatches[0]["user_id"] == user_id
    assert session.get(BalanceCache, user_id).cash_cents == STARTING_BALANCE_CENTS


def test_repairs_corrupted_position_cache(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
) -> None:
    user_id = _signup(client, "corrupted-position")
    artist = make_artist("Corrupted")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 6})
    true_shares = session.get(PositionCache, (user_id, artist.id)).shares

    position = session.get(PositionCache, (user_id, artist.id))
    position.shares = 999
    position.scout_shares = 999
    session.flush()

    result = run_reconcile(session, now=datetime.now(UTC))

    assert len(result.position_mismatches) == 1
    assert result.position_mismatches[0]["artist_id"] == artist.id
    repaired = session.get(PositionCache, (user_id, artist.id))
    assert repaired.shares == true_shares


def test_recreates_a_missing_balance_cache_row(client: TestClient, session: Session) -> None:
    user_id = _signup(client, "missing-balance")
    session.delete(session.get(BalanceCache, user_id))
    session.flush()

    result = run_reconcile(session, now=datetime.now(UTC))

    assert len(result.balance_mismatches) == 1
    assert session.get(BalanceCache, user_id).cash_cents == STARTING_BALANCE_CENTS


def test_weighted_average_cost_survives_a_reconcile_round_trip(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
) -> None:
    """Two buys at different prices, then a partial sell -- exercises the
    real weighted-average/realized-pnl formulas (`ax.core.ledger`), not
    just share counts, through a full replay."""
    user_id = _signup(client, "cost-basis")
    artist = make_artist("Averaged")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 3})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 4})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 2})

    before = session.get(PositionCache, (user_id, artist.id))
    before_snapshot = (
        before.shares,
        before.avg_cost_microcents,
        before.realized_pnl_cents,
    )

    result = run_reconcile(session, now=datetime.now(UTC))

    assert result.position_mismatches == []
    after = session.get(PositionCache, (user_id, artist.id))
    assert (after.shares, after.avg_cost_microcents, after.realized_pnl_cents) == before_snapshot


def test_reconcile_endpoint_requires_a_token(client: TestClient) -> None:
    response = client.post("/internal/jobs/reconcile")
    assert response.status_code == 401


def test_reconcile_endpoint_reports_users_checked(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _signup(client, "endpoint-check")

    response = client.post("/internal/jobs/reconcile", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["users_checked"] >= 1
    assert response.json()["balance_mismatches"] == []
