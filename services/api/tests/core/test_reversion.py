"""I10, I11: the reversion kernel `reversion_move_cents`.

`reversion_move_cents` lives in `ax.core.amm` (PHASE2.md keeps the whole
AMM + reversion surface in one module) but is tested on its own here,
independent of the glide/quote machinery landed in the previous commit.
"""

from hypothesis import given
from hypothesis import strategies as st

from ax.core.amm import reversion_move_cents
from ax.core.config import REVERSION_MAX_MOVE_BPS, REVERSION_MIN_MOVE_CENTS

# A safety cap on the I11 convergence loop, independent of the gap being
# tested -- if the kernel ever regresses to non-convergence, the test
# should fail loudly rather than spin.
_MAX_CONVERGENCE_STEPS = 10_000

gap_cents = st.integers(min_value=-(10**9), max_value=10**9)
market_cents = st.integers(min_value=0, max_value=10**9)
fair_and_market = st.integers(min_value=1, max_value=10**6)


@given(market_cents=market_cents)
def test_zero_gap_moves_nothing(market_cents: int) -> None:
    assert reversion_move_cents(0, market_cents) == 0


@given(gap_cents=gap_cents.filter(lambda g: g != 0), market_cents=market_cents)
def test_i10_move_is_sign_symmetric(gap_cents: int, market_cents: int) -> None:
    move = reversion_move_cents(gap_cents, market_cents)
    assert (move > 0) == (gap_cents > 0)
    assert move != 0


@given(gap_cents=gap_cents.filter(lambda g: g != 0), market_cents=market_cents)
def test_i10_move_never_overshoots_the_gap(gap_cents: int, market_cents: int) -> None:
    move = reversion_move_cents(gap_cents, market_cents)
    assert abs(move) <= abs(gap_cents)


@given(gap_cents=gap_cents.filter(lambda g: g != 0), market_cents=market_cents)
def test_i10_move_never_exceeds_the_max_move_cap(gap_cents: int, market_cents: int) -> None:
    move = reversion_move_cents(gap_cents, market_cents)
    cap = max(REVERSION_MIN_MOVE_CENTS, market_cents * REVERSION_MAX_MOVE_BPS // 10_000)
    assert abs(move) <= cap


def _converge(fair_value_cents: int, market_cents: int) -> list[int]:
    """Walk `market_cents` toward `fair_value_cents` via `reversion_move_cents`
    with a fixed fair value, returning the gap observed at each step
    (including the initial gap and the final, necessarily-zero gap)."""
    gaps = [fair_value_cents - market_cents]
    for _ in range(_MAX_CONVERGENCE_STEPS):
        gap = gaps[-1]
        if gap == 0:
            return gaps
        market_cents += reversion_move_cents(gap, market_cents)
        gaps.append(fair_value_cents - market_cents)
    raise AssertionError(f"did not converge within {_MAX_CONVERGENCE_STEPS} steps")


@given(fair_value_cents=fair_and_market, market_cents=fair_and_market)
def test_i11_reversion_converges_monotonically_and_exactly(
    fair_value_cents: int, market_cents: int
) -> None:
    gap0 = abs(fair_value_cents - market_cents)
    gaps = _converge(fair_value_cents, market_cents)
    abs_gaps = [abs(g) for g in gaps]

    assert abs_gaps[-1] == 0
    # `abs_gaps[1:]` is deliberately one shorter than `abs_gaps` (it is the
    # same list minus its first element) -- `strict=True` would reject
    # that expected mismatch instead of just stopping at the shorter one.
    for before, after in zip(abs_gaps, abs_gaps[1:], strict=False):
        assert after < before

    steps_taken = len(gaps) - 1
    assert steps_taken <= gap0
