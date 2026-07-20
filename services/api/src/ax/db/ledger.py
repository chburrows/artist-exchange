"""DB-layer ledger writes — the I/O counterpart to `ax.core.ledger`'s pure
entry construction and state transitions.

Every write here happens inside a transaction the caller already holds
the right lock for (CLAUDE.md rule 8): the user's own `balance_cache` row
for anything touching cash, the artist row for anything touching
`net_supply`, both taken `FOR UPDATE` before this module is called.
`balance_cache` is locked first in every caller and no caller locks a
second user's balance row in the same transaction, so that fixed
ordering cannot deadlock against the artist-row lock.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.core.ledger import LedgerEntry, PositionState
from ax.db.models import BalanceCache, PositionCache, Transaction


def lock_balance_cache(session: Session, user_id: int) -> BalanceCache:
    """`SELECT ... FOR UPDATE` on the user's balance row, creating it
    with zero cash if this is somehow the first time it's touched
    (should not happen post-signup, but a missing row must not crash a
    trade)."""
    row = session.execute(
        select(BalanceCache).where(BalanceCache.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if row is not None:
        return row

    row = BalanceCache(user_id=user_id, cash_cents=0)
    session.add(row)
    session.flush()
    return session.execute(
        select(BalanceCache).where(BalanceCache.user_id == user_id).with_for_update()
    ).scalar_one()


def get_position(session: Session, user_id: int, artist_id: int) -> PositionState:
    """Current position as the pure `PositionState` the core ledger
    functions operate on. No lock of its own -- safe because every
    caller already holds the artist row lock, which is what serializes
    writers to this `(user_id, artist_id)` row for BUY/SELL."""
    row = session.get(PositionCache, (user_id, artist_id))
    if row is None:
        return PositionState()
    return PositionState(
        shares=row.shares,
        avg_cost_uc=row.avg_cost_microcents,
        realized_pnl_cents=row.realized_pnl_cents,
        scout_shares=row.scout_shares,
    )


def write_entries(
    session: Session,
    balance: BalanceCache,
    user_id: int,
    entries: list[LedgerEntry],
    *,
    index_score_at_trade: float | None = None,
    fair_value_cents_at_trade: int | None = None,
    idempotency_key: str | None = None,
) -> list[Transaction]:
    """Appends every entry to `transactions` and folds its cash delta
    into the already-locked `balance` row (mutating the locked ORM
    object directly is safe -- and correct, not just convenient -- only
    because the caller holds the row lock for the whole transaction, so
    no concurrent writer can interleave between this read and the
    eventual flush).

    `index_score_at_trade` / `fair_value_cents_at_trade` /
    `idempotency_key` are stamped on the first entry only, never on a
    paired FEE row -- callers pass a list where the first entry is the
    GRANT/BUY/SELL leg by construction (`ax.core.ledger.grant_entries` /
    `buy_entries` / `sell_entries`).
    """
    rows = []
    for i, entry in enumerate(entries):
        row = Transaction(
            user_id=user_id,
            artist_id=entry.artist_id,
            kind=entry.kind.value,
            cash_delta_cents=entry.cash_delta_cents,
            share_delta=entry.share_delta,
            exec_price_cents=entry.exec_price_cents,
            index_score_at_trade=index_score_at_trade if i == 0 else None,
            fair_value_cents_at_trade=fair_value_cents_at_trade if i == 0 else None,
            idempotency_key=idempotency_key if i == 0 else None,
        )
        session.add(row)
        rows.append(row)
        balance.cash_cents += entry.cash_delta_cents

    session.flush()
    return rows


def write_position(session: Session, user_id: int, artist_id: int, state: PositionState) -> None:
    row = session.get(PositionCache, (user_id, artist_id))
    if row is None:
        row = PositionCache(user_id=user_id, artist_id=artist_id)
        session.add(row)
    row.shares = state.shares
    row.avg_cost_microcents = state.avg_cost_uc
    row.realized_pnl_cents = state.realized_pnl_cents
    row.scout_shares = state.scout_shares
