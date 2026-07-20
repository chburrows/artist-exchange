"""Sanity relations on the tunable constants themselves.

Cheap and structural: these guard against a typo in config.py (a bps
value out of range, weights that don't sum to 1) rather than testing any
economics -- that's what test_amm.py / test_index.py / test_reversion.py
do against the constants.
"""

from ax.core import config


def test_signal_weights_sum_to_one() -> None:
    assert sum(config.SIGNAL_WEIGHTS.values()) == 1.0


def test_signal_weights_positive() -> None:
    assert all(w > 0 for w in config.SIGNAL_WEIGHTS.values())


def test_clamp_and_bounds_are_positive() -> None:
    assert config.Z_CLAMP > 0
    assert config.ROBUST_Z_MIN_MAD > 0
    assert config.MIN_CROSS_SECTION_SIZE > 0
    assert 0 < config.INDEX_MIN < config.INDEX_MAX


def test_ewma_alpha_is_a_valid_mixing_weight() -> None:
    assert 0 < config.EWMA_ALPHA <= 1


def test_bps_values_in_range() -> None:
    bps_constants = [
        config.TRADE_FEE_BPS,
        config.MAX_SLIPPAGE_BPS,
        config.REVERSION_RATE_BPS,
        config.REVERSION_MAX_MOVE_BPS,
        config.MAX_ARTIST_EXPOSURE_BPS,
        config.MAX_USER_SUPPLY_SHARE_BPS,
    ]
    assert all(0 < bps <= 10_000 for bps in bps_constants)


def test_amm_depth_and_trade_caps_positive() -> None:
    assert config.AMM_DEPTH_SHARES > 0
    assert config.MAX_TRADE_SHARES > 0
    assert config.MAX_TRADE_SHARES <= config.AMM_DEPTH_SHARES


def test_reversion_min_move_and_glide_positive() -> None:
    assert config.REVERSION_MIN_MOVE_CENTS >= 1
    assert config.REVERSION_GLIDE_HOURS > 0


def test_fair_value_constants_positive() -> None:
    assert config.FAIR_VALUE_BASE_CENTS > 0
    assert config.FAIR_VALUE_EXPONENT > 0
    assert config.FAIR_VALUE_MIN_CENTS >= 1


def test_scout_thresholds_positive() -> None:
    assert config.SCOUT_DISCOVERY_INDEX_MAX > 0
    assert config.SCOUT_DISCOVERY_PRICE_CENTS > 0


def test_oracle_manipulation_thresholds_are_sane() -> None:
    assert config.RATIO_DIVERGENCE_MAD_THRESHOLD > 0
    assert 0 < config.PERCENTILE_MOVE_THRESHOLD < 1
