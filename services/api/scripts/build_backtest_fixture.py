"""One-off, seeded generator for `tests/core/fixtures/backtest_metrics.csv`.

Same pattern as `build_seed.py`: deterministic, run by hand, output
committed and reviewable rather than regenerated on the fly.

Every artist's raw counts carry the real data's central pathology: a
universe-wide multiplicative inflation applied on top of each artist's
own trend, so every playcount series is monotone non-decreasing
regardless of whether the artist is genuinely rising or falling in
*relative* popularity. Each archetype below doubles as a known answer
for `test_index.py`'s and (Phase 2 commit 7's) `ax backtest`'s
assertions:

  breakout    -- accelerating growth -> ends with a score well above 50.
  laggard     -- rises every single day, just slower than the rest ->
                 ends with a score below 50 and a fair value below its
                 early value (I8 end to end, the product truth).
  steady-N x8 -- gentle growth +- seeded noise -> scores stay strictly
                 between the laggard and the breakout (a large `SIGNAL_WEIGHTS`
                 growth weight amplifies even small noise, so "hover near
                 50" means "not an extreme", not a tight band).
  viral-spike -- one +40% day, then flat -> spikes hard within a few
                 days, then decays back down over the following weeks
                 rather than stepping permanently.
  gappy       -- a run of missing days -> exercises the
                 [t-9, t-5] base-window fallback and same-day exclusion.
  tiny        -- a small-listener artist -> integer-granularity edges.

A population of 8 steady artists (rather than a token 1-2) is deliberate:
the cross-sectional median is an order statistic of the *combined*
growth+level score, not of either term alone, so with too few artists a
single noisy draw can visibly shift the population median away from 50
even though every individual term is separately well-centered. A larger
"normal" majority damps that sampling noise down to the +-1 the product
actually expects (see PLAN.md's Phase 2 "As built" notes).

Usage:
    uv run python services/api/scripts/build_backtest_fixture.py
"""

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEED = 42
NUM_DAYS = 35
START_DATE = date(2024, 1, 1)
UNIVERSE_DAILY_INFLATION = 1.001  # applied to every artist's every metric, every day

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "core" / "fixtures" / "backtest_metrics.csv"
)

FIELDNAMES = ["artist_slug", "as_of_date", "source", "metric_key", "value"]


@dataclass(frozen=True)
class Archetype:
    slug: str
    start_listeners: int
    daily_rate: float  # baseline fractional daily growth in listeners, pre-inflation
    accelerate: float = 0.0  # added to daily_rate once per elapsed day (breakout)
    noise_sd: float = 0.0  # gaussian noise on daily_rate, floored at 0 (steady-N)
    spike_day: int | None = None  # one-off multiplicative jump (viral-spike)
    spike_multiplier: float = 1.0
    missing_days: frozenset[int] = field(default_factory=frozenset)  # (gappy)
    playcount_multiplier: float = 6.0  # playcount tracks listeners at a fixed ratio


ARCHETYPES = [
    Archetype("breakout", start_listeners=20_000, daily_rate=0.008, accelerate=0.0008),
    Archetype("laggard", start_listeners=20_000, daily_rate=0.0015),
    *(
        Archetype(f"steady-{i}", start_listeners=20_000, daily_rate=0.003, noise_sd=0.002)
        for i in range(8)
    ),
    Archetype(
        "viral-spike", start_listeners=20_000, daily_rate=0.003, spike_day=10, spike_multiplier=1.4
    ),
    Archetype(
        "gappy", start_listeners=20_000, daily_rate=0.004, missing_days=frozenset(range(12, 18))
    ),
    Archetype("tiny", start_listeners=50, daily_rate=0.004, playcount_multiplier=3.0),
]


def _build_listener_series(archetype: Archetype, rng: random.Random) -> list[int]:
    listeners = float(archetype.start_listeners)
    series: list[int] = []
    for day in range(NUM_DAYS):
        if archetype.spike_day is not None and day == archetype.spike_day:
            listeners *= archetype.spike_multiplier
        else:
            day_rate = archetype.daily_rate + archetype.accelerate * day
            if archetype.noise_sd:
                day_rate += rng.gauss(0, archetype.noise_sd)
            day_rate = max(day_rate, 0.0)  # never shrinks -- the monotone pathology
            listeners *= 1 + day_rate
        listeners *= UNIVERSE_DAILY_INFLATION
        series.append(round(listeners))
    return series


def build_rows() -> list[dict[str, str]]:
    rng = random.Random(SEED)
    rows: list[dict[str, str]] = []
    for archetype in ARCHETYPES:
        listener_series = _build_listener_series(archetype, rng)
        for day, listeners in enumerate(listener_series):
            if day in archetype.missing_days:
                continue
            as_of = (START_DATE + timedelta(days=day)).isoformat()
            playcount = round(listeners * archetype.playcount_multiplier)
            rows.append(
                {
                    "artist_slug": archetype.slug,
                    "as_of_date": as_of,
                    "source": "lastfm",
                    "metric_key": "listeners",
                    "value": str(listeners),
                }
            )
            rows.append(
                {
                    "artist_slug": archetype.slug,
                    "as_of_date": as_of,
                    "source": "lastfm",
                    "metric_key": "playcount",
                    "value": str(playcount),
                }
            )
    return rows


def main() -> None:
    rows = build_rows()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"Wrote {len(rows)} rows for {len(ARCHETYPES)} artists over {NUM_DAYS} days "
        f"to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
