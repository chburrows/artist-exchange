"""Integer money helpers (CLAUDE.md rule 1: never float, never NUMERIC).

Small and boring on purpose -- every rounding decision in the codebase
that touches a price or balance should go through one of these, so the
"buys round up, sells round down" rule (CLAUDE.md rule 6) lives in one
place instead of being re-derived at every call site.

Suffix convention: `_cents` is integer cents; `_uc` is integer
microcents, `1 cent = MICROCENTS_PER_CENT uc`. Sub-cent intermediate math
(the AMM's per-share integral) happens in microcents and is only divided
down to cents at the boundary.
"""

MICROCENTS_PER_CENT = 1_000_000


def ceil_div(n: int, d: int) -> int:
    """Ceiling integer division. Requires `d > 0`."""
    return -(-n // d)


def round_div(n: int, d: int) -> int:
    """Round-half-up integer division. Requires `d > 0`, `n >= 0`."""
    return (n + d // 2) // d


def cents_to_uc(cents: int) -> int:
    return cents * MICROCENTS_PER_CENT


def uc_to_cents_ceil(uc: int) -> int:
    """Buys round UP (rule 6): the house never sells a share for less
    than its exact microcent cost."""
    return ceil_div(uc, MICROCENTS_PER_CENT)


def uc_to_cents_floor(uc: int) -> int:
    """Sells round DOWN (rule 6): the house never pays out more than a
    share's exact microcent value."""
    return uc // MICROCENTS_PER_CENT


def uc_to_cents_nearest(uc: int) -> int:
    """Round-half-up display conversion. `uc` must be non-negative.

    Never used on a buy or sell amount -- only for spot-price display,
    reversion gap measurement, and anchor persistence, where "favors the
    market" has no meaning and a deterministic, unbiased rounding does.
    """
    return (uc + MICROCENTS_PER_CENT // 2) // MICROCENTS_PER_CENT


def bps_ceil(amount: int, bps: int) -> int:
    """`ceil(amount * bps / 10_000)`. Used for fees, so any nonzero trade
    pays at least 1 cent (what makes I2 strict)."""
    return ceil_div(amount * bps, 10_000)


def bps_floor(amount: int, bps: int) -> int:
    """`floor(amount * bps / 10_000)`."""
    return (amount * bps) // 10_000
