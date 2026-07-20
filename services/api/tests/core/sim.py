"""Deterministic market simulation for I14 -- the anti-arbitrage claim.

Test-only, not product code: `ax.core`'s AMM/reversion/ledger functions
are exercised against a seeded synthetic market (200 artists, 200 days,
no DB, no network, stdlib `random.Random(seed)` only) to answer the
product's central economic question -- can a bot that mechanically buys
the price-to-fair-value gap, without evaluating any artist, turn a
profit? -- with two adversaries of increasing sophistication.

Each day, in order: (1) `plan_reversion` runs for every artist; (2) the
bot trades *at glide start* (the pre-glide price -- the entry most
favorable to the bot, which makes the test conservative); (3) the glide
completes fully before the next day (a 24h glide sampled once daily
needs no intraday modeling). Bot trades go through the real
`buy_quote`/`sell_quote`/`validate_buy`/`validate_sell`/ledger
functions, so fees, market impact (the bot's own supply moves persist),
slippage, and position caps are all live.
"""

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ax.core.amm import buy_quote, listing_slope_uc, plan_reversion, sell_quote, spot_price_uc
from ax.core.config import (
    FAIR_VALUE_BASE_CENTS,
    MAX_TRADE_SHARES,
    REVERSION_GLIDE_HOURS,
)
from ax.core.ledger import validate_buy, validate_sell
from ax.core.money import cents_to_uc, uc_to_cents_nearest

NUM_ARTISTS = 200
NUM_DAYS = 200
FAIR_VALUE_FLOOR_CENTS = 50
FAIR_VALUE_CEIL_CENTS = 5_000
STARTING_CASH_CENTS = 1_000_000  # matches STARTING_BALANCE_CENTS

# The platform-wide AMM slope (PLAN.md): fixed across artists and time.
SLOPE_UC = listing_slope_uc()

_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
_GLIDE = timedelta(hours=REVERSION_GLIDE_HOURS)


@dataclass
class ArtistState:
    fair_value_series: list[int]
    anchor_cents: int
    anchor_target_cents: int
    glide_start_at: datetime
    glide_end_at: datetime
    net_supply: int = 0


def _fair_value_series(rng: random.Random, num_days: int, sigma_daily: float) -> list[int]:
    """A seeded geometric random walk, clamped to
    [FAIR_VALUE_FLOOR_CENTS, FAIR_VALUE_CEIL_CENTS]. The walk itself
    continues from the unclamped float so a long run pinned at a bound
    doesn't freeze -- only the *published* daily value is clamped."""
    fair = float(FAIR_VALUE_BASE_CENTS)
    series = [round(fair)]
    for _ in range(num_days - 1):
        fair *= math.exp(rng.gauss(0, sigma_daily))
        published = min(max(fair, FAIR_VALUE_FLOOR_CENTS), FAIR_VALUE_CEIL_CENTS)
        series.append(round(published))
    return series


def build_market(
    seed: int, sigma_daily: float, num_artists: int = NUM_ARTISTS, num_days: int = NUM_DAYS
) -> list[ArtistState]:
    """A fresh, deterministic market: same `(seed, sigma_daily)` always
    produces the same fair-value walks. Every artist starts already
    fully glided to its own day-0 fair value (a zero-gap, `net_supply=0`
    steady state), so the very first day's reversion is a genuine no-op
    rather than an artificial jump."""
    rng = random.Random(seed)
    artists = []
    for _ in range(num_artists):
        series = _fair_value_series(rng, num_days, sigma_daily)
        start = series[0]
        artists.append(
            ArtistState(
                fair_value_series=series,
                anchor_cents=start,
                anchor_target_cents=start,
                glide_start_at=_EPOCH - _GLIDE,
                glide_end_at=_EPOCH,
            )
        )
    return artists


