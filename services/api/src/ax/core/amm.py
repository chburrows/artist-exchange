"""Linear bonding-curve AMM with a mutable anchor, plus the nightly
reversion kernel and its continuous glide (PHASE2.md).

Chosen over LMSR / constant-product because it has an exact closed form
in integer arithmetic (no float in a money path), a trivial inverse
(slippage is checkable before execution), and separates price-from-
trading from price-from-fundamentals -- the anchor tracks fair value,
the slope term prices the AMM's own inventory risk.

`spot_price(a, t) = effective_anchor(a, t) + slope * net_supply(a)`. The
k-th share bought from supply `s` costs `anchor + slope*k` for
`k = s .. s+n-1`; selling walks `k = s-1 .. s-n`. Integrating that
arithmetic series gives the closed forms below.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ax.core.config import (
    MAX_SLIPPAGE_BPS,
    REVERSION_GLIDE_HOURS,
    REVERSION_MAX_MOVE_BPS,
    REVERSION_MIN_MOVE_CENTS,
    REVERSION_RATE_BPS,
    TRADE_FEE_BPS,
)
from ax.core.money import (
    bps_ceil,
    ceil_div,
    cents_to_uc,
    uc_to_cents_ceil,
    uc_to_cents_floor,
    uc_to_cents_nearest,
)


@dataclass(frozen=True)
class BuyQuote:
    shares: int
    cost_cents: int
    fee_cents: int
    total_cents: int  # cost + fee
    exec_price_cents: int  # ceil_div(cost_cents, shares)
    spot_before_uc: int
    spot_after_uc: int


@dataclass(frozen=True)
class SellQuote:
    shares: int
    proceeds_cents: int
    fee_cents: int
    net_cents: int  # proceeds - fee
    exec_price_cents: int  # proceeds_cents // shares, floor
    spot_before_uc: int
    spot_after_uc: int


@dataclass(frozen=True)
class ReversionPlan:
    """One night's reversion, expressed as a new glide.

    `anchor_cents` is the *current* interpolated effective anchor at the
    moment the plan is made (C11) -- not the stale stored endpoint --
    so a late-firing cron never causes a discontinuous price jump.
    """

    anchor_cents: int
    anchor_target_cents: int
    glide_start_at: datetime
    glide_end_at: datetime


def spot_price_uc(anchor_uc: int, slope_uc: int, net_supply: int) -> int:
    """Marginal price (in microcents) of the *next* share at this supply."""
    return anchor_uc + slope_uc * net_supply


def buy_quote(anchor_uc: int, slope_uc: int, net_supply: int, shares: int) -> BuyQuote:
    if shares < 1:
        raise ValueError("shares must be >= 1")
    if net_supply < 0:
        raise ValueError("net_supply must be >= 0")

    n, s = shares, net_supply
    cost_uc = n * anchor_uc + slope_uc * (n * s + n * (n - 1) // 2)
    cost_cents = uc_to_cents_ceil(cost_uc)
    fee_cents = bps_ceil(cost_cents, TRADE_FEE_BPS)

    return BuyQuote(
        shares=n,
        cost_cents=cost_cents,
        fee_cents=fee_cents,
        total_cents=cost_cents + fee_cents,
        exec_price_cents=ceil_div(cost_cents, n),
        spot_before_uc=spot_price_uc(anchor_uc, slope_uc, s),
        spot_after_uc=spot_price_uc(anchor_uc, slope_uc, s + n),
    )


def sell_quote(anchor_uc: int, slope_uc: int, net_supply: int, shares: int) -> SellQuote:
    if shares < 1:
        raise ValueError("shares must be >= 1")
    if net_supply < 0:
        raise ValueError("net_supply must be >= 0")
    if shares > net_supply:
        raise ValueError("cannot sell more shares than net supply")

    n, s = shares, net_supply
    proceeds_uc = n * anchor_uc + slope_uc * (n * (s - n) + n * (n - 1) // 2)
    proceeds_cents = uc_to_cents_floor(proceeds_uc)
    fee_cents = bps_ceil(proceeds_cents, TRADE_FEE_BPS)

    return SellQuote(
        shares=n,
        proceeds_cents=proceeds_cents,
        fee_cents=fee_cents,
        net_cents=proceeds_cents - fee_cents,
        exec_price_cents=proceeds_cents // n,
        spot_before_uc=spot_price_uc(anchor_uc, slope_uc, s),
        spot_after_uc=spot_price_uc(anchor_uc, slope_uc, s - n),
    )


def max_shares_within_slippage(spot_uc: int, slope_uc: int) -> int:
    """Largest `n` such that trading `n` shares moves spot by no more than
    `MAX_SLIPPAGE_BPS` of the pre-trade spot.

    Slippage is `(spot_after - spot_before) / spot_before`, and spot moves
    exactly `slope_uc * n` per share, so `n <= spot_uc * MAX_SLIPPAGE_BPS
    / (10_000 * slope_uc)`.
    """
    return (spot_uc * MAX_SLIPPAGE_BPS) // (10_000 * slope_uc)


def effective_anchor_uc(
    anchor_uc: int,
    target_uc: int,
    glide_start: datetime,
    glide_end: datetime,
    now: datetime,
) -> int:
    """The anchor at `now`, linearly interpolated across the glide window
    in integer microcents (C1) -- never a float, so the interpolation is
    exact at both endpoints and provably monotone (I15).

    A typical 100-cent glide moves the anchor by ~1_157 uc/second, which
    is why a 2pm buyer's P&L visibly moves by 2:01pm: this is what turns
    the reversion from a discrete nightly jump into a continuous glide.
    """
    if now >= glide_end or glide_end <= glide_start:
        return target_uc
    if now <= glide_start:
        return anchor_uc

    elapsed = (now - glide_start) // timedelta(microseconds=1)
    total = (glide_end - glide_start) // timedelta(microseconds=1)
    return anchor_uc + (target_uc - anchor_uc) * elapsed // total


def reversion_move_cents(gap_cents: int, market_cents: int) -> int:
    """The pure kernel of one night's reversion (C2/C3): how many cents
    to move the anchor toward fair value, given the current gap.

    Truncating division makes the move systematically weaker than
    `REVERSION_RATE_BPS` in magnitude, which is what keeps it
    sign-symmetric (Python's `//` on negatives would otherwise make
    downward reversion 1 cent stronger than upward). The minimum-move
    floor is what makes convergence exact rather than asymptotic (I11):
    without it, gaps under ~6-7 cents would produce a zero move forever.
    """
    if gap_cents == 0:
        return 0

    raw = abs(gap_cents) * REVERSION_RATE_BPS // 10_000
    cap = max(REVERSION_MIN_MOVE_CENTS, market_cents * REVERSION_MAX_MOVE_BPS // 10_000)
    magnitude = min(cap, max(REVERSION_MIN_MOVE_CENTS, raw))
    return magnitude if gap_cents > 0 else -magnitude


def plan_reversion(
    anchor_cents: int,
    anchor_target_cents: int,
    glide_start: datetime,
    glide_end: datetime,
    slope_uc: int,
    net_supply: int,
    fair_value_cents: int,
    now: datetime,
) -> ReversionPlan:
    """Compose one night's reversion from the artist's current stored
    glide and its live market state.

    Starts from the *current interpolated* effective anchor (C11), not
    the stale stored `anchor_cents`/`anchor_target_cents` endpoint --
    the cron fires late (observed 2h late on day one in production), and
    starting from a stale endpoint would jump price discontinuously at
    reversion time, exactly what the glide exists to prevent.
    """
    eff_uc = effective_anchor_uc(
        cents_to_uc(anchor_cents), cents_to_uc(anchor_target_cents), glide_start, glide_end, now
    )
    spot_uc = spot_price_uc(eff_uc, slope_uc, net_supply)
    market_cents = uc_to_cents_nearest(spot_uc)
    gap_cents = fair_value_cents - market_cents
    move = reversion_move_cents(gap_cents, market_cents)

    new_anchor_cents = uc_to_cents_nearest(eff_uc)
    return ReversionPlan(
        anchor_cents=new_anchor_cents,
        anchor_target_cents=new_anchor_cents + move,
        glide_start_at=now,
        glide_end_at=now + timedelta(hours=REVERSION_GLIDE_HOURS),
    )
