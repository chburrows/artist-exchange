"""`POST /trades/quote` and `POST /trades`, end to end through the real
app -- the money-moving path, so correctness here matters more than
anywhere else in Phase 4.

Most tests use the shared per-test savepoint session (`client`,
`list_artist`). The concurrency test at the bottom deliberately does not:
proving the `FOR UPDATE` lock actually serializes two writers requires
two independent, really-committed database connections contending on the
same row, which a single shared transaction can't simulate.
"""

import threading
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from ax.core.amm import buy_quote, listing_slope_uc
from ax.core.config import STARTING_BALANCE_CENTS, TRADE_FEE_BPS
from ax.db.models import (
    Artist,
    BalanceCache,
    IndexSnapshot,
    PositionCache,
    PriceHistory,
    Transaction,
    User,
)
from tests.conftest import ArtistFactory, ListArtist


def _signup(client: TestClient, username: str) -> dict:
    response = client.post("/auth/signup", json={"username": username})
    assert response.status_code == 201
    return response.json()


def test_quote_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/trades/quote", json={"artist_slug": "nobody", "side": "buy", "shares": 1}
    )
    assert response.status_code == 401


def test_quote_unknown_artist_is_404(client: TestClient) -> None:
    _signup(client, "quoter")
    response = client.post(
        "/trades/quote", json={"artist_slug": "does-not-exist", "side": "buy", "shares": 1}
    )
    assert response.status_code == 404


def test_quote_unlisted_artist_is_409(client: TestClient, make_artist: ArtistFactory) -> None:
    _signup(client, "quoter2")
    artist = make_artist("Warming Up")
    response = client.post(
        "/trades/quote", json={"artist_slug": artist.slug, "side": "buy", "shares": 1}
    )
    assert response.status_code == 409


def test_quote_buy_matches_core_amm(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    _signup(client, "quoter3")
    artist = make_artist("Quotable")
    list_artist(artist, fair_value_cents=1_000)

    response = client.post(
        "/trades/quote", json={"artist_slug": artist.slug, "side": "buy", "shares": 5}
    )
    assert response.status_code == 200
    body = response.json()

    expected = buy_quote(1_000 * 1_000_000, listing_slope_uc(), 0, 5)
    assert body["shares"] == 5
    assert body["amount_cents"] == expected.cost_cents
    assert body["fee_cents"] == expected.fee_cents
    assert body["total_cents"] == expected.total_cents
    assert body["exec_price_cents"] == expected.exec_price_cents
    assert body["violations"] == []


def test_execute_buy_updates_balance_and_position(
    client: TestClient,
    session: OrmSession,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
) -> None:
    user = _signup(client, "buyer")
    artist = make_artist("Buyable")
    list_artist(artist, fair_value_cents=1_000)

    response = client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 3})
    assert response.status_code == 201
    body = response.json()
    assert body["shares"] == 3
    assert body["idempotent_replay"] is False
    assert body["cash_cents"] < STARTING_BALANCE_CENTS

    balance = session.get(BalanceCache, user["user"]["id"])
    assert balance is not None
    assert balance.cash_cents == body["cash_cents"]

    position = session.get(PositionCache, (user["user"]["id"], artist.id))
    assert position is not None
    assert position.shares == 3

    latest_price = session.scalars(
        select(PriceHistory)
        .where(PriceHistory.artist_id == artist.id)
        .order_by(PriceHistory.id.desc())
        .limit(1)
    ).one()
    assert latest_price.source == "trade"
    assert latest_price.net_supply == 3

    transactions = session.scalars(
        select(Transaction).where(Transaction.user_id == user["user"]["id"])
    ).all()
    kinds = sorted(t.kind for t in transactions if t.kind != "GRANT")
    assert kinds == ["BUY", "FEE"]


def test_execute_buy_insufficient_funds_is_422(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    _signup(client, "pauper")
    artist = make_artist("Expensive")
    # One share alone costs far more than STARTING_BALANCE_CENTS.
    list_artist(artist, fair_value_cents=2_000_000)

    response = client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 1})

    assert response.status_code == 422
    assert "overdraft" in response.json()["detail"]["violations"]


