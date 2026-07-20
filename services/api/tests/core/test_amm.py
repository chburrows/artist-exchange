"""I2-I5, I7, I13: the AMM's closed-form quotes.

The closed forms were checked algebraically before implementation, so
several tests here recompute the same closed form independently (as
`_closed_form_cost_uc` / `_closed_form_proceeds_uc`) to catch an
implementation slip -- e.g. `n*(n+1)//2` where the formula needs
`n*(n-1)//2` -- rather than re-proving the algebra.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ax.core.amm import buy_quote, max_shares_within_slippage, sell_quote, spot_price_uc
from ax.core.config import MAX_SLIPPAGE_BPS
from ax.core.money import cents_to_uc

from .strategies import anchor_cents, net_supply, sellable_supply, shares, slope_uc


def _closed_form_cost_uc(anchor_uc: int, slope: int, supply: int, n: int) -> int:
    return n * anchor_uc + slope * (n * supply + n * (n - 1) // 2)


def _closed_form_proceeds_uc(anchor_uc: int, slope: int, supply: int, n: int) -> int:
    return n * anchor_uc + slope * (n * (supply - n) + n * (n - 1) // 2)


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, net_supply=net_supply, shares=shares)
def test_i2_buy_then_sell_strictly_loses(
    anchor_cents: int, slope_uc: int, net_supply: int, shares: int
) -> None:
    anchor_uc = cents_to_uc(anchor_cents)
    buy = buy_quote(anchor_uc, slope_uc, net_supply, shares)
    sell = sell_quote(anchor_uc, slope_uc, net_supply + shares, shares)
    assert buy.total_cents - sell.net_cents >= 2


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, net_supply=net_supply, shares=shares)
def test_i3_buy_strictly_raises_spot(
    anchor_cents: int, slope_uc: int, net_supply: int, shares: int
) -> None:
    buy = buy_quote(cents_to_uc(anchor_cents), slope_uc, net_supply, shares)
    assert buy.spot_after_uc - buy.spot_before_uc == slope_uc * shares
    assert buy.spot_after_uc > buy.spot_before_uc


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, shares_and_supply=sellable_supply())
def test_i3_sell_strictly_lowers_spot(
    anchor_cents: int, slope_uc: int, shares_and_supply: tuple[int, int]
) -> None:
    n, s = shares_and_supply
    sell = sell_quote(cents_to_uc(anchor_cents), slope_uc, s, n)
    assert sell.spot_before_uc - sell.spot_after_uc == slope_uc * n
    assert sell.spot_after_uc < sell.spot_before_uc


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, net_supply=net_supply, shares=shares)
def test_i4_closed_form_matches_marginal_share_sum_exactly(
    anchor_cents: int, slope_uc: int, net_supply: int, shares: int
) -> None:
    """Pre-rounding: cost(n) in uc equals the exact sum of each unit
    share's marginal price (the k-th share costs exactly the spot price
    at net_supply=k, by construction of the AMM) -- integer sums, so this
    must be exact, not merely close."""
    anchor_uc = cents_to_uc(anchor_cents)
    ground_truth = sum(spot_price_uc(anchor_uc, slope_uc, net_supply + k) for k in range(shares))
    assert _closed_form_cost_uc(anchor_uc, slope_uc, net_supply, shares) == ground_truth


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, net_supply=net_supply, shares=shares)
def test_i4_sequential_unit_buys_bound_the_single_buy(
    anchor_cents: int, slope_uc: int, net_supply: int, shares: int
) -> None:
    """Post-rounding: n sequential 1-share buys cost at least as much as
    one n-share buy (each unit purchase rounds up independently) and not
    more than 2n cents extra."""
    anchor_uc = cents_to_uc(anchor_cents)
    single = buy_quote(anchor_uc, slope_uc, net_supply, shares).cost_cents

    sequential = 0
    s = net_supply
    for _ in range(shares):
        sequential += buy_quote(anchor_uc, slope_uc, s, 1).cost_cents
        s += 1

    assert sequential >= single
    assert sequential - single <= 2 * shares


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, shares_and_supply=sellable_supply())
def test_i5_sell_proceeds_and_buy_cost_are_symmetric_pre_rounding(
    anchor_cents: int, slope_uc: int, shares_and_supply: tuple[int, int]
) -> None:
    n, s = shares_and_supply
    anchor_uc = cents_to_uc(anchor_cents)
    assert _closed_form_proceeds_uc(anchor_uc, slope_uc, s, n) == _closed_form_cost_uc(
        anchor_uc, slope_uc, s - n, n
    )


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, shares_and_supply=sellable_supply())
def test_i5_sell_proceeds_and_buy_cost_within_a_cent_post_rounding(
    anchor_cents: int, slope_uc: int, shares_and_supply: tuple[int, int]
) -> None:
    """Since the pre-rounding values are identical (I5 above), the
    rounded cent amounts can only differ by whether that shared value
    landed exactly on a cent boundary: ceil - floor is 0 or 1."""
    n, s = shares_and_supply
    anchor_uc = cents_to_uc(anchor_cents)
    buy = buy_quote(anchor_uc, slope_uc, s - n, n)
    sell = sell_quote(anchor_uc, slope_uc, s, n)
    assert buy.cost_cents - sell.proceeds_cents in (0, 1)


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, net_supply=net_supply, shares=shares)
def test_i7_buy_rounds_in_the_houses_favor(
    anchor_cents: int, slope_uc: int, net_supply: int, shares: int
) -> None:
    anchor_uc = cents_to_uc(anchor_cents)
    exact_uc = _closed_form_cost_uc(anchor_uc, slope_uc, net_supply, shares)
    buy = buy_quote(anchor_uc, slope_uc, net_supply, shares)
    assert buy.cost_cents * 1_000_000 >= exact_uc
    assert buy.fee_cents >= 1


@given(anchor_cents=anchor_cents, slope_uc=slope_uc, shares_and_supply=sellable_supply())
def test_i7_sell_rounds_in_the_houses_favor(
    anchor_cents: int, slope_uc: int, shares_and_supply: tuple[int, int]
) -> None:
    n, s = shares_and_supply
    anchor_uc = cents_to_uc(anchor_cents)
    exact_uc = _closed_form_proceeds_uc(anchor_uc, slope_uc, s, n)
    sell = sell_quote(anchor_uc, slope_uc, s, n)
    assert sell.proceeds_cents * 1_000_000 <= exact_uc
    assert sell.fee_cents >= 1


@given(
    spot_uc=st.integers(min_value=1, max_value=10**9),
    slope_uc=slope_uc,
)
def test_i13_max_shares_within_slippage_boundary(spot_uc: int, slope_uc: int) -> None:
    n = max_shares_within_slippage(spot_uc, slope_uc)
    assert slope_uc * n * 10_000 <= spot_uc * MAX_SLIPPAGE_BPS
    assert slope_uc * (n + 1) * 10_000 > spot_uc * MAX_SLIPPAGE_BPS


def test_quotes_reject_invalid_inputs() -> None:
    anchor_uc = cents_to_uc(100)
    with pytest.raises(ValueError):
        buy_quote(anchor_uc, 1, 0, 0)
    with pytest.raises(ValueError):
        buy_quote(anchor_uc, 1, -1, 1)
    with pytest.raises(ValueError):
        sell_quote(anchor_uc, 1, 0, 0)
    with pytest.raises(ValueError):
        sell_quote(anchor_uc, 1, -1, 1)
    with pytest.raises(ValueError):
        sell_quote(anchor_uc, 1, 5, 6)
