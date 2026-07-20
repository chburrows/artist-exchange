"""`POST /trades/quote` (preview, no writes) and `POST /trades` (executes
under `SELECT ... FOR UPDATE`, PLAN.md Phase 4).

**Lock order is fixed across every request: the user's `balance_cache`
row, then the artist row.** Two different users trading the same artist
never contend on `balance_cache` (different rows); the same user trading
two different artists concurrently never contends on the artist row
(different rows). The only way either lock is *shared* between two
concurrent trades is along its own axis, so a fixed order can't produce
a cycle — this is what makes the overdraft check race-free: without
locking `balance_cache` first, two concurrent trades on two different
artists by the same user could each read the same pre-trade cash,
independently pass the overdraft check, and jointly overdraw the
account.

**`MAX_ARTIST_EXPOSURE_BPS` is checked against a snapshot of the user's
*other* positions, each marked to market independently and not locked.**
That's deliberate, not an oversight: locking every artist a user has
ever held to evaluate one soft guardrail would serialize a user's entire
trading history behind unrelated trades. A trade landing just outside
the cap because of a concurrent trade in an unrelated artist self-heals
on the next check; the overdraft check above is the one guarantee that
actually needs to be airtight, and it is.
"""

from datetime import UTC, datetime
from enum import StrEnum

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ax.api.deps import CurrentUserDep, DbDep
from ax.core.amm import BuyQuote, SellQuote, buy_quote, sell_quote
from ax.core.ledger import (
    LedgerEntry,
    apply_buy,
    apply_sell,
    buy_entries,
    scout_qualified,
    sell_entries,
    validate_buy,
    validate_sell,
)
from ax.core.money import uc_to_cents_nearest
from ax.db.ledger import get_position, lock_balance_cache, write_entries, write_position
from ax.db.market import (
    distinct_artist_ids_with_positions,
    effective_anchor_uc_now,
    is_tradable,
    latest_price_history_rows,
    spot_cents,
)
from ax.db.models import Artist, BalanceCache, IndexSnapshot, PositionCache, PriceHistory
from ax.db.models import Transaction as TransactionModel

router = APIRouter(tags=["trades"])


class TradeSide(StrEnum):
    buy = "buy"
    sell = "sell"


class TradeRequest(BaseModel):
    artist_slug: str
    side: TradeSide
    shares: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, max_length=64)


class QuoteResponse(BaseModel):
    side: TradeSide
    shares: int
    amount_cents: int
    fee_cents: int
    total_cents: int
    exec_price_cents: int
    spot_before_cents: int
    spot_after_cents: int
    violations: list[str]


class TradeResponse(BaseModel):
    transaction_id: int
    side: TradeSide
    shares: int
    exec_price_cents: int
    fee_cents: int
    cash_cents: int
    position_shares: int
    idempotent_replay: bool


def _find_tradable_artist(db: Session, slug: str, *, lock: bool = False) -> Artist:
    stmt = select(Artist).where(Artist.slug == slug)
    if lock:
        stmt = stmt.with_for_update()
    artist = db.scalars(stmt).one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artist not found")
    if not is_tradable(artist):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="artist is not currently tradable"
        )
    return artist


