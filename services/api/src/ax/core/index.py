"""The cross-sectional index score and its fair-value mapping.

Every input is a robust (median/MAD) z-score of a *growth rate*, never a
level (CLAUDE.md rule 5). Last.fm `playcount` is monotonic -- it only
ever rises -- so an index built on levels could never produce a falling
price and every position would win. Because every artist's growth rate
is measured relative to the *cross-sectional median* growth rate that
same day, a universe-wide inflation of raw counts shifts every artist's
growth rate by (approximately) the same constant and leaves every
z-score, and therefore every score, unchanged. That invariance (I8) is
what makes it possible for prices to fall on genuinely rising, monotonic
input data -- the whole point of the product.

Floats are legitimate here (`index_score` is a statistic, not money).
Money re-enters only at `fair_value_cents`, an int.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ax.core.config import (
    EWMA_ALPHA,
    FAIR_VALUE_BASE_CENTS,
    FAIR_VALUE_EXPONENT,
    FAIR_VALUE_MIN_CENTS,
    GROWTH_BASE_WINDOW_DAYS,
    GROWTH_LOOKBACK_DAYS,
    GROWTH_WEIGHT,
    INDEX_MAX,
    INDEX_MIN,
    LEVEL_WEIGHT,
    MIN_CROSS_SECTION_SIZE,
    ROBUST_Z_MIN_MAD,
    SIGNAL_WEIGHTS,
    Z_CLAMP,
)

_ROBUST_Z_SCALE = 0.6745  # maps MAD to a standard-normal-equivalent scale


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SignalInput:
    """One artist, one signal, one day."""

    current: int  # V_t
    base: int  # V_base, the snapshot GROWTH_LOOKBACK_DAYS (nominally) earlier
    gap_days: int  # actual calendar gap to `base`, in [5, 9] (C6)
    prev_ewma: float | None  # yesterday's Z_s(a); None on first observation (C7)


@dataclass(frozen=True)
class ArtistDayInput:
    signals: Mapping[str, SignalInput]  # keyed by "source.metric_key"
    listeners: int  # level term input


@dataclass(frozen=True)
class ArtistDayResult:
    index_score: float
    fair_value_cents: int
    components: dict[str, object]  # versioned; goes verbatim into index_snapshots.components


def pick_base_snapshot(
    dates_to_values: Mapping[date, int], target_day: date
) -> tuple[int, int] | None:
    """The base snapshot for `target_day`'s growth rate (C6): prefers the
    day closest to `GROWTH_LOOKBACK_DAYS` back within
    `+-GROWTH_BASE_WINDOW_DAYS`, ties broken toward the older (larger-gap)
    day. Returns `(base_value, gap_days)`, or `None` if no day in the
    window has data -- the caller's cue that the artist is `warming_up`.

    Shared by `cli.py`'s `ax backtest` and `jobs/recompute.py`, both of
    which need the identical base-window rule production applies against
    `metric_snapshots`. Pure (stdlib `date`/`timedelta` only), so it
    belongs here rather than being duplicated in each caller.
    """
    window = range(
        GROWTH_LOOKBACK_DAYS - GROWTH_BASE_WINDOW_DAYS,
        GROWTH_LOOKBACK_DAYS + GROWTH_BASE_WINDOW_DAYS + 1,
    )
    candidate_offsets = [
        offset for offset in window if (target_day - timedelta(days=offset)) in dates_to_values
    ]
    if not candidate_offsets:
        return None

    best_offset = min(
        candidate_offsets, key=lambda offset: (abs(offset - GROWTH_LOOKBACK_DAYS), -offset)
    )
    best_day = target_day - timedelta(days=best_offset)
    return dates_to_values[best_day], best_offset


def robust_z(values: Sequence[float], *, clamp: float = Z_CLAMP) -> list[float]:
    """Median/MAD z-scores, clamped to +-`clamp` (C4). Defaults to
    +-Z_CLAMP, the score-formula's own bound; callers outside the score
    path (Phase 3's oracle-manipulation divergence check, which needs to
    tell "beyond 3 MAD" apart from "clamped at the boundary") pass
    `clamp=math.inf` for the raw, unclamped z-score instead.

    Median/MAD rather than mean/stdev so one viral artist can't compress
    (or blow up) every other artist's z-score. The MAD floor
    (`ROBUST_Z_MIN_MAD`) exists because a cross-section where more than
    half the values are identical -- plausible for small, static artists
    -- makes MAD exactly 0, which would otherwise divide by zero.

    Invariant (I8): adding the same constant to every value in `values`
    leaves every returned z-score unchanged, because both the numerator
    (`value - median`) and MAD are shift-invariant together.
    """
    if not values:
        return []

    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    median = sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2

    abs_devs = sorted(abs(v - median) for v in values)
    mad = abs_devs[mid] if n % 2 else (abs_devs[mid - 1] + abs_devs[mid]) / 2
    denom = max(mad, ROBUST_Z_MIN_MAD)

    return [_clamp(_ROBUST_Z_SCALE * (v - median) / denom, -clamp, clamp) for v in values]


def fair_value_cents(score: float) -> int:
    """Fair value in cents at a given index score (C13).

    Round-half-up (`int(x + 0.5)`), not Python's banker's-rounding
    `round()` -- there is no reason for this to be surprising here --
    floored at `FAIR_VALUE_MIN_CENTS` so the AMM never quotes a zero
    price for a score-1 artist.
    """
    raw = FAIR_VALUE_BASE_CENTS * (score / 50) ** FAIR_VALUE_EXPONENT
    return max(FAIR_VALUE_MIN_CENTS, int(raw + 0.5))


def _growth_rate(signal: SignalInput) -> float:
    """`g_s(a) = (ln(V_t + 1) - ln(V_base + 1)) * GROWTH_LOOKBACK_DAYS / gap_days` (C6):
    linearly rescaled to a nominal `GROWTH_LOOKBACK_DAYS`-day rate when the
    actual base snapshot is a different number of days back."""
    raw = math.log(signal.current + 1) - math.log(signal.base + 1)
    return raw * GROWTH_LOOKBACK_DAYS / signal.gap_days


def _ewma(z: float, prev: float | None) -> float:
    """C7: the first observation initializes the EWMA state directly,
    rather than decaying in from an implicit 0 -- which would otherwise
    bias every newly-listed artist toward the median for weeks."""
    if prev is None:
        return z
    return EWMA_ALPHA * z + (1 - EWMA_ALPHA) * prev


def compute_index[K](day: Mapping[K, ArtistDayInput]) -> dict[K, ArtistDayResult]:
    """One cross-section's worth of index scores.

    Eligibility: an artist enters the cross-section only if it has
    *every* configured signal for the day (missing listeners is not
    possible -- `ArtistDayInput.listeners` is required -- so this reduces
    to having every key in `SIGNAL_WEIGHTS`). Ineligible artists are
    simply absent from the result; the caller (Phase 3's job) decides
    what "hold previous score" means for them.

    If fewer than `MIN_CROSS_SECTION_SIZE` artists are eligible, the
    cross-sectional statistics (median/MAD) are too noisy to trust, so
    the day is skipped entirely: returns `{}`.
    """
    required_signals = set(SIGNAL_WEIGHTS)
    eligible = [key for key, artist in day.items() if required_signals <= set(artist.signals)]

    if len(eligible) < MIN_CROSS_SECTION_SIZE:
        return {}

    growth_rates: dict[str, dict[K, float]] = {}
    raw_z: dict[str, dict[K, float]] = {}
    ewma_z: dict[str, dict[K, float]] = {}

    for signal_key in SIGNAL_WEIGHTS:
        rates = {key: _growth_rate(day[key].signals[signal_key]) for key in eligible}
        z_list = robust_z([rates[key] for key in eligible])
        z_by_key = dict(zip(eligible, z_list, strict=True))
        ewma_by_key = {
            key: _ewma(z_by_key[key], day[key].signals[signal_key].prev_ewma) for key in eligible
        }

        growth_rates[signal_key] = rates
        raw_z[signal_key] = z_by_key
        ewma_z[signal_key] = ewma_by_key

    growth_term = {
        key: sum(SIGNAL_WEIGHTS[s] * ewma_z[s][key] for s in SIGNAL_WEIGHTS) for key in eligible
    }

    level_z_list = robust_z([math.log(day[key].listeners + 1) for key in eligible])
    level_term = dict(zip(eligible, level_z_list, strict=True))

    results: dict[K, ArtistDayResult] = {}
    for key in eligible:
        score_pre_clamp = 50 + GROWTH_WEIGHT * growth_term[key] + LEVEL_WEIGHT * level_term[key]
        score = _clamp(score_pre_clamp, INDEX_MIN, INDEX_MAX)

        components: dict[str, object] = {
            "v": 1,
            "signals": {
                signal_key: {
                    "g": growth_rates[signal_key][key],
                    "z": raw_z[signal_key][key],
                    "ewma": ewma_z[signal_key][key],
                    "gap_days": day[key].signals[signal_key].gap_days,
                }
                for signal_key in SIGNAL_WEIGHTS
            },
            "level_z": level_term[key],
            "growth_term": growth_term[key],
            "level_term": level_term[key],
            "score_pre_clamp": score_pre_clamp,
        }

        results[key] = ArtistDayResult(
            index_score=score,
            fair_value_cents=fair_value_cents(score),
            components=components,
        )

    return results
