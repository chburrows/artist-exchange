"""I8, I9: the cross-sectional index score.

I8 is the most important test in the repo (CLAUDE.md): Last.fm
`playcount` only ever rises, so if the index were built on levels, no
price would ever fall. Every input is instead a robust z-score of a
*growth rate*, and (a)/(b) below prove the structural reason that
holds -- median/MAD z-scores are exactly shift-invariant -- at the level
of `robust_z` itself, since that is the one function the property is
actually about. (c) is the behavioral, end-to-end version on realistic
integer counts: the one that matters to the product.
"""

import math
import statistics
import sys
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ax.core.config import (
    FAIR_VALUE_BASE_CENTS,
    GROWTH_LOOKBACK_DAYS,
    GROWTH_WEIGHT,
    INDEX_MAX,
    INDEX_MIN,
    MIN_CROSS_SECTION_SIZE,
    ROBUST_Z_MIN_MAD,
    SIGNAL_WEIGHTS,
)
from ax.core.index import (
    ArtistDayInput,
    ArtistDayResult,
    SignalInput,
    compute_index,
    fair_value_cents,
    pick_base_snapshot,
    robust_z,
)

from .fixture_data import BACKTEST_FIXTURE_PATH, load_fixture, replay

# --- I8(a): dyadic (power-of-two) values, exact under IEEE754 -----------

_dyadic = st.integers(min_value=-16_000, max_value=16_000).map(lambda i: i / 1024)


@given(values=st.lists(_dyadic, min_size=2, max_size=40), shift=_dyadic)
def test_i8a_robust_z_is_bit_identical_under_dyadic_shift(
    values: list[float], shift: float
) -> None:
    shifted = [v + shift for v in values]
    assert robust_z(shifted) == robust_z(values)


# --- I8(b): arbitrary floats, near-identical through score/fair-value ----

_small_float = st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False)
_MAX_ABS_INPUT = 5  # bound of the _small_float strategy above

# I8(b)'s invariant is exact in real-number arithmetic (see I8(a) above, which
# proves it bit-for-bit on dyadic inputs). For arbitrary floats, `v + shift`
# loses precision when |v| << |shift|, and robust_z's `v - median` cancellation
# recovers that error at full magnitude, then amplifies it by 1/ROBUST_Z_MIN_MAD
# and by GROWTH_WEIGHT on the way to a score. Worst case for this strategy's
# bounds is ~1e-8; this keeps two orders of magnitude of margin above that.
_SCORE_TOLERANCE = 100 * sys.float_info.epsilon * _MAX_ABS_INPUT * GROWTH_WEIGHT / ROBUST_Z_MIN_MAD


def _score_from_z(z: float) -> float:
    return max(INDEX_MIN, min(INDEX_MAX, 50 + GROWTH_WEIGHT * z))


@given(
    values=st.lists(_small_float, min_size=10, max_size=40),
    shift=_small_float,
)
def test_i8b_arbitrary_shift_scores_and_fair_values_nearly_identical(
    values: list[float], shift: float
) -> None:
    shifted = [v + shift for v in values]

    z_base = robust_z(values)
    z_shifted = robust_z(shifted)

    for zb, zs in zip(z_base, z_shifted, strict=True):
        score_base = _score_from_z(zb)
        score_shifted = _score_from_z(zs)
        assert abs(score_base - score_shifted) < _SCORE_TOLERANCE

        fair_base = fair_value_cents(score_base)
        fair_shifted = fair_value_cents(score_shifted)
        assert abs(fair_base - fair_shifted) <= 1


# --- I8(c): behavioral -- monotonic inputs can still produce a falling --
# --- price, on realistic integer counts through the full pipeline. -----


def _signal_input(
    base: int, daily_rate: float, gap_days: int = GROWTH_LOOKBACK_DAYS
) -> SignalInput:
    """A signal whose count rose every day at `daily_rate` for `gap_days`
    days, starting from `base` -- i.e. a genuinely monotonically
    increasing raw count, exactly like real Last.fm data."""
    current = round(base * (1 + daily_rate) ** gap_days)
    return SignalInput(current=current, base=base, gap_days=gap_days, prev_ewma=None)


