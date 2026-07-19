"""All tunable economics (CLAUDE.md rule 4).

Nothing in `amm.py`, `index.py`, `ledger.py`, or their callers should ever
inline a magic number that appears here. These constants get retuned
against live data over the product's life; the whole point of this module
is that "what do we change to make X happen" always has exactly one
answer, findable in one place.

Every constant carries a comment explaining what tuning it up or down
does, not just what it is.
"""

# --- Wallet -------------------------------------------------------------

STARTING_BALANCE_CENTS = 1_000_000
"""$10,000 play money granted on signup. Higher = more headroom before
position/exposure caps bind; lower = caps bind sooner and trading feels
more constrained."""

# --- Fair value -----------------------------------------------------------

FAIR_VALUE_BASE_CENTS = 1_000
"""Fair value in cents at IndexScore == 50 (the population median).
Scales every artist's price level uniformly; does not affect relative
pricing between artists."""

FAIR_VALUE_EXPONENT = 1.6
"""Convexity of fair value in the index score. Higher = a given score
edge above/below 50 produces a larger price gap (rewards conviction on
big movers more); 1.0 would make fair value linear in score."""

FAIR_VALUE_MIN_CENTS = 1
"""Floor so a score-1 artist still quotes a positive price; the AMM must
never see a zero anchor. (C13)"""

INDEX_MIN = 1.0
INDEX_MAX = 100.0
"""Hard bounds every index score is clamped into. Never loosen without
also re-deriving FAIR_VALUE_EXPONENT's effective price range."""

GROWTH_WEIGHT = 10.0
"""How many index-score points one unit of blended growth z-score is
worth. Higher = growth dominates the score (more responsive, more
volatile); lower = the level term dominates (calmer, more "market cap")."""

LEVEL_WEIGHT = 6.0
"""How many index-score points one unit of level z-score (size) is
worth. Higher = being big matters more than growing; this is the "blue
chip" pull against the "growth" pull."""

Z_CLAMP = 3.0
"""Symmetric clamp applied to every z-score (growth signals and the
level term) before it enters the score. Lower = dampens outliers harder,
protecting against one viral artist or data glitch dominating the
cross-section; this is a backstop on top of median/MAD robustness, not
the primary defense."""

ROBUST_Z_MIN_MAD = 1e-6
"""Floor on the MAD denominator in the robust z-score (C4). Without this,
a cross-section where more than half the artists have identical growth
(plausible for small, static artists) makes MAD exactly 0 and the
z-score a division by zero. Effectively never binds except in that
degenerate case, where it makes the z-score enormous-but-finite instead
of crashing; Z_CLAMP then reins it in."""

MIN_CROSS_SECTION_SIZE = 10
"""Minimum number of eligible artists required to compute a cross-
sectional index on a given day (C4). Below this, statistics like
median/MAD are too noisy to trust, so the day is skipped entirely
(returns no scores) rather than publishing a score built on noise."""

EWMA_ALPHA = 0.4
"""Smoothing weight on today's raw z-score vs. yesterday's EWMA state.
Higher = the index reacts faster to new data but is jumpier; lower =
calmer but slower to recognize a genuine breakout. Also the first line
of defense against oracle manipulation (PLAN.md Phase 3): it damps a
one-day scrobble-bot spike to `EWMA_ALPHA` of its raw effect."""

GROWTH_LOOKBACK_DAYS = 7
"""Target window (in days) for the growth rate g_s = ln(V_t) - ln(V_base).
Longer = smoother, slower-reacting growth signal; shorter = noisier but
more responsive."""

GROWTH_BASE_WINDOW_DAYS = 2
"""Half-width of the base-snapshot search window around t - GROWTH_LOOKBACK_DAYS
(C6): the base snapshot is accepted from [t-9, t-5] when the target is
t-7. Wider = more days survive a gap in the snapshot history at the cost
of a noisier gap_days-adjusted growth rate."""

MIN_SNAPSHOTS_TO_LIST = 8
"""Minimum historical snapshots an artist needs before it has an index
score at all and can be listed. Below this the artist is `warming_up`:
present in the universe, absent from the cross-section and from
listing."""

# --- Signal registry ------------------------------------------------------

