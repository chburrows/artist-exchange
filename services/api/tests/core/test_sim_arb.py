"""I14: the anti-arbitrage simulation.

The test of the product's central economic claim: a bot that
mechanically buys the price-to-fair-value gap, without ever evaluating
an artist, should not be able to turn a reliable profit against the
AMM's fees, impact, slippage cap, and the reversion's own partial
convergence.

Bot A (the naive nightly round-tripper) must lose at every volatility
level tested -- it captures only ~15%/night of the gap and pays ~1.5%
plus impact on every round trip, so this should pass comfortably. Bot B
(the patient harvester, who holds until the gap itself closes) is the
real threat; it must not profit at sigma <= 0.5%/day, the volatility
regime real Last.fm-derived fair value is expected to stay well under.
Above that, the test only prints a break-even frontier table for Phase 3
to compare against real index volatility, rather than asserting --
Phase 2 is not responsible for whether pathologically volatile
fundamentals could someday out-run the fee schedule.
"""

import statistics

from .sim import run_bot_a, run_bot_b

SEEDS = [1, 2, 3]
SIGMAS = [0.0025, 0.005, 0.01, 0.02]


def test_bot_a_naive_round_tripper_always_loses() -> None:
    for sigma in SIGMAS:
        for seed in SEEDS:
            final_equity, starting_equity = run_bot_a(seed, sigma)
            assert final_equity < starting_equity, (
                f"Bot A profited at sigma={sigma}, seed={seed}: {final_equity} >= {starting_equity}"
            )


def test_bot_b_patient_harvester_does_not_profit_at_low_volatility() -> None:
    for seed in SEEDS:
        final_equity, starting_equity = run_bot_b(seed, 0.005)
        assert final_equity <= starting_equity, (
            f"Bot B profited at sigma=0.005, seed={seed}: {final_equity} > {starting_equity}"
        )


def test_bot_b_break_even_frontier() -> None:
    """Not an assertion of product correctness above sigma=0.5%/day --
    a printed frontier so Phase 3 can compare real index volatility
    against the point where the patient harvester starts winning."""
    print("\nI14 Bot B break-even frontier (mean return by sigma_daily):")
    for sigma in SIGMAS:
        returns = []
        for seed in SEEDS:
            final_equity, starting_equity = run_bot_b(seed, sigma)
            returns.append((final_equity - starting_equity) / starting_equity)
        mean_return = statistics.mean(returns)
        per_seed = [f"{r:+.4%}" for r in returns]
        print(f"  sigma={sigma:.4f}  mean_return={mean_return:+.4%}  per-seed={per_seed}")