def test_i8c_slower_than_median_grower_scores_below_50_and_falls_below_base_fair_value() -> None:
    base_count = 100_000
    # 11 normal artists growing at ~5%/gap_days-window, one laggard growing
    # much slower -- but still growing, every single day: the pathology
    # I8 exists to defeat.
    normal_rates = [0.050, 0.052, 0.048, 0.055, 0.045, 0.051, 0.049, 0.053, 0.047, 0.054, 0.046]
    laggard_rate = 0.005

    day: dict[str, ArtistDayInput] = {}
    for i, rate in enumerate(normal_rates):
        signal = _signal_input(base_count, rate)
        day[f"normal-{i}"] = ArtistDayInput(
            signals={"lastfm.listeners": signal, "lastfm.playcount": signal},
            listeners=5_000,  # identical level across the universe: isolates the growth term
        )
    laggard_signal = _signal_input(base_count, laggard_rate)
    day["laggard"] = ArtistDayInput(
        signals={"lastfm.listeners": laggard_signal, "lastfm.playcount": laggard_signal},
        listeners=5_000,
    )

    assert len(day) >= MIN_CROSS_SECTION_SIZE
    results = compute_index(day)

    laggard = results["laggard"]
    assert laggard.index_score < 50
    assert laggard.fair_value_cents < FAIR_VALUE_BASE_CENTS

    # The product claim, made explicit: every single one of the laggard's
    # raw counts still went up (base_count -> current), yet its fair
    # value is below the index-50 base price.
    assert laggard_signal.current > laggard_signal.base


# --- I9: scores always in range; median ~50 on a realistic universe -----


@given(
    rates=st.lists(
        st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
        min_size=MIN_CROSS_SECTION_SIZE,
        max_size=30,
    ),
    listener_levels=st.lists(
        st.integers(min_value=1, max_value=10**8), min_size=MIN_CROSS_SECTION_SIZE, max_size=30
    ),
)
def test_i9_scores_always_within_bounds(rates: list[float], listener_levels: list[int]) -> None:
    n = min(len(rates), len(listener_levels))
    rates, listener_levels = rates[:n], listener_levels[:n]

    day: dict[int, ArtistDayInput] = {}
    for i in range(n):
        base = 10_000
        current = max(0, round(base * math.exp(rates[i])))
        signal = SignalInput(
            current=current, base=base, gap_days=GROWTH_LOOKBACK_DAYS, prev_ewma=None
        )
        day[i] = ArtistDayInput(
            signals={key: signal for key in SIGNAL_WEIGHTS},
            listeners=listener_levels[i],
        )

    results = compute_index(day)
    for result in results.values():
        assert INDEX_MIN <= result.index_score <= INDEX_MAX
        assert result.fair_value_cents >= 1


def test_i9_below_min_cross_section_size_returns_no_scores() -> None:
    day: dict[int, ArtistDayInput] = {}
    for i in range(MIN_CROSS_SECTION_SIZE - 1):
        signal = SignalInput(current=1_100, base=1_000, gap_days=7, prev_ewma=None)
        day[i] = ArtistDayInput(signals={key: signal for key in SIGNAL_WEIGHTS}, listeners=1_000)

    assert compute_index(day) == {}


@pytest.fixture(scope="module")
def backtest_replay() -> dict[date, dict[str, ArtistDayResult]]:
    series = load_fixture(BACKTEST_FIXTURE_PATH)
    return replay(series)