SIGNAL_WEIGHTS: dict[str, float] = {
    "lastfm.listeners": 0.60,
    "lastfm.playcount": 0.40,
}
"""Weight of each signal's smoothed growth z-score in the blended growth
term G. Must sum to 1.0 (enforced in test_config.py). Listeners is
weighted above playcount because playcount is inflated by superfans
re-scrobbling, whereas listeners measures breadth of adoption -- which is
what "breaking out" actually means. Adding a new signal (e.g. YouTube) is
one new dict entry plus a provider class; no migration, because
metric_snapshots is long-format."""

# --- AMM --------------------------------------------------------------

AMM_DEPTH_SHARES = 2_000
"""Shares of net supply over which the linear bonding curve's slope is
calibrated (slope = FAIR_VALUE_BASE_CENTS / AMM_DEPTH_SHARES, in
microcents). Higher = a deeper market (more shares trade before price
moves materially, less slippage per trade); lower = a shallower, more
reactive-to-flow market."""

TRADE_FEE_BPS = 75
"""Fee charged on both legs of every trade, in basis points of the trade
amount. Higher = a stronger tax on round-tripping / gap-arbitrage (part
of what makes mechanically harvesting the price-to-fair-value gap
unprofitable), but also a higher cost for genuine scouting trades."""

MAX_SLIPPAGE_BPS = 300
"""Maximum allowed spot-price move (in bps of the pre-trade spot) for a
single trade. Lower = forces large orders to split into more trades
(each paying the full fee, compounding the anti-arb effect); higher =
larger single trades permitted, less friction for genuine large
positions."""

MAX_TRADE_SHARES = 500
"""Hard cap on shares per single trade, independent of slippage. Backstop
against a single fat-fingered or adversarial order regardless of how deep
the book is."""

# --- Nightly reversion + glide -----------------------------------------

REVERSION_RATE_BPS = 1_500
"""Fraction (in bps) of the price-to-fair-value gap closed by one
night's reversion. Higher = price tracks fair value faster (rewards
being early less, since the market catches up quicker); lower = slower
convergence, more room for early conviction to pay off before the market
"catches up" to the same information."""

REVERSION_MAX_MOVE_BPS = 1_000
"""Cap on a single night's anchor move, in bps of the current market
price. Protects against one extreme index swing (e.g. an oracle-
manipulation spike, or a data glitch) moving price too far in one
glide."""

REVERSION_MIN_MOVE_CENTS = 1
"""Minimum nonzero move applied when the gap is nonzero (C3). Without a
floor, `REVERSION_RATE_BPS` truncation makes any gap under ~6-7 cents
produce a zero move forever, so reversion would never actually converge
gap to zero. This makes convergence exact and terminating (I11)."""

REVERSION_GLIDE_HOURS = 24
"""Duration over which one night's anchor move is linearly interpolated
into the effective anchor, rather than applied as a step. This is the
fix for the dead-first-session problem: price moves continuously, so a
user's P&L visibly changes minutes after they trade. Set so each glide
ends exactly as the next one begins."""

# --- Position / exposure caps -------------------------------------------

MAX_ARTIST_EXPOSURE_BPS = 2_500
"""Cap on one artist's position value as a fraction (bps) of a user's
total equity, checked post-trade. Lower = forces diversification across
artists (weaker single-artist conviction bets); higher = allows more
concentrated scouting bets."""

MAX_USER_SUPPLY_SHARE_BPS = 2_000
"""Cap on one user's shares in one artist as a fraction (bps) of
AMM_DEPTH_SHARES (a fixed depth constant, not of live net supply --
supply-relative would degenerately block the first buyer of any artist
from owning more than a sliver). Lower = spreads ownership across more
users per artist; higher = allows a single user to dominate one artist's
float."""

# --- Talent Scout ---------------------------------------------------------

SCOUT_DISCOVERY_INDEX_MAX = 45.0
SCOUT_DISCOVERY_PRICE_CENTS = 1_000
"""A buy is "scout-qualified" iff index_score_at_trade is below
SCOUT_DISCOVERY_INDEX_MAX **and** exec_price_cents is below
SCOUT_DISCOVERY_PRICE_CENTS (C12) -- both conditions, so buying a merely
dipped blue-chip does not count as scouting an unknown. Lower either
threshold to make the "still small" bar stricter."""

# --- Auth (Phase 4; lives here per rule 4) --------------------------------

SESSION_TTL_DAYS = 90
MAGIC_LINK_TTL_MINUTES = 15