def _advance_reversion(artists: list[ArtistState], day: int) -> None:
    now = _EPOCH + timedelta(days=day)
    for artist in artists:
        plan = plan_reversion(
            artist.anchor_cents,
            artist.anchor_target_cents,
            artist.glide_start_at,
            artist.glide_end_at,
            SLOPE_UC,
            artist.net_supply,
            artist.fair_value_series[day],
            now,
        )
        artist.anchor_cents = plan.anchor_cents
        artist.anchor_target_cents = plan.anchor_target_cents
        artist.glide_start_at = plan.glide_start_at
        artist.glide_end_at = plan.glide_end_at


def _market_price_cents(artist: ArtistState) -> int:
    spot_uc = spot_price_uc(cents_to_uc(artist.anchor_cents), SLOPE_UC, artist.net_supply)
    return uc_to_cents_nearest(spot_uc)


def _gap_fraction(artist: ArtistState, day: int) -> float:
    """`(fair - market) / market`: positive means undervalued (a discount)."""
    market = _market_price_cents(artist)
    if market <= 0:
        return 0.0
    return (artist.fair_value_series[day] - market) / market


def _size_buy(
    artist: ArtistState,
    budget_cents: int,
    cash_cents: int,
    equity_cents: int,
    held_shares: int,
    max_shares_cap: int = MAX_TRADE_SHARES,
) -> int:
    """Largest whole share count, within `[0, max_shares_cap]`, that both
    fits `budget_cents` and clears every `validate_buy` guardrail.
    Binary search is valid because cost, price impact, and share count
    are all monotone increasing in `n`, so "is `n` shares acceptable" is
    a monotone predicate."""
    anchor_uc = cents_to_uc(artist.anchor_cents)

    def acceptable(n: int) -> bool:
        if n < 1:
            return False
        q = buy_quote(anchor_uc, SLOPE_UC, artist.net_supply, n)
        if q.total_cents > budget_cents:
            return False
        violations = validate_buy(
            q,
            cash_cents=cash_cents,
            user_shares_after=held_shares + n,
            position_value_after_cents=q.cost_cents,
            equity_after_cents=max(equity_cents, 1),
        )
        return not violations

    lo, hi, best = 0, min(max_shares_cap, MAX_TRADE_SHARES), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if acceptable(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _mark_to_market(artists: list[ArtistState], holdings: dict[int, int], cash_cents: int) -> int:
    equity = cash_cents
    for idx, shares in holdings.items():
        equity += shares * _market_price_cents(artists[idx])
    return equity


def run_bot_a(seed: int, sigma_daily: float) -> tuple[int, int]:
    """Naive nightly round-tripper: each day, buy the 10 largest percentage
    discounts (splitting a fixed daily budget), then sell everything the
    next day at that day's opening (glide-start) price.

    Returns `(final_equity_cents, starting_equity_cents)`.
    """
    artists = build_market(seed, sigma_daily)
    cash = STARTING_CASH_CENTS
    holdings: dict[int, int] = {}

    for day in range(NUM_DAYS):
        _advance_reversion(artists, day)

        # Sell everything bought yesterday, at today's opening price.
        for idx, shares in list(holdings.items()):
            artist = artists[idx]
            q = sell_quote(cents_to_uc(artist.anchor_cents), SLOPE_UC, artist.net_supply, shares)
            if validate_sell(q, position_shares=shares):
                continue
            cash += q.net_cents
            artist.net_supply -= shares
            del holdings[idx]

        gaps = sorted(
            ((idx, _gap_fraction(artists[idx], day)) for idx in range(len(artists))),
            key=lambda pair: pair[1],
            reverse=True,
        )
        top10 = [idx for idx, gap in gaps[:10] if gap > 0]
        if not top10:
            continue

        per_name_budget = STARTING_CASH_CENTS // 10
        equity = _mark_to_market(artists, holdings, cash)
        for idx in top10:
            artist = artists[idx]
            budget = min(per_name_budget, cash)
            n = _size_buy(artist, budget, cash, equity, holdings.get(idx, 0))
            if n < 1:
                continue
            q = buy_quote(cents_to_uc(artist.anchor_cents), SLOPE_UC, artist.net_supply, n)
            cash -= q.total_cents
            artist.net_supply += n
            holdings[idx] = holdings.get(idx, 0) + n

    return _mark_to_market(artists, holdings, cash), STARTING_CASH_CENTS


# Bot B's entry/exit thresholds, as fractions of market price.
_ENTRY_GAP = 0.02
_EXIT_GAP = 0.005
_MAX_OPEN_POSITIONS = 10

# A position that eats its own entire edge in impact captures nothing --
# so unlike Bot A's fixed budget, Bot B sizes each entry so its *own*
# price impact stays a small fraction of the gap it is trying to
# harvest, leaving the rest for the reversion to realize over the hold.
# (A bot that instead just maxed out `MAX_SLIPPAGE_BPS` in one shot would
# routinely move price by as much as the gap itself on this AMM's depth,
# realizing ~zero edge net of fees -- self-defeating, not "patient".)
_MAX_IMPACT_FRACTION_OF_GAP = 0.2


def run_bot_b(seed: int, sigma_daily: float) -> tuple[int, int]:
    """Patient harvester: buys the largest discounts whose gap exceeds
    `_ENTRY_GAP`, up to `_MAX_OPEN_POSITIONS` concurrently held, and
    holds each individual position until *its own* gap falls below
    `_EXIT_GAP` or flips to a premium -- capturing most of the
    steady-state gap rather than one night's partial reversion.

    Returns `(final_equity_cents, starting_equity_cents)`.
    """
    artists = build_market(seed, sigma_daily)
    cash = STARTING_CASH_CENTS
    holdings: dict[int, int] = {}
    per_slot_budget = STARTING_CASH_CENTS // _MAX_OPEN_POSITIONS

    for day in range(NUM_DAYS):
        _advance_reversion(artists, day)
        gaps = {idx: _gap_fraction(artists[idx], day) for idx in range(len(artists))}

        for idx in list(holdings):
            if gaps[idx] < _EXIT_GAP:
                shares = holdings.pop(idx)
                artist = artists[idx]
                q = sell_quote(
                    cents_to_uc(artist.anchor_cents), SLOPE_UC, artist.net_supply, shares
                )
                if validate_sell(q, position_shares=shares):
                    holdings[idx] = shares  # put back; shouldn't normally happen
                    continue
                cash += q.net_cents
                artist.net_supply -= shares

        open_slots = _MAX_OPEN_POSITIONS - len(holdings)
        if open_slots > 0:
            candidates = sorted(
                (
                    idx
                    for idx in range(len(artists))
                    if idx not in holdings and gaps[idx] > _ENTRY_GAP
                ),
                key=lambda idx: gaps[idx],
                reverse=True,
            )[:open_slots]

            equity = _mark_to_market(artists, holdings, cash)
            for idx in candidates:
                artist = artists[idx]
                budget = min(per_slot_budget, cash)
                gap_cents = artist.fair_value_series[day] - _market_price_cents(artist)
                max_impact_cents = max(1, round(_MAX_IMPACT_FRACTION_OF_GAP * gap_cents))
                impact_shares_cap = cents_to_uc(max_impact_cents) // SLOPE_UC
                n = _size_buy(
                    artist,
                    budget,
                    cash,
                    equity,
                    holdings.get(idx, 0),
                    max_shares_cap=impact_shares_cap,
                )
                if n < 1:
                    continue
                q = buy_quote(cents_to_uc(artist.anchor_cents), SLOPE_UC, artist.net_supply, n)
                cash -= q.total_cents
                artist.net_supply += n
                holdings[idx] = n

    return _mark_to_market(artists, holdings, cash), STARTING_CASH_CENTS