def test_i9_median_near_50_on_backtest_fixture(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    """The realistic-universe check: replay the committed backtest fixture
    day by day, carrying EWMA state, and look at the final day's
    cross-section -- median score near 50 is structural now thanks to
    the level term's robust z (C5), though the growth term's blended
    two-signal z and its EWMA carry can still nudge it, hence the
    documented +-1 rather than an exact equality."""
    final_results = backtest_replay[max(backtest_replay)]

    assert len(final_results) >= MIN_CROSS_SECTION_SIZE
    median_score = statistics.median(r.index_score for r in final_results.values())
    assert abs(median_score - 50) <= 1


# --- Archetype assertions: the fixture's known answers, and the ---------
# --- Phase 2 "Done when" bullet about ax backtest's output. -------------


def test_archetype_breakout_ends_well_above_50(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    final_results = backtest_replay[max(backtest_replay)]
    assert final_results["breakout"].index_score > 60


def test_archetype_laggard_ends_below_50_with_falling_fair_value(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    dates_with_laggard = sorted(d for d, r in backtest_replay.items() if "laggard" in r)
    early_result = backtest_replay[dates_with_laggard[0]]["laggard"]
    final_result = backtest_replay[dates_with_laggard[-1]]["laggard"]

    assert final_result.index_score < 45
    # The product claim, end to end: the laggard's raw counts rose every
    # single day (it is a monotonically increasing series, like real
    # Last.fm data), yet its fair value is lower now than early on.
    assert final_result.fair_value_cents < early_result.fair_value_cents


def test_archetype_steady_artists_stay_between_the_extremes(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    """A large `GROWTH_WEIGHT` amplifies even small day-to-day noise, so
    "hover near 50" means "not an extreme like breakout/laggard", not a
    tight numeric band -- see build_backtest_fixture.py's docstring."""
    final_results = backtest_replay[max(backtest_replay)]
    laggard_score = final_results["laggard"].index_score
    breakout_score = final_results["breakout"].index_score

    steady_scores = [
        result.index_score for slug, result in final_results.items() if slug.startswith("steady-")
    ]
    assert len(steady_scores) >= 8
    assert all(laggard_score < score < breakout_score for score in steady_scores)


def test_archetype_viral_spike_decays_rather_than_steps(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    dates_with_spike = sorted(d for d, r in backtest_replay.items() if "viral-spike" in r)
    scores_by_date = {d: backtest_replay[d]["viral-spike"].index_score for d in dates_with_spike}

    baseline = scores_by_date[dates_with_spike[0]]
    peak_date = max(scores_by_date, key=lambda d: scores_by_date[d])
    peak_score = scores_by_date[peak_date]

    # It does spike...
    assert peak_score > baseline + 30
    # ...and about ten days after the peak, it has decayed back down
    # rather than staying elevated -- a damped response, not a step.
    ten_days_later = [d for d in dates_with_spike if d >= peak_date + timedelta(days=10)]
    assert ten_days_later
    assert scores_by_date[ten_days_later[0]] < peak_score - 30


def test_archetype_gappy_resumes_after_its_missing_days(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    dates_with_gappy = sorted(d for d, r in backtest_replay.items() if "gappy" in r)
    all_dates = sorted(backtest_replay)

    # It really was missing for a stretch (the point of this archetype).
    assert len(dates_with_gappy) < len(all_dates)
    # But it resumes producing valid scores once data resumes, rather
    # than being permanently excluded by a bad base-window fallback.
    result = backtest_replay[dates_with_gappy[-1]]["gappy"]
    assert INDEX_MIN <= result.index_score <= INDEX_MAX


def test_archetype_tiny_produces_sane_score_and_fair_value(
    backtest_replay: dict[date, dict[str, ArtistDayResult]],
) -> None:
    final_results = backtest_replay[max(backtest_replay)]
    result = final_results["tiny"]
    assert INDEX_MIN <= result.index_score <= INDEX_MAX
    assert result.fair_value_cents >= 1


# --- pick_base_snapshot (C6): shared by ax backtest and jobs/recompute --


def test_pick_base_snapshot_prefers_exactly_seven_days_back() -> None:
    target = date(2026, 1, 15)
    dates_to_values = {
        target - timedelta(days=5): 100,
        target - timedelta(days=7): 200,
        target - timedelta(days=9): 300,
    }
    assert pick_base_snapshot(dates_to_values, target) == (200, 7)


def test_pick_base_snapshot_falls_back_within_the_window() -> None:
    target = date(2026, 1, 15)
    dates_to_values = {target - timedelta(days=9): 300}
    assert pick_base_snapshot(dates_to_values, target) == (300, 9)


def test_pick_base_snapshot_breaks_ties_toward_the_older_day() -> None:
    target = date(2026, 1, 15)
    # 6 and 8 days back are equidistant from the nominal 7-day target;
    # the older (8-day) snapshot wins.
    dates_to_values = {
        target - timedelta(days=6): 100,
        target - timedelta(days=8): 200,
    }
    assert pick_base_snapshot(dates_to_values, target) == (200, 8)


def test_pick_base_snapshot_returns_none_outside_the_window() -> None:
    target = date(2026, 1, 15)
    dates_to_values = {target - timedelta(days=1): 100, target - timedelta(days=20): 200}
    assert pick_base_snapshot(dates_to_values, target) is None


def test_pick_base_snapshot_returns_none_for_no_history() -> None:
    assert pick_base_snapshot({}, date(2026, 1, 15)) is None
