"""Shared Hypothesis strategies for the pure-core test suite.

Bound to the product's real ranges rather than arbitrary integers --
these tests pin the product's actual operating envelope, not an
abstract mathematical property that happens to hold everywhere.
"""

from datetime import UTC, datetime

from hypothesis import strategies as st

from ax.core.config import MAX_TRADE_SHARES

anchor_cents = st.integers(min_value=1, max_value=500_000)
slope_uc = st.integers(min_value=1, max_value=5_000_000)
net_supply = st.integers(min_value=0, max_value=100_000)
shares = st.integers(min_value=1, max_value=MAX_TRADE_SHARES)

aware_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2035, 1, 1),
    timezones=st.just(UTC),
)


@st.composite
def sellable_supply(draw: st.DrawFn) -> tuple[int, int]:
    """`(shares, net_supply)` with `net_supply >= shares`, so a sell is
    always valid. Drawing `net_supply` unconditionally (then `assume`-ing
    it's large enough) would reject almost every case, since `net_supply`
    starts at 0 and `shares` can be up to `MAX_TRADE_SHARES`."""
    n = draw(shares)
    extra = draw(st.integers(min_value=0, max_value=100_000))
    return n, n + extra
