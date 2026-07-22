"""`jobs/leaderboard.py` -- the nightly equity/scout snapshot behind
PLAN.md Phase 6's leaderboards and the Portfolio page's real history
chart.
"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.core.config import STARTING_BALANCE_CENTS
from ax.db.models import EquitySnapshot, LeaderboardScout
from ax.jobs.leaderboard import run_leaderboard_snapshot
from tests.conftest import ArtistFactory, ListArtist


def _signup(client: TestClient, username: str) -> int:
    body = client.post("/auth/signup", json={"username": username}).json()
    return int(body["user"]["id"])


def test_fresh_signup_gets_an_equity_snapshot_at_starting_balance(
    client: TestClient, session: Session
) -> None:
    user_id = _signup(client, "freshling")

    result = run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    assert result.users_processed == 1
    snap = session.get(EquitySnapshot, (user_id, date(2026, 1, 1)))
    assert snap.equity_cents == STARTING_BALANCE_CENTS
    assert snap.cash_cents == STARTING_BALANCE_CENTS


def test_equity_snapshot_reflects_a_position(
    client: TestClient, session: Session, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    user_id = _signup(client, "holder")
    artist = make_artist("Held")
    list_artist(artist, fair_value_cents=1_000)
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 4})

    result = run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    assert result.users_processed == 1
    snap = session.get(EquitySnapshot, (user_id, date(2026, 1, 1)))
    # Bought shares plus a fee always costs something (C7's strict-loss
    # invariant), so post-trade equity is strictly below the starting
    # balance even though the position itself is marked to a
    # positive-spread spot price.
    assert snap.equity_cents < STARTING_BALANCE_CENTS


def test_rerunning_the_same_date_upserts_not_duplicates(
    client: TestClient, session: Session
) -> None:
    _signup(client, "retried")

    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))
    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    rows = list(
        session.scalars(select(EquitySnapshot).where(EquitySnapshot.as_of_date == date(2026, 1, 1)))
    )
    assert len(rows) == 1


def test_scout_qualified_buy_produces_a_leaderboard_scout_row(
    client: TestClient, session: Session, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    user_id = _signup(client, "scout")
    artist = make_artist("Undervalued", tier="growth")
    # index_score 30 < SCOUT_DISCOVERY_INDEX_MAX (45), fair_value_cents
    # 200 < SCOUT_DISCOVERY_PRICE_CENTS (1_000) -- both thresholds, C12.
    list_artist(artist, fair_value_cents=200, index_score=30.0)
    # 10 shares, not 1-2: at this depth/anchor a too-small buy's avg cost
    # (fee-inclusive) and post-trade spot round to the same cent, masking
    # the gap this assertion wants to exercise. 10 stays under this
    # anchor's 12-share slippage cap (MAX_SLIPPAGE_BPS) while still
    # clearing it.
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 10})

    result = run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    assert result.scout_rows == 1
    row = session.get(LeaderboardScout, user_id)
    assert row.best_artist_id == artist.id
    assert row.scout_shares == 10
    # Spot price after a large-enough buy is strictly above the average
    # cost paid (the AMM's upward-sloping cost curve), so this is a
    # genuine positive return even with fair value untouched.
    assert row.return_bps > 0


def test_non_scout_buy_produces_no_scout_row(
    client: TestClient, session: Session, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    user_id = _signup(client, "not-a-scout")
    artist = make_artist("Blue Chip", tier="blue_chip")
    # index_score 50 >= SCOUT_DISCOVERY_INDEX_MAX -- not scout-qualified.
    list_artist(artist, fair_value_cents=5_000, index_score=50.0)
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 2})

    result = run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    assert result.scout_rows == 0
    assert session.get(LeaderboardScout, user_id) is None


def test_leaderboard_scout_drops_a_row_once_the_position_is_sold(
    client: TestClient, session: Session, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    user_id = _signup(client, "sold-out-scout")
    artist = make_artist("Once Undervalued")
    list_artist(artist, fair_value_cents=200, index_score=30.0)
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 5})

    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))
    assert session.get(LeaderboardScout, user_id) is not None

    client.post("/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 5})
    run_leaderboard_snapshot(session, date(2026, 1, 2), now=datetime.now(UTC))

    assert session.get(LeaderboardScout, user_id) is None


def test_leaderboard_endpoint_requires_a_token(client: TestClient) -> None:
    response = client.post("/internal/jobs/leaderboard")
    assert response.status_code == 401


def test_leaderboard_endpoint_reports_users_processed(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _signup(client, "endpoint-check")

    response = client.post("/internal/jobs/leaderboard", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["users_processed"] >= 1
