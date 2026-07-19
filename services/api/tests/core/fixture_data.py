"""Reads the committed backtest fixture CSV for the pure-core tests.

Test-only. Production's `ax backtest` (Phase 2 commit 7) reads the same
CSV directly in `cli.py`, with its own replay loop -- `core/` must stay
I/O-free, and `cli.py` can't import test code, so this small amount of
duplication is deliberate rather than shared.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

from ax.core.config import GROWTH_BASE_WINDOW_DAYS, GROWTH_LOOKBACK_DAYS
from ax.core.index import ArtistDayInput, ArtistDayResult, SignalInput, compute_index

BACKTEST_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "backtest_metrics.csv"

# {artist_slug: {"source.metric_key": {as_of_date: value}}}
FixtureSeries = dict[str, dict[str, dict[date, int]]]


def load_fixture(path: Path) -> FixtureSeries:
    series: FixtureSeries = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            slug = row["artist_slug"]
            signal_key = f"{row['source']}.{row['metric_key']}"
            as_of = date.fromisoformat(row["as_of_date"])
            value = int(row["value"])
            series.setdefault(slug, {}).setdefault(signal_key, {})[as_of] = value
    return series


def pick_base(dates_to_values: dict[date, int], target_day: date) -> tuple[int, int] | None:
    """The base snapshot for `target_day`'s growth rate (C6): prefers the
    day closest to `GROWTH_LOOKBACK_DAYS` back within the
    `+-GROWTH_BASE_WINDOW_DAYS` window, ties broken toward the older
    (larger-gap) day. Returns `(base_value, gap_days)`, or `None` if no
    day in the window has data."""
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


def _day_input(
    series: FixtureSeries, as_of: date, prev_ewma: dict[str, dict[str, float]]
) -> dict[str, ArtistDayInput]:
    day_input: dict[str, ArtistDayInput] = {}
    for slug, metrics in series.items():
        signals: dict[str, SignalInput] = {}
        for signal_key, dates_to_values in metrics.items():
            if as_of not in dates_to_values:
                break
            base = pick_base(dates_to_values, as_of)
            if base is None:
                break
            base_value, gap_days = base
            signals[signal_key] = SignalInput(
                current=dates_to_values[as_of],
                base=base_value,
                gap_days=gap_days,
                prev_ewma=prev_ewma.get(slug, {}).get(signal_key),
            )
        else:
            day_input[slug] = ArtistDayInput(
                signals=signals, listeners=metrics["lastfm.listeners"][as_of]
            )
    return day_input


def replay(series: FixtureSeries) -> dict[date, dict[str, ArtistDayResult]]:
    """Replay every date in `series` through `compute_index` in order,
    carrying each artist's EWMA state from one day's `components` into
    the next day's `prev_ewma` -- the same thing `ax backtest` (Phase 2
    commit 7) does against a live CSV, done here directly against the
    fixture so the pure-core tests can check the realistic, warmed-up
    cross-section rather than a single cold-start day."""
    all_dates = sorted(
        {d for metrics in series.values() for dates in metrics.values() for d in dates}
    )
    prev_ewma: dict[str, dict[str, float]] = {}
    results_by_date: dict[date, dict[str, ArtistDayResult]] = {}

    for as_of in all_dates:
        day_results = compute_index(_day_input(series, as_of, prev_ewma))
        results_by_date[as_of] = day_results

        for slug, result in day_results.items():
            signals_component = result.components["signals"]
            assert isinstance(signals_component, dict)
            for signal_key, info in signals_component.items():
                assert isinstance(info, dict)
                prev_ewma.setdefault(slug, {})[signal_key] = info["ewma"]

    return results_by_date
