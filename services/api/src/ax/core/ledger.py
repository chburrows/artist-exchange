"""Pure construction of ledger rows and position math.

The DB writes `LedgerEntry` rows to `transactions` in Phase 4; here they
are pure data, so Phase 2's invariant tests and market simulation
consume them directly with no session, no HTTP, no I/O.

Fees have no counterparty row -- they are burned, which is the economy's
inflation sink (CONCEPT.md "Economy inflation"). Conservation therefore
reads:

    Sum(user cash) = Sum(grants) - Sum(fees) - amm_net
    amm_net = Sum(buy costs) - Sum(sell proceeds)
"""

from dataclasses import dataclass
from enum import StrEnum

from ax.core.amm import BuyQuote, SellQuote, max_shares_within_slippage
from ax.core.config import (
    AMM_DEPTH_SHARES,
    MAX_ARTIST_EXPOSURE_BPS,
    MAX_TRADE_SHARES,
    MAX_USER_SUPPLY_SHARE_BPS,
    SCOUT_DISCOVERY_INDEX_MAX,
    SCOUT_DISCOVERY_PRICE_CENTS,
)
from ax.core.money import MICROCENTS_PER_CENT


class Kind(StrEnum):
    GRANT = "GRANT"
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"


@dataclass(frozen=True)
class LedgerEntry:
    kind: Kind
    artist_id: int | None  # None for GRANT; FEE carries the trade's artist_id
    cash_delta_cents: int
    share_delta: int  # 0 except BUY(+n)/SELL(-n)
    exec_price_cents: int | None


def grant_entries(amount_cents: int) -> list[LedgerEntry]:
    return [LedgerEntry(Kind.GRANT, None, amount_cents, 0, None)]


def buy_entries(artist_id: int, q: BuyQuote) -> list[LedgerEntry]:
    return [
        LedgerEntry(Kind.BUY, artist_id, -q.cost_cents, q.shares, q.exec_price_cents),
        LedgerEntry(Kind.FEE, artist_id, -q.fee_cents, 0, None),
    ]


def sell_entries(artist_id: int, q: SellQuote) -> list[LedgerEntry]:
    return [
        LedgerEntry(Kind.SELL, artist_id, q.proceeds_cents, -q.shares, q.exec_price_cents),
        LedgerEntry(Kind.FEE, artist_id, -q.fee_cents, 0, None),
    ]


@dataclass(frozen=True)
class PositionState:
    shares: int = 0
    avg_cost_uc: int = 0  # weighted average, fee-inclusive
    realized_pnl_cents: int = 0
    scout_shares: int = 0


def scout_qualified(index_score: float | None, exec_price_cents: int) -> bool:
    """C12: a buy is scout-qualified iff the artist was *both* below the
    score threshold *and* below the price threshold at trade time -- AND,
    not OR, so buying a merely dipped blue-chip doesn't count as
    scouting an unknown. An artist with no score yet (still `warming_up`)
    cannot be scout-qualified, since the threshold can't be evaluated."""
    if index_score is None:
        return False
    return (
        index_score < SCOUT_DISCOVERY_INDEX_MAX and exec_price_cents < SCOUT_DISCOVERY_PRICE_CENTS
    )


def apply_buy(pos: PositionState, q: BuyQuote, *, scout: bool) -> PositionState:
    """Weighted-average cost basis, fee-inclusive (so leaderboard P&L is
    honest about costs) -- floor division, drift < 1 uc/trade."""
    new_shares = pos.shares + q.shares
    new_avg_uc = (pos.shares * pos.avg_cost_uc + q.total_cents * MICROCENTS_PER_CENT) // new_shares

    return PositionState(
        shares=new_shares,
        avg_cost_uc=new_avg_uc,
        realized_pnl_cents=pos.realized_pnl_cents,
        scout_shares=pos.scout_shares + (q.shares if scout else 0),
    )


def apply_sell(pos: PositionState, q: SellQuote) -> PositionState:
    """Assumes the caller already checked `q.shares <= pos.shares`
    (`validate_sell`'s `oversell` code) -- this function is the pure
    state transition, not the guardrail.

    Scout shares reduce proportionally (floor, C12), which resists
    gaming the Talent Scout leaderboard by buying scout-qualified then
    topping up with a large non-qualified purchase before selling a
    sliver. Selling to zero necessarily zeroes scout_shares via that same
    proportional formula, but avg_cost_uc needs an explicit reset -- it
    would otherwise remain a stale nonzero value on an empty position.
    """
    n = q.shares
    realized_gain = q.net_cents - (pos.avg_cost_uc * n) // MICROCENTS_PER_CENT
    new_shares = pos.shares - n
    new_scout_shares = pos.scout_shares * new_shares // pos.shares if pos.shares else 0

    return PositionState(
        shares=new_shares,
        avg_cost_uc=pos.avg_cost_uc if new_shares > 0 else 0,
        realized_pnl_cents=pos.realized_pnl_cents + realized_gain,
        scout_shares=new_scout_shares,
    )


def _slippage_violation(spot_before_uc: int, spot_after_uc: int, shares: int) -> bool:
    """Slippage is always measured against the *pre-trade* spot
    (`spot_before_uc`), regardless of trade direction; the slope is
    recovered from the quote itself (`spot_after - spot_before = slope *
    shares` exactly, by I3) rather than threaded through as an extra
    parameter."""
    slope_uc = abs(spot_after_uc - spot_before_uc) // shares
    return shares > max_shares_within_slippage(spot_before_uc, slope_uc)


def validate_buy(
    q: BuyQuote,
    *,
    cash_cents: int,
    user_shares_after: int,
    position_value_after_cents: int,
    equity_after_cents: int,
) -> list[str]:
    violations: list[str] = []

    if q.total_cents > cash_cents:
        violations.append("overdraft")
    if q.shares > MAX_TRADE_SHARES:
        violations.append("max_trade_shares")
    if _slippage_violation(q.spot_before_uc, q.spot_after_uc, q.shares):
        violations.append("slippage")
    if user_shares_after > MAX_USER_SUPPLY_SHARE_BPS * AMM_DEPTH_SHARES // 10_000:
        violations.append("supply_share_cap")
    if position_value_after_cents > MAX_ARTIST_EXPOSURE_BPS * equity_after_cents // 10_000:
        violations.append("exposure_cap")

    return violations


def validate_sell(q: SellQuote, *, position_shares: int) -> list[str]:
    violations: list[str] = []

    if q.shares > position_shares:
        violations.append("oversell")
    if q.shares > MAX_TRADE_SHARES:
        violations.append("max_trade_shares")
    if _slippage_violation(q.spot_before_uc, q.spot_after_uc, q.shares):
        violations.append("slippage")

    return violations
