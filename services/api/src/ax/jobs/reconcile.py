"""Nightly cache reconciliation (PLAN.md Phase 4).

`balance_cache`/`position_cache` are written atomically with every
ledger append (CLAUDE.md rule 8), so drift should be structurally
impossible -- this job is what makes that "should be" trustworthy rather
than merely assumed. It rebuilds both caches independently from
`transactions`, the only real source of truth, and overwrites any row
that disagrees.

**Balance** is a plain `SUM(cash_delta_cents)` -- `v_balances`, the view
created for exactly this purpose (PLAN.md's "definition of truth"),
queried directly rather than re-deriving the same SQL in Python.

**Positions** are not a plain sum.** `avg_cost_microcents` (a weighted
average) and `realized_pnl_cents` are order-dependent -- not SQL
aggregates -- so `v_positions` only covers `shares`. Full position
truth means replaying every BUY/SELL through the same pure,
invariant-tested `ax.core.ledger.apply_buy`/`apply_sell` the trade route
itself uses, in `(created_at, id)` order. The BUY/SELL row and its
paired FEE row are matched by `created_at`, for the same reason
`api/routers/trades.py._replay_response` does: both are written in the
same DB transaction, so they share the exact `now()`-at-transaction-start
value (CLAUDE.md rule 9).

**No artist-row or position-row locking during the read/replay.** A
concurrent trade could, in principle, commit between this job's read of
`transactions` and its overwrite of the cache row for the same user, in
which case this job's write briefly reintroduces the drift it was meant
to fix. Bounded and self-correcting (the next run rebuilds from
`transactions` again, which the trade already updated) -- the same
category of accepted risk as `jobs/recompute.py`'s net_supply staleness
note. Locking every user's entire trading history against every
concurrent trade to close this would serialize the whole platform behind
a nightly job for a window that heals itself within a day.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ax.core.amm import BuyQuote, SellQuote
from ax.core.ledger import PositionState, apply_buy, apply_sell, scout_qualified
from ax.db.ledger import lock_balance_cache, write_position
from ax.db.models import PositionCache, Transaction, User

log = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    users_checked: int = 0
    balance_mismatches: list[dict[str, object]] = field(default_factory=list)
    position_mismatches: list[dict[str, object]] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "users_checked": self.users_checked,
            "balance_mismatches": self.balance_mismatches,
            "position_mismatches": self.position_mismatches,
        }


def _true_balance_cents(session: Session, user_id: int) -> int:
    row = session.execute(
        text("SELECT cash_cents FROM v_balances WHERE user_id = :user_id"), {"user_id": user_id}
    ).one_or_none()
    return int(row.cash_cents) if row is not None else 0


def _true_positions(session: Session, user_id: int) -> dict[int, PositionState]:
    """Replays every BUY/SELL for `user_id`, in ledger order, through the
    real core state transitions. Returns only artists with at least one
    trade -- a caller comparing against existing cache rows must still
    check for cache rows this doesn't mention (a position that should
    have been zeroed out and dropped by a prior bug)."""
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.kind.in_(["BUY", "SELL", "FEE"]))
        .order_by(Transaction.created_at, Transaction.id)
    )
    rows = list(session.scalars(stmt))

    positions: dict[int, PositionState] = {}
    i = 0
    while i < len(rows):
        row = rows[i]
        if row.kind not in ("BUY", "SELL"):
            # A standalone FEE without a preceding BUY/SELL would mean
            # `write_entries` wrote one on its own, which it never does.
            i += 1
            continue

        # `write_entries` always writes a trade's FEE row immediately
        # after its BUY/SELL leg, in the same flush -- so the very next
        # row for the same artist is always its pair. Matching this way
        # (rather than joining on `created_at`) is what stays correct
        # even when two trades share one DB transaction and therefore
        # one `now()` value, as every trade in a single test session
        # does (`created_at`'s `now()` default is transaction-start
        # time, CLAUDE.md rule 9) -- a `created_at`-keyed join would
        # silently pair a BUY with an unrelated trade's fee in exactly
        # that case.
        assert row.artist_id is not None
        fee_cents = 0
        if i + 1 < len(rows):
            fee_row = rows[i + 1]
            if fee_row.kind == "FEE" and fee_row.artist_id == row.artist_id:
                fee_cents = -fee_row.cash_delta_cents
                i += 1
        i += 1

        pos = positions.get(row.artist_id, PositionState())
        exec_price_cents = row.exec_price_cents or 0

        if row.kind == "BUY":
            # `Transaction.cash_delta_cents` on a BUY row is `-cost_cents`
            # alone (`ax.core.ledger.buy_entries`) -- the fee is its own
            # paired FEE row, not folded in here.
            cost_cents = -row.cash_delta_cents
            buy_q = BuyQuote(
                shares=row.share_delta,
                cost_cents=cost_cents,
                fee_cents=fee_cents,
                total_cents=cost_cents + fee_cents,
                exec_price_cents=exec_price_cents,
                spot_before_uc=0,  # unused by apply_buy; not reconstructable from the ledger alone
                spot_after_uc=0,
            )
            scout = scout_qualified(row.index_score_at_trade, exec_price_cents)
            positions[row.artist_id] = apply_buy(pos, buy_q, scout=scout)
        else:
            proceeds_cents = row.cash_delta_cents
            sell_q = SellQuote(
                shares=-row.share_delta,
                proceeds_cents=proceeds_cents,
                fee_cents=fee_cents,
                net_cents=proceeds_cents - fee_cents,
                exec_price_cents=exec_price_cents,
                spot_before_uc=0,
                spot_after_uc=0,
            )
            positions[row.artist_id] = apply_sell(pos, sell_q)

    return positions


def _positions_differ(cached: PositionCache, true_state: PositionState) -> bool:
    return (
        cached.shares != true_state.shares
        or cached.avg_cost_microcents != true_state.avg_cost_uc
        or cached.realized_pnl_cents != true_state.realized_pnl_cents
        or cached.scout_shares != true_state.scout_shares
    )


def run_reconcile(session: Session, *, now: datetime) -> ReconcileResult:
    result = ReconcileResult()

    for user_id in session.scalars(select(User.id)):
        result.users_checked += 1

        true_balance = _true_balance_cents(session, user_id)
        balance = lock_balance_cache(session, user_id)
        if balance.cash_cents != true_balance:
            log.warning(
                "balance_cache drift for user_id=%s: cached=%s true=%s",
                user_id,
                balance.cash_cents,
                true_balance,
            )
            result.balance_mismatches.append(
                {"user_id": user_id, "cached_cents": balance.cash_cents, "true_cents": true_balance}
            )
            balance.cash_cents = true_balance

        true_positions = _true_positions(session, user_id)
        cached_rows = {
            row.artist_id: row
            for row in session.scalars(
                select(PositionCache).where(PositionCache.user_id == user_id)
            )
        }

        for artist_id in set(true_positions) | set(cached_rows):
            true_state = true_positions.get(artist_id, PositionState())
            cached_row = cached_rows.get(artist_id)

            if cached_row is not None and not _positions_differ(cached_row, true_state):
                continue

            log.warning(
                "position_cache drift for user_id=%s artist_id=%s: cached=%s true=%s",
                user_id,
                artist_id,
                None
                if cached_row is None
                else {
                    "shares": cached_row.shares,
                    "avg_cost_microcents": cached_row.avg_cost_microcents,
                    "realized_pnl_cents": cached_row.realized_pnl_cents,
                    "scout_shares": cached_row.scout_shares,
                },
                true_state,
            )
            result.position_mismatches.append(
                {
                    "user_id": user_id,
                    "artist_id": artist_id,
                    "true_shares": true_state.shares,
                }
            )
            write_position(session, user_id, artist_id, true_state)

    session.commit()
    return result
