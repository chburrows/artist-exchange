"""I1, I6: ledger conservation and supply integrity, plus the position
math (weighted-average cost, scout shares) and the guardrail validators
that the I14 simulation and Phase 4's trade route both rely on.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ax.core.amm import buy_quote, sell_quote
from ax.core.config import MAX_TRADE_SHARES
from ax.core.ledger import (
    Kind,
    PositionState,
    apply_buy,
    apply_sell,
    buy_entries,
    grant_entries,
    scout_qualified,
    sell_entries,
    validate_buy,
    validate_sell,
)
from ax.core.money import MICROCENTS_PER_CENT, cents_to_uc

NUM_USERS = 3
STARTING_CASH_CENTS = 50_000
ANCHOR_CENTS = 1_000
SLOPE_UC = 5_000
ARTIST_ID = 1

_action = st.tuples(
    st.integers(min_value=0, max_value=NUM_USERS - 1),
    st.booleans(),  # True -> buy, False -> sell
    st.integers(min_value=1, max_value=50),
)


@given(actions=st.lists(_action, min_size=0, max_size=40))
def test_i1_i6_ledger_conservation_and_supply_integrity(
    actions: list[tuple[int, bool, int]],
) -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)

    cash = [0] * NUM_USERS
    positions = [PositionState() for _ in range(NUM_USERS)]
    net_supply = 0

    total_grants = 0
    total_fees = 0
    total_buy_cost = 0
    total_sell_proceeds = 0
    total_share_delta = 0

    for user_idx in range(NUM_USERS):
        for entry in grant_entries(STARTING_CASH_CENTS):
            cash[user_idx] += entry.cash_delta_cents
            total_grants += entry.cash_delta_cents

    for user_idx, is_buy, shares in actions:
        if is_buy:
            q = buy_quote(anchor_uc, SLOPE_UC, net_supply, shares)
            violations = validate_buy(
                q,
                cash_cents=cash[user_idx],
                user_shares_after=positions[user_idx].shares + q.shares,
                position_value_after_cents=0,
                equity_after_cents=10**12,
            )
            if violations:
                continue

            for entry in buy_entries(ARTIST_ID, q):
                cash[user_idx] += entry.cash_delta_cents
                total_share_delta += entry.share_delta
                if entry.kind is Kind.FEE:
                    total_fees += -entry.cash_delta_cents
            total_buy_cost += q.cost_cents
            positions[user_idx] = apply_buy(positions[user_idx], q, scout=False)
            net_supply += q.shares
        else:
            shares = min(shares, positions[user_idx].shares, net_supply)
            if shares < 1:
                continue
            q = sell_quote(anchor_uc, SLOPE_UC, net_supply, shares)
            violations = validate_sell(q, position_shares=positions[user_idx].shares)
            if violations:
                continue

            for entry in sell_entries(ARTIST_ID, q):
                cash[user_idx] += entry.cash_delta_cents
                total_share_delta += entry.share_delta
                if entry.kind is Kind.FEE:
                    total_fees += -entry.cash_delta_cents
            total_sell_proceeds += q.proceeds_cents
            positions[user_idx] = apply_sell(positions[user_idx], q)
            net_supply -= q.shares

    # I6: supply integrity.
    assert net_supply == total_share_delta
    assert net_supply == sum(p.shares for p in positions)
    assert net_supply >= 0
    assert all(p.shares >= 0 for p in positions)

    # I1: cash conservation.
    amm_net = total_buy_cost - total_sell_proceeds
    assert sum(cash) == total_grants - total_fees - amm_net

    # The curve never pays out more than it took in once its own
    # inventory is flat again -- rounding direction made real.
    if net_supply == 0:
        assert amm_net >= 0


def test_oversell_is_rejected_by_amm_before_ledger_sees_it() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    with pytest.raises(ValueError):
        sell_quote(anchor_uc, SLOPE_UC, net_supply=5, shares=6)


# --- Position math -------------------------------------------------------


def test_apply_buy_computes_weighted_average_cost_from_empty() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)

    pos = apply_buy(PositionState(), q, scout=False)

    assert pos.shares == 10
    assert pos.avg_cost_uc == q.total_cents * MICROCENTS_PER_CENT // 10
    assert pos.scout_shares == 0
    assert pos.realized_pnl_cents == 0


def test_apply_buy_blends_average_cost_across_two_buys() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q1 = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)
    pos1 = apply_buy(PositionState(), q1, scout=False)

    q2 = buy_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=5)
    pos2 = apply_buy(pos1, q2, scout=True)

    assert pos2.shares == 15
    expected_avg = (10 * pos1.avg_cost_uc + q2.total_cents * MICROCENTS_PER_CENT) // 15
    assert pos2.avg_cost_uc == expected_avg
    # Only the second buy was scout-qualified.
    assert pos2.scout_shares == 5


def test_apply_sell_reduces_scout_shares_proportionally() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    pos = PositionState(shares=10, avg_cost_uc=cents_to_uc(100), scout_shares=4)

    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=5)
    result = apply_sell(pos, q)

    assert result.shares == 5
    assert result.scout_shares == 4 * 5 // 10  # floor, proportional (C12)


def test_apply_sell_to_zero_resets_avg_cost_and_scout_shares() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    pos = PositionState(shares=10, avg_cost_uc=cents_to_uc(100), scout_shares=3)

    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=10)
    result = apply_sell(pos, q)

    assert result.shares == 0
    assert result.avg_cost_uc == 0
    assert result.scout_shares == 0


def test_apply_sell_realizes_gain_relative_to_avg_cost() -> None:
    # A very cheap avg cost basis against real sale proceeds should
    # realize a strictly positive gain.
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    pos = PositionState(shares=10, avg_cost_uc=cents_to_uc(1), scout_shares=0)

    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=10)
    result = apply_sell(pos, q)

    assert result.realized_pnl_cents > 0


# --- scout_qualified (C12: AND) ------------------------------------------


def test_scout_qualified_requires_both_conditions() -> None:
    assert scout_qualified(40.0, 500) is True
    assert scout_qualified(50.0, 500) is False  # score too high
    assert scout_qualified(40.0, 1_500) is False  # price too high
    assert scout_qualified(None, 500) is False  # no score yet


# --- validate_buy / validate_sell ----------------------------------------


def _safe_buy_kwargs() -> dict[str, int]:
    return {
        "cash_cents": 10**12,
        "user_shares_after": 0,
        "position_value_after_cents": 0,
        "equity_after_cents": 10**12,
    }


def test_validate_buy_flags_overdraft() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)

    kwargs = _safe_buy_kwargs()
    kwargs["cash_cents"] = q.total_cents - 1
    assert "overdraft" in validate_buy(q, **kwargs)


def test_validate_buy_flags_max_trade_shares() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=MAX_TRADE_SHARES + 1)
    assert "max_trade_shares" in validate_buy(q, **_safe_buy_kwargs())


def test_validate_buy_flags_slippage() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    # A steep slope makes a modest share count move spot well past
    # MAX_SLIPPAGE_BPS.
    steep_slope_uc = anchor_uc // 10
    q = buy_quote(anchor_uc, steep_slope_uc, net_supply=0, shares=50)
    assert "slippage" in validate_buy(q, **_safe_buy_kwargs())


def test_validate_buy_flags_supply_share_cap() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)

    kwargs = _safe_buy_kwargs()
    kwargs["user_shares_after"] = 10**9
    assert "supply_share_cap" in validate_buy(q, **kwargs)


def test_validate_buy_flags_exposure_cap() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)

    kwargs = _safe_buy_kwargs()
    kwargs["position_value_after_cents"] = 10**9
    kwargs["equity_after_cents"] = 100
    assert "exposure_cap" in validate_buy(q, **kwargs)


def test_validate_buy_happy_path_has_no_violations() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = buy_quote(anchor_uc, SLOPE_UC, net_supply=0, shares=10)
    assert validate_buy(q, **_safe_buy_kwargs()) == []


def test_validate_sell_flags_oversell() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=10)
    assert "oversell" in validate_sell(q, position_shares=9)


def test_validate_sell_flags_max_trade_shares() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    n = MAX_TRADE_SHARES + 1
    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=n, shares=n)
    assert "max_trade_shares" in validate_sell(q, position_shares=n)


def test_validate_sell_flags_slippage() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    steep_slope_uc = anchor_uc // 10
    q = sell_quote(anchor_uc, steep_slope_uc, net_supply=50, shares=50)
    assert "slippage" in validate_sell(q, position_shares=50)


def test_validate_sell_happy_path_has_no_violations() -> None:
    anchor_uc = cents_to_uc(ANCHOR_CENTS)
    q = sell_quote(anchor_uc, SLOPE_UC, net_supply=10, shares=10)
    assert validate_sell(q, position_shares=10) == []