def test_execute_sell_with_zero_net_supply_is_422(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    """No shares exist yet (net_supply == 0), so the AMM curve itself
    rejects the sell before the position-ownership check ever runs."""
    _signup(client, "no-position")
    artist = make_artist("Unowned")
    list_artist(artist, fair_value_cents=1_000)

    response = client.post(
        "/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 1}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_execute_sell_more_than_owned_is_422(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    """Supply exists (someone else bought in), but *this* user holds
    none of it -- the oversell violation from `validate_sell`."""
    artist = make_artist("Partly Owned")
    list_artist(artist, fair_value_cents=1_000)

    _signup(client, "owner")
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 5})
    client.post("/auth/logout")

    _signup(client, "bystander")
    response = client.post(
        "/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 1}
    )

    assert response.status_code == 422
    assert "oversell" in response.json()["detail"]["violations"]


def test_buy_then_sell_round_trip_loses_money(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    """PLAN.md's Phase 4 'done when': signup -> quote -> buy -> portfolio
    -> sell -> portfolio shows the expected fee-driven round-trip loss."""
    user = _signup(client, "roundtripper")
    artist = make_artist("Round Tripper")
    list_artist(artist, fair_value_cents=1_000)

    buy = client.post(
        "/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 10}
    ).json()
    sell = client.post(
        "/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 10}
    ).json()

    spent = STARTING_BALANCE_CENTS - buy["cash_cents"]
    received = sell["cash_cents"] - buy["cash_cents"]
    loss = spent - received
    # Loss measured against the trade's own notional, not the whole
    # starting balance ($100 traded out of a $10,000 balance is a real
    # loss that's still tiny as a fraction of net worth). Two fee legs
    # at TRADE_FEE_BPS each is the floor; slippage from the AMM's own
    # slope adds on top, so this is a lower bound, not an exact match.
    loss_bps_of_notional = loss * 10_000 // spent
    assert loss_bps_of_notional >= 2 * TRADE_FEE_BPS
    assert sell["position_shares"] == 0
    del user  # asserted indirectly via cash figures above


def test_idempotency_key_prevents_double_charge(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    _signup(client, "retrier")
    artist = make_artist("Retryable")
    list_artist(artist, fair_value_cents=1_000)
    key = str(uuid4())

    first = client.post(
        "/trades",
        json={"artist_slug": artist.slug, "side": "buy", "shares": 4, "idempotency_key": key},
    )
    second = client.post(
        "/trades",
        json={"artist_slug": artist.slug, "side": "buy", "shares": 4, "idempotency_key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["transaction_id"] == second.json()["transaction_id"]
    assert second.json()["idempotent_replay"] is True
    assert first.json()["cash_cents"] == second.json()["cash_cents"]


def test_idempotency_key_is_scoped_to_the_original_user(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    artist = make_artist("Contested")
    list_artist(artist, fair_value_cents=1_000)
    key = str(uuid4())

    _signup(client, "owner")
    client.post(
        "/trades",
        json={"artist_slug": artist.slug, "side": "buy", "shares": 1, "idempotency_key": key},
    )
    client.post("/auth/logout")

    _signup(client, "interloper")
    response = client.post(
        "/trades",
        json={"artist_slug": artist.slug, "side": "buy", "shares": 1, "idempotency_key": key},
    )

    assert response.status_code == 409


def test_concurrent_buys_on_one_artist_serialize(engine: Engine) -> None:
    """Two real, independent connections racing `FOR UPDATE` on the same
    artist row -- the property PLAN.md's testing strategy calls out by
    name ("concurrent buys on one artist don't corrupt supply"). A
    single shared savepoint session can't exercise real lock contention,
    so this test commits for real and cleans up after itself.
    """
    from ax.api.routers.trades import TradeRequest, TradeSide, execute_trade

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    setup = SessionLocal()

    suffix = uuid4().hex[:8]
    user = User(username=f"racer-{suffix}")
    setup.add(user)
    setup.flush()
    setup.add(BalanceCache(user_id=user.id, cash_cents=STARTING_BALANCE_CENTS))

    artist = Artist(
        slug=f"racer-artist-{suffix}",
        name="Racer Artist",
        lastfm_name="Racer Artist",
        tier="growth",
    )
    setup.add(artist)
    setup.flush()

    now = datetime.now(UTC)
    artist.slope_microcents_per_share = listing_slope_uc()
    artist.anchor_cents = 1_000
    artist.anchor_target_cents = 1_000
    artist.glide_start_at = now
    artist.glide_end_at = now
    artist.listed_at = now
    setup.add(
        IndexSnapshot(
            artist_id=artist.id,
            as_of_date=now.date(),
            index_score=50.0,
            fair_value_cents=1_000,
            components={"v": 1},
        )
    )
    setup.add(
        PriceHistory(
            artist_id=artist.id,
            market_price_cents=1_000,
            fair_value_cents=1_000,
            net_supply=0,
            source="listing",
        )
    )
    setup.commit()
    user_id, artist_id, artist_slug = user.id, artist.id, artist.slug
    setup.close()

    results: list[object] = []
    errors: list[BaseException] = []

    def buy_ten() -> None:
        thread_session = SessionLocal()
        try:
            thread_user = thread_session.get(User, user_id)
            assert thread_user is not None
            body = TradeRequest(artist_slug=artist_slug, side=TradeSide.buy, shares=10)
            results.append(execute_trade(body, thread_session, thread_user))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            thread_session.close()

    threads = [threading.Thread(target=buy_ten) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, errors
        assert len(results) == 2

        check = SessionLocal()
        position = check.get(PositionCache, (user_id, artist_id))
        assert position is not None
        assert position.shares == 20

        latest = check.scalars(
            select(PriceHistory)
            .where(PriceHistory.artist_id == artist_id)
            .order_by(PriceHistory.id.desc())
            .limit(1)
        ).one()
        assert latest.net_supply == 20

        balance = check.get(BalanceCache, user_id)
        assert balance is not None
        assert balance.cash_cents >= 0
        check.close()
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(Transaction).where(Transaction.user_id == user_id))
        cleanup.execute(delete(PositionCache).where(PositionCache.user_id == user_id))
        cleanup.execute(delete(BalanceCache).where(BalanceCache.user_id == user_id))
        cleanup.execute(delete(PriceHistory).where(PriceHistory.artist_id == artist_id))
        cleanup.execute(delete(IndexSnapshot).where(IndexSnapshot.artist_id == artist_id))
        cleanup.execute(delete(Artist).where(Artist.id == artist_id))
        cleanup.execute(delete(User).where(User.id == user_id))
        cleanup.commit()
        cleanup.close()