def _latest_index_snapshot(db: Session, artist_id: int) -> IndexSnapshot | None:
    stmt = (
        select(IndexSnapshot)
        .where(IndexSnapshot.artist_id == artist_id)
        .order_by(IndexSnapshot.as_of_date.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def _other_positions_value_cents(
    db: Session, user_id: int, exclude_artist_id: int, now: datetime
) -> int:
    """Sum of every *other* artist the user holds, each marked to its
    current spot -- see the module docstring on why this is a best-effort
    read, not a locked one."""
    artist_ids = [
        a for a in distinct_artist_ids_with_positions(db, user_id) if a != exclude_artist_id
    ]
    if not artist_ids:
        return 0

    artists = {a.id: a for a in db.scalars(select(Artist).where(Artist.id.in_(artist_ids)))}
    price_rows = latest_price_history_rows(db, artist_ids)
    positions = db.scalars(
        select(PositionCache).where(
            PositionCache.user_id == user_id, PositionCache.artist_id.in_(artist_ids)
        )
    )

    total = 0
    for position in positions:
        artist = artists.get(position.artist_id)
        price_row = price_rows.get(position.artist_id)
        if artist is None or price_row is None:
            continue
        total += position.shares * spot_cents(artist, price_row.net_supply, now)
    return total


@router.post("/trades/quote")
def quote_trade(body: TradeRequest, db: DbDep, user: CurrentUserDep) -> QuoteResponse:
    """Read-only preview -- no lock, no writes. A trade quoted here can
    still fail at execution time if state moved in between; that's
    inherent to previewing a live market, not a bug."""
    now = datetime.now(UTC)
    artist = _find_tradable_artist(db, body.artist_slug)

    price_row = latest_price_history_rows(db, [artist.id]).get(artist.id)
    net_supply = price_row.net_supply if price_row is not None else 0
    anchor_uc = effective_anchor_uc_now(artist, now)
    slope_uc = artist.slope_microcents_per_share
    assert slope_uc is not None

    balance = db.get(BalanceCache, user.id)
    cash_cents = balance.cash_cents if balance is not None else 0
    position = get_position(db, user.id, artist.id)

    q: BuyQuote | SellQuote
    try:
        if body.side is TradeSide.buy:
            q = buy_quote(anchor_uc, slope_uc, net_supply, body.shares)
            new_shares = position.shares + q.shares
            position_value_after = new_shares * q.exec_price_cents
            other_value = _other_positions_value_cents(db, user.id, artist.id, now)
            equity_after = max(0, cash_cents - q.total_cents + position_value_after + other_value)
            violations = validate_buy(
                q,
                cash_cents=cash_cents,
                user_shares_after=new_shares,
                position_value_after_cents=position_value_after,
                equity_after_cents=equity_after,
            )
            amount_cents, total_cents = q.cost_cents, q.total_cents
        else:
            q = sell_quote(anchor_uc, slope_uc, net_supply, body.shares)
            violations = validate_sell(q, position_shares=position.shares)
            amount_cents, total_cents = q.proceeds_cents, q.net_cents
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return QuoteResponse(
        side=body.side,
        shares=q.shares,
        amount_cents=amount_cents,
        fee_cents=q.fee_cents,
        total_cents=total_cents,
        exec_price_cents=q.exec_price_cents,
        spot_before_cents=uc_to_cents_nearest(q.spot_before_uc),
        spot_after_cents=uc_to_cents_nearest(q.spot_after_uc),
        violations=violations,
    )


def _replay_response(db: Session, primary: TransactionModel, user_id: int) -> TradeResponse:
    """Reconstructs the response for an idempotent retry. Finding the
    paired FEE row by `created_at` equality doesn't work: both rows are
    written in the same DB transaction and `created_at`'s `now()` default
    is *transaction-start* time (CLAUDE.md rule 9), so two *different*
    trades sharing one DB transaction (the test suite's shared-savepoint
    session does this on every test) share that same value too, and a
    `created_at ==` match can hit more than one FEE row.

    Instead: every trade this user makes is fully serialized by the fixed
    `balance_cache`-first lock order (two of this user's trades can never
    execute concurrently), so this user's own `transactions.id` values are
    strictly increasing in real execution order with no interleaving from
    anyone else's rows. `write_entries` always writes a trade's FEE row
    immediately after its BUY/SELL leg in the same flush, so the very next
    row by `id` for this user is always its pair -- the same "next row is
    the pair" rule `jobs/reconcile.py._true_positions` uses, expressed as
    a single indexed lookup instead of an in-memory walk."""
    next_row = db.scalars(
        select(TransactionModel)
        .where(TransactionModel.user_id == user_id, TransactionModel.id > primary.id)
        .order_by(TransactionModel.id)
        .limit(1)
    ).one_or_none()
    fee_cents = 0
    if next_row is not None and next_row.kind == "FEE" and next_row.artist_id == primary.artist_id:
        fee_cents = -next_row.cash_delta_cents

    balance = db.get(BalanceCache, user_id)
    position = db.get(PositionCache, (user_id, primary.artist_id))
    return TradeResponse(
        transaction_id=primary.id,
        side=TradeSide.buy if primary.kind == "BUY" else TradeSide.sell,
        shares=abs(primary.share_delta),
        exec_price_cents=primary.exec_price_cents or 0,
        fee_cents=fee_cents,
        cash_cents=balance.cash_cents if balance is not None else 0,
        position_shares=position.shares if position is not None else 0,
        idempotent_replay=True,
    )


@router.post("/trades", status_code=status.HTTP_201_CREATED)
def execute_trade(body: TradeRequest, db: DbDep, user: CurrentUserDep) -> TradeResponse:
    if body.idempotency_key:
        existing = db.scalars(
            select(TransactionModel).where(TransactionModel.idempotency_key == body.idempotency_key)
        ).one_or_none()
        if existing is not None:
            if existing.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="idempotency_key already used by another request",
                )
            return _replay_response(db, existing, user.id)

    now = datetime.now(UTC)

    # Computed before any locks are taken. Best-effort and unlocked by
    # design (see module docstring) -- it only feeds the soft
    # MAX_ARTIST_EXPOSURE_BPS guardrail, never the overdraft check, so
    # there's no correctness reason to pay its ~4 extra queries while
    # holding the balance_cache/artist locks below instead of before them.
    # An unresolved slug here just means an empty "other positions" set;
    # the real 404/409 for a bad slug still comes from the locked lookup.
    other_value = 0
    if body.side is TradeSide.buy:
        exposure_artist_id = db.scalars(
            select(Artist.id).where(Artist.slug == body.artist_slug)
        ).one_or_none()
        if exposure_artist_id is not None:
            other_value = _other_positions_value_cents(db, user.id, exposure_artist_id, now)

    # Fixed lock order -- see module docstring.
    balance = lock_balance_cache(db, user.id)
    artist = _find_tradable_artist(db, body.artist_slug, lock=True)

    price_row = latest_price_history_rows(db, [artist.id]).get(artist.id)
    net_supply = price_row.net_supply if price_row is not None else 0
    anchor_uc = effective_anchor_uc_now(artist, now)
    slope_uc = artist.slope_microcents_per_share
    assert slope_uc is not None

    position = get_position(db, user.id, artist.id)
    index_snapshot = _latest_index_snapshot(db, artist.id)
    index_score = index_snapshot.index_score if index_snapshot is not None else None
    fair_value_cents = index_snapshot.fair_value_cents if index_snapshot is not None else None

    # Each side's quote, validation, and ledger-entry construction stay in
    # one branch (rather than three separate `if body.side is ...` blocks
    # sharing a `q: BuyQuote | SellQuote` variable) so mypy narrows `q` to
    # the concrete quote type throughout -- `validate_buy`/`buy_entries`
    # and `validate_sell`/`sell_entries` each require their own type, and
    # `body.side` alone doesn't statically prove which one `q` is.
    violations: list[str]
    entries: list[LedgerEntry]
    if body.side is TradeSide.buy:
        try:
            buy_q = buy_quote(anchor_uc, slope_uc, net_supply, body.shares)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        new_shares = position.shares + buy_q.shares
        position_value_after = new_shares * buy_q.exec_price_cents
        equity_after = max(
            0, balance.cash_cents - buy_q.total_cents + position_value_after + other_value
        )
        violations = validate_buy(
            buy_q,
            cash_cents=balance.cash_cents,
            user_shares_after=new_shares,
            position_value_after_cents=position_value_after,
            equity_after_cents=equity_after,
        )
        if not violations:
            scout = scout_qualified(index_score, buy_q.exec_price_cents)
            entries = buy_entries(artist.id, buy_q)
            new_position = apply_buy(position, buy_q, scout=scout)
            new_supply = net_supply + buy_q.shares
        q: BuyQuote | SellQuote = buy_q
    else:
        try:
            sell_q = sell_quote(anchor_uc, slope_uc, net_supply, body.shares)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        violations = validate_sell(sell_q, position_shares=position.shares)
        if not violations:
            entries = sell_entries(artist.id, sell_q)
            new_position = apply_sell(position, sell_q)
            new_supply = net_supply - sell_q.shares
        q = sell_q

    if violations:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"violations": violations}
        )

    try:
        rows = write_entries(
            db,
            balance,
            user.id,
            entries,
            index_score_at_trade=index_score,
            fair_value_cents_at_trade=fair_value_cents,
            idempotency_key=body.idempotency_key,
        )
        write_position(db, user.id, artist.id, new_position)
        db.add(
            PriceHistory(
                artist_id=artist.id,
                market_price_cents=uc_to_cents_nearest(q.spot_after_uc),
                fair_value_cents=fair_value_cents,
                net_supply=new_supply,
                source="trade",
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A concurrent request with the same idempotency_key committed
        # first, between our pre-check above and this write.
        if body.idempotency_key:
            existing = db.scalars(
                select(TransactionModel).where(
                    TransactionModel.idempotency_key == body.idempotency_key
                )
            ).one_or_none()
            if existing is not None:
                return _replay_response(db, existing, user.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="trade could not be committed"
        ) from exc

    primary = rows[0]
    return TradeResponse(
        transaction_id=primary.id,
        side=body.side,
        shares=q.shares,
        exec_price_cents=q.exec_price_cents,
        fee_cents=q.fee_cents,
        cash_cents=balance.cash_cents,
        position_shares=new_position.shares,
        idempotent_replay=False,
    )
