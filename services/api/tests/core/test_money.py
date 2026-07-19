"""I7 (rounding always favors the house) at the level of the primitive
helpers themselves, checked against `fractions.Fraction` exact ground
truth rather than re-implementing rounding by hand."""

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from ax.core.money import (
    MICROCENTS_PER_CENT,
    bps_ceil,
    bps_floor,
    ceil_div,
    cents_to_uc,
    uc_to_cents_ceil,
    uc_to_cents_floor,
    uc_to_cents_nearest,
)

nonneg_int = st.integers(min_value=0, max_value=10**12)
any_uc = st.integers(min_value=-(10**15), max_value=10**15)
pos_divisor = st.integers(min_value=1, max_value=10**9)
small_bps = st.integers(min_value=0, max_value=10_000)


@given(n=any_uc, d=pos_divisor)
def test_ceil_div_matches_fraction_ground_truth(n: int, d: int) -> None:
    exact = Fraction(n, d)
    result = ceil_div(n, d)
    assert result >= exact
    assert result - 1 < exact


@given(n=any_uc, d=pos_divisor)
def test_ceil_div_is_exact_when_evenly_divisible(n: int, d: int) -> None:
    assert ceil_div(n * d, d) == n


def test_cents_to_uc_is_exact() -> None:
    assert cents_to_uc(0) == 0
    assert cents_to_uc(1) == MICROCENTS_PER_CENT
    assert cents_to_uc(-3) == -3 * MICROCENTS_PER_CENT


@given(uc=nonneg_int)
def test_uc_to_cents_ceil_never_undercharges(uc: int) -> None:
    """Ceiling conversion must never be less than the exact value in
    cents -- the house never sells a share for under its microcent cost."""
    result = uc_to_cents_ceil(uc)
    exact = Fraction(uc, MICROCENTS_PER_CENT)
    assert result >= exact
    assert result - 1 < exact


@given(uc=nonneg_int)
def test_uc_to_cents_floor_never_overpays(uc: int) -> None:
    """Floor conversion must never exceed the exact value in cents -- the
    house never pays out more than a share's microcent value."""
    result = uc_to_cents_floor(uc)
    exact = Fraction(uc, MICROCENTS_PER_CENT)
    assert result <= exact
    assert result + 1 > exact


@given(uc=nonneg_int)
def test_ceil_ge_floor(uc: int) -> None:
    assert uc_to_cents_ceil(uc) >= uc_to_cents_floor(uc)


@given(cents=nonneg_int)
def test_uc_roundtrip_is_exact_at_whole_cents(cents: int) -> None:
    uc = cents_to_uc(cents)
    assert uc_to_cents_ceil(uc) == cents
    assert uc_to_cents_floor(uc) == cents
    assert uc_to_cents_nearest(uc) == cents


@given(uc=nonneg_int)
def test_uc_to_cents_nearest_within_half_cent(uc: int) -> None:
    result = uc_to_cents_nearest(uc)
    exact = Fraction(uc, MICROCENTS_PER_CENT)
    assert abs(Fraction(result) - exact) <= Fraction(1, 2)


def test_uc_to_cents_nearest_ties_round_up() -> None:
    half_cent = MICROCENTS_PER_CENT // 2
    assert uc_to_cents_nearest(3 * MICROCENTS_PER_CENT + half_cent) == 4


@given(amount=nonneg_int, bps=small_bps)
def test_bps_ceil_never_undercharges(amount: int, bps: int) -> None:
    result = bps_ceil(amount, bps)
    exact = Fraction(amount * bps, 10_000)
    assert result >= exact
    assert result - 1 < exact


@given(amount=nonneg_int, bps=small_bps)
def test_bps_floor_never_overpays(amount: int, bps: int) -> None:
    result = bps_floor(amount, bps)
    exact = Fraction(amount * bps, 10_000)
    assert result <= exact
    assert result + 1 > exact


@given(
    amount=st.integers(min_value=1, max_value=10**12),
    bps=st.integers(min_value=1, max_value=10_000),
)
def test_bps_ceil_is_at_least_one_for_any_nonzero_amount(amount: int, bps: int) -> None:
    """Fees must never round to zero on a genuinely nonzero trade (what
    makes I2 -- no round-trip profit -- strict)."""
    assert bps_ceil(amount, bps) >= 1
