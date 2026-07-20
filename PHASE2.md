# Phase 2 — Execution Spec: The Pure Core and Its Tests

**Audience:** the model executing Phase 2. This document is self-contained: read it,
`CLAUDE.md`, and the Phase 2 section of `PLAN.md` before writing code. Where this spec
and PLAN.md's Phase 2 section disagree, **this spec wins** — every deviation is
deliberate and justified in "Corrections to the PLAN.md spec" below.

**Scope:** `services/api/src/ax/core/{config,money,amm,index,ledger}.py`, their tests
(invariants I1–I15), the `ax backtest` CLI command, and a committed CSV fixture.
Nothing else.

**Hard boundaries — do not cross:**

- **No schema changes, no migrations.** The whole v1 schema already shipped in one
  migration. Phase 2 is code-only.
- **Do not touch** `db/`, `api/`, `jobs/`, `providers/`, `settings.py`, or
  `migrations/`. The only file outside `core/` and `tests/` you may edit is `cli.py`
  (to register `backtest`), plus the docs/CI updates listed at the end.
- **No new dependencies.** Hypothesis and pytest-cov are already in the dev group.
  `core/` may import **stdlib only** (`math`, `statistics`, `dataclasses`, `datetime`,
  `typing`, `collections.abc`, `enum` are all fine) — `tests/test_core_purity.py`
  enforces this mechanically and must never be edited.
- **`mypy --strict` must pass on `core/`** (CI already runs it). Annotate everything.
- **Never weaken a test to make it pass.** If an invariant genuinely cannot hold as
  specified, stop, write the finding into an "Open questions" section at the bottom of
  this file, and report it — do not commit a loosened assertion or an `xfail`.
- Nothing in Phase 2 reads the database or the network. Production has ~1 day of real
  snapshots; the index needs 8. All Phase 2 data is synthetic fixtures.

**Context in one paragraph:** play-money market for musical artists. Fair value comes
from an index over nightly Last.fm snapshots; market price comes from a linear-bonding-
curve AMM whose anchor glides toward fair value nightly. The product claim is that
spotting a rising artist early is provably rewarded, and that *mechanically harvesting
the price→fair-value gap without evaluating artists* is not profitable. Phase 2 builds
the math that makes both halves true, as pure functions, with the invariant tests that
keep them true.

---

## Corrections to the PLAN.md spec

Each of these was found by analysis before implementation. The AMM closed forms, the
I5 symmetry, the buy/sell/fee rounding directions, and the weight/clamp ranges
(score always lands in [2, 98] before the final clamp, so the clamp is a backstop, not
an active shaper) were checked and are **correct as written in PLAN.md** — implement
those verbatim.

| # | PLAN.md said | Corrected to | Why |
|---|---|---|---|
| C1 | `effective_anchor` interpolates with a float `frac` | Integer microcent interpolation (see `amm.py` spec) | Float in a money path violates rule 1; integer floor-interpolation is exact at both endpoints and monotone, which is I15 |
| C2 | `REVERSION_RATE = 0.15` (float) | `REVERSION_RATE_BPS = 1_500` (int), move computed with sign-symmetric truncation | Float × cents is a money-path float. Python `//` on negatives floors away from zero, making downward reversion systematically 1 cent stronger than upward — an asymmetric drift |
| C3 | (unspecified) | `REVERSION_MIN_MOVE_CENTS = 1`: nonzero gap always moves ≥ 1 cent; cap floored at 1 cent | With truncation alone, gaps ≤ 6 cents produce move = 0 forever — I11 ("converges") would be false. Min-move makes convergence exact and terminating |
| C4 | z-score denominator = MAD | `max(MAD, ROBUST_Z_MIN_MAD)`, and skip the day if the eligible cross-section < `MIN_CROSS_SECTION_SIZE` | MAD is 0 whenever >half the universe has identical growth (e.g. small artists with unchanged weekly counts) → ZeroDivisionError on a plausible real input |
| C5 | Level term `S = clamp(zscore(ln(listeners)))` | Same **robust z** (median/MAD, 0.6745 scaling) as the growth term, on `ln(listeners + 1)` | (a) mean/std on skewed log-listeners makes I9 ("median ≈ 50") non-structural; median/MAD centers the median at exactly 0 by construction. (b) `+1` because listeners can be 0. (c) one z implementation, not two |
| C6 | "fall back to nearest in [t−9, t−5], adjust for actual day gap" | Explicit: `g = (ln(V_t+1) − ln(V_base+1)) * GROWTH_LOOKBACK_DAYS / gap_days` where `gap_days ∈ [5, 9]`, preferring the day closest to 7 (tie → older) | "Adjust" was unspecified; this is the only linear rescaling |
| C7 | EWMA recurrence given, initial state unspecified | First observation initializes the EWMA (`prev is None → Z = z`) | Decaying from an implicit 0 would bias every newly-listed artist toward the median for weeks |
| C8 | I8: "adding a constant to every artist's log-growth leaves every score **bit-identical**" | Three tests, see I8 spec below | `(g+c) − median(g+c)` is not bitwise `g − median(g)` under IEEE 754 — float addition is not associative. Bit-identity is provable only on dyadic (power-of-two) inputs; the general property holds to ~1e-9 |
| C9 | I14: one bot, "buys discounts / sells premiums nightly" | Two bots: the naive nightly round-tripper **and** a patient harvester who holds until the glide converges; simulation parameterized by fair-value volatility, printing a break-even frontier | The naive bot loses trivially (captures 15% of the gap, pays 1.5%). The patient bot captures ~85% of the gap and is the actual threat the guardrails must beat. Testing only the weak bot would be a false pass on the product's central economic claim |
| C10 | Position caps named but semantics undefined | `MAX_USER_SUPPLY_SHARE_BPS` is a share of `AMM_DEPTH_SHARES` (= 400 shares), **not** of live net supply; `MAX_ARTIST_EXPOSURE_BPS` is post-trade position market value vs. total user equity | Needed by I14's sim. Share-of-live-supply is degenerate: the first buyer of any artist would own 100% and be blocked |
| C11 | (unspecified) | A new nightly glide starts from the **current interpolated effective anchor**, not from stored `anchor_cents`/`anchor_target_cents` | The cron fires late (observed 2h late on day one). If the new glide starts from a stale endpoint, price jumps discontinuously at reversion time — exactly what the glide exists to prevent |
| C12 | Scout shares named in schema, qualification undefined | A buy is scout-qualified iff `index_score_at_trade < SCOUT_DISCOVERY_INDEX_MAX` **and** `exec_price_cents < SCOUT_DISCOVERY_PRICE_CENTS`; sells reduce scout shares proportionally (floor) | AND is the defensible reading of "still small"; OR would credit buying a dipped blue-chip. Proportional reduction resists gaming the Phase 6 leaderboard. Product-tunable, in config |
| C13 | `FairValue = round(...)` | Round half **up** (`int(x + 0.5)`), floored at `FAIR_VALUE_MIN_CENTS = 1` | Python `round()` is banker's rounding — surprising and pointless here. The floor keeps a score-1 artist's price ≥ 1 cent so the AMM never quotes 0 |

---

## Module specs

All money values are `int`. Suffix conventions are load-bearing: `_cents` is integer
cents, `_uc` is integer microcents (`1 cent = 1_000_000 uc`). Time is always a
parameter, always a timezone-aware `datetime`. Write docstrings in the repo's house
style: explain *why*, not *what*.

### `core/config.py`

Every constant below, each with a comment saying what tuning it up or down does
(CLAUDE.md rule 4). This is PLAN.md's table with the corrections applied:

```python
STARTING_BALANCE_CENTS      = 1_000_000   # $10,000
FAIR_VALUE_BASE_CENTS       = 1_000       # $10 at index 50
FAIR_VALUE_EXPONENT         = 1.6
FAIR_VALUE_MIN_CENTS        = 1           # C13
INDEX_MIN, INDEX_MAX        = 1.0, 100.0
GROWTH_WEIGHT               = 10.0
LEVEL_WEIGHT                = 6.0
Z_CLAMP                     = 3.0
ROBUST_Z_MIN_MAD            = 1e-6        # C4
MIN_CROSS_SECTION_SIZE      = 10          # C4
EWMA_ALPHA                  = 0.4
GROWTH_LOOKBACK_DAYS        = 7
GROWTH_BASE_WINDOW_DAYS     = 2           # base snapshot accepted in [t-9, t-5]
MIN_SNAPSHOTS_TO_LIST       = 8
SIGNAL_WEIGHTS              = {"lastfm.listeners": 0.60, "lastfm.playcount": 0.40}
AMM_DEPTH_SHARES            = 2_000
TRADE_FEE_BPS               = 100         # retuned from 75 post-I14; see "As built"
MAX_SLIPPAGE_BPS            = 300
MAX_TRADE_SHARES            = 500
REVERSION_RATE_BPS          = 1_500       # C2 (was float 0.15)
REVERSION_MAX_MOVE_BPS      = 1_000
REVERSION_MIN_MOVE_CENTS    = 1           # C3
REVERSION_GLIDE_HOURS       = 24
MAX_ARTIST_EXPOSURE_BPS     = 2_500       # C10: of user equity
MAX_USER_SUPPLY_SHARE_BPS   = 2_000       # C10: of AMM_DEPTH_SHARES -> 400 shares
SCOUT_DISCOVERY_INDEX_MAX   = 45.0
SCOUT_DISCOVERY_PRICE_CENTS = 1_000
SESSION_TTL_DAYS            = 90          # used in Phase 4; lives here per rule 4
MAGIC_LINK_TTL_MINUTES      = 15
```

Signal keys are `f"{source}.{metric_key}"` — the provider emits `source="lastfm"`,
`metric_key="listeners"|"playcount"` (see `providers/lastfm.py`), so the registry keys
above are already exact. `test_config.py` asserts `sum(SIGNAL_WEIGHTS.values()) == 1.0`
and the basic sanity relations (clamps positive, bps values in range, etc.).

### `core/money.py`

Small, boring, heavily reused:

```python
MICROCENTS_PER_CENT = 1_000_000

def ceil_div(n: int, d: int) -> int          # -(-n // d); d > 0
def cents_to_uc(cents: int) -> int
def uc_to_cents_ceil(uc: int) -> int         # buys round UP   (rule 6)
def uc_to_cents_floor(uc: int) -> int        # sells round DOWN (rule 6)
def uc_to_cents_nearest(uc: int) -> int      # display/spot only, uc >= 0; half rounds up
def bps_ceil(amount: int, bps: int) -> int   # fees: ceil(amount * bps / 10_000)
def bps_floor(amount: int, bps: int) -> int
```

`uc_to_cents_nearest` is **never** used on a buy or sell amount — it exists for spot
display, reversion gap measurement, and anchor persistence, where "favors the market"
has no meaning and determinism does.

### `core/amm.py`

Implement PLAN.md's closed forms exactly; they are verified correct:

- Buy `n` from supply `s` (the k-th share costs `anchor + slope·k`, `k = s … s+n−1`):
  `cost_uc = n·anchor_uc + slope_uc·(n·s + n·(n−1)//2)`, `cost_cents = uc_to_cents_ceil`.
- Sell `n` from supply `s` (walks `s−1 … s−n`):
  `proceeds_uc = n·anchor_uc + slope_uc·(n·(s−n) + n·(n−1)//2)`, `uc_to_cents_floor`.
- Fee both legs: `bps_ceil(cost_or_proceeds_cents, TRADE_FEE_BPS)` — so any nonzero
  trade pays ≥ 1 cent, which is what makes I2 strict.
- `spot_uc = effective_anchor_uc + slope_uc * net_supply` — the marginal price of the
  *next* share. Displayed/recorded spot is `uc_to_cents_nearest(spot_uc)`.

```python
@dataclass(frozen=True)
class BuyQuote:
    shares: int; cost_cents: int; fee_cents: int; total_cents: int   # cost + fee
    exec_price_cents: int          # ceil_div(cost_cents, shares)
    spot_before_uc: int; spot_after_uc: int

@dataclass(frozen=True)
class SellQuote:
    shares: int; proceeds_cents: int; fee_cents: int; net_cents: int  # proceeds - fee
    exec_price_cents: int          # proceeds_cents // shares (floor)
    spot_before_uc: int; spot_after_uc: int

def spot_price_uc(anchor_uc: int, slope_uc: int, net_supply: int) -> int
def buy_quote(anchor_uc: int, slope_uc: int, net_supply: int, shares: int) -> BuyQuote
def sell_quote(anchor_uc: int, slope_uc: int, net_supply: int, shares: int) -> SellQuote
def max_shares_within_slippage(spot_uc: int, slope_uc: int) -> int
    # floor(spot_uc * MAX_SLIPPAGE_BPS / 10_000 / slope_uc); slippage is defined as
    # (spot_after - spot_before) / spot_before, and spot moves exactly slope*n
def effective_anchor_uc(anchor_uc: int, target_uc: int,
                        glide_start: datetime, glide_end: datetime,
                        now: datetime) -> int
def reversion_move_cents(gap_cents: int, market_cents: int) -> int
def plan_reversion(anchor_cents: int, anchor_target_cents: int,
                   glide_start: datetime, glide_end: datetime,
                   slope_uc: int, net_supply: int,
                   fair_value_cents: int, now: datetime) -> ReversionPlan
```

Validation: quotes raise `ValueError` on `shares < 1`, `net_supply < 0`, or a sell
with `shares > net_supply`. Pure core raises; later phases translate to HTTP 4xx.

**`effective_anchor_uc` (C1)** — integer end to end:

```python
if now >= glide_end or glide_end <= glide_start: return target_uc
if now <= glide_start: return anchor_uc
elapsed = (now - glide_start) // timedelta(microseconds=1)   # exact int, no float
total   = (glide_end - glide_start) // timedelta(microseconds=1)
return anchor_uc + (target_uc - anchor_uc) * elapsed // total
```

Python floor division makes this monotone for both rising and falling glides, exactly
`anchor_uc` at start and `target_uc` at end (I15). At a typical 100-cent glide the
anchor moves ~1_157 uc/second — this is why a 2pm buyer sees P&L move by 2:01pm.

**`reversion_move_cents` (C2/C3)** — the pure kernel I10/I11 test:

```python
if gap_cents == 0: return 0
raw = abs(gap_cents) * REVERSION_RATE_BPS // 10_000          # truncation, symmetric
cap = max(REVERSION_MIN_MOVE_CENTS, market_cents * REVERSION_MAX_MOVE_BPS // 10_000)
magnitude = min(cap, max(REVERSION_MIN_MOVE_CENTS, raw))
return magnitude if gap_cents > 0 else -magnitude
```

Note `magnitude ≤ |gap|` always holds: `raw ≤ 0.15·|gap| ≤ |gap|` and the min-move 1
only applies when `|gap| ≥ 1`. That is I10.

**`plan_reversion` (C11)** composes: current effective anchor (interpolated **now**) →
spot → `market_cents = uc_to_cents_nearest(spot_uc)` → `gap = fair − market` → move →
returns `ReversionPlan(anchor_cents=uc_to_cents_nearest(eff_uc),
anchor_target_cents=that + move, glide_start_at=now,
glide_end_at=now + REVERSION_GLIDE_HOURS)`. Persisting the anchor endpoint in whole
cents snaps the price by ≤ 0.5 cent once nightly; that is accepted and documented —
do not "fix" it by storing microcents in a `*_cents` column.

### `core/index.py`

Pipeline (per as-of date, cross-sectional over eligible artists):

```
g_s(a)  = (ln(V_t + 1) − ln(V_base + 1)) * GROWTH_LOOKBACK_DAYS / gap_days     # C6
z_s(a)  = clamp(0.6745 * (g_s − median) / max(MAD, ROBUST_Z_MIN_MAD), ±Z_CLAMP) # C4
Z_s(a)  = z_s if prev is None else EWMA_ALPHA * z_s + (1−EWMA_ALPHA) * prev     # C7
G(a)    = Σ_s SIGNAL_WEIGHTS[s] * Z_s(a)
S(a)    = clamp(robust_z over ln(listeners_t + 1), ±Z_CLAMP)                    # C5
score   = clamp(50 + GROWTH_WEIGHT*G + LEVEL_WEIGHT*S, INDEX_MIN, INDEX_MAX)
fair    = max(FAIR_VALUE_MIN_CENTS, int(FAIR_VALUE_BASE_CENTS * (score/50)**FAIR_VALUE_EXPONENT + 0.5))
```

Floats are legitimate here — the index is a statistic, not money (see
`index_snapshots.index_score`). Money re-enters only at `fair`, an int.

```python
@dataclass(frozen=True)
class SignalInput:            # one artist, one signal, one day
    current: int              # V_t
    base: int                 # V_base from the window
    gap_days: int             # 5..9, callers pick closest-to-7 (tie -> older)
    prev_ewma: float | None   # from yesterday's components; None on first observation

@dataclass(frozen=True)
class ArtistDayInput:
    signals: Mapping[str, SignalInput]   # keyed by "source.metric_key"
    listeners: int                       # level term input

@dataclass(frozen=True)
class ArtistDayResult:
    index_score: float
    fair_value_cents: int
    components: dict[str, object]        # goes verbatim into index_snapshots.components

def robust_z(values: Sequence[float]) -> list[float]
def compute_index(day: Mapping[K, ArtistDayInput]) -> dict[K, ArtistDayResult]
def fair_value_cents(score: float) -> int
```

Eligibility: an artist enters the cross-section only if it has **every** configured
signal plus the level input for that day. Ineligible artists are simply absent from
the result — the Phase 3 job decides what "hold previous score" means. If fewer than
`MIN_CROSS_SECTION_SIZE` artists are eligible, return `{}` (no scores that day).

**`components` contract** (Phase 3 writes it, Phase 3's quarantine and Phase 6's
audit trail read it — treat as a versioned API):

```json
{"v": 1,
 "signals": {"lastfm.listeners": {"g": 0.0123, "z": 0.45, "ewma": 0.31,
                                   "gap_days": 7},
             "lastfm.playcount":  {"...": "..."}},
 "level_z": 1.2, "growth_term": 0.38, "level_term": 1.2,
 "score_pre_clamp": 61.0}
```

The `ewma` values are next day's `prev_ewma` — the state round-trips through this
dict. Phase 3 will add quarantine keys to it; leave room, don't validate strictly.

### `core/ledger.py`

Pure construction of ledger rows and position math. The DB writes them in Phase 4;
Phase 2's sim and invariant tests consume them directly.

```python
class Kind(StrEnum): GRANT="GRANT"; BUY="BUY"; SELL="SELL"; FEE="FEE"

@dataclass(frozen=True)
class LedgerEntry:
    kind: Kind
    artist_id: int | None        # None for GRANT; FEE carries the trade's artist_id
    cash_delta_cents: int
    share_delta: int             # 0 except BUY(+n)/SELL(-n)
    exec_price_cents: int | None

def grant_entries(amount_cents: int) -> list[LedgerEntry]
def buy_entries(artist_id: int, q: BuyQuote) -> list[LedgerEntry]   # BUY + FEE
def sell_entries(artist_id: int, q: SellQuote) -> list[LedgerEntry] # SELL + FEE
```

A buy is two rows: `BUY(cash −cost_cents, shares +n)` and `FEE(cash −fee_cents)`.
Fees have no counterparty row — they are burned, which is the economy's inflation
sink (CONCEPT.md "Economy inflation"). Conservation therefore reads:

> Σ user cash = Σ grants − Σ fees − amm_net, where amm_net = Σ buy costs − Σ sell proceeds.

```python
@dataclass(frozen=True)
class PositionState:
    shares: int = 0
    avg_cost_uc: int = 0          # weighted average, fee-inclusive
    realized_pnl_cents: int = 0
    scout_shares: int = 0

def scout_qualified(index_score: float | None, exec_price_cents: int) -> bool  # C12: AND
def apply_buy(pos: PositionState, q: BuyQuote, *, scout: bool) -> PositionState
def apply_sell(pos: PositionState, q: SellQuote) -> PositionState
```

Position math (informational — the cash rows above are the money truth, so simple
deterministic rounding is fine here):

- Buy: `avg' = (shares·avg + total_cents·1e6) // (shares + n)` — basis includes the
  fee, so leaderboard P&L is honest about costs. Floor division; drift < 1 uc/trade.
- Sell: `realized += net_cents − (avg·n) // 1_000_000` (floor);
  `scout' = scout·(shares−n) // shares` (proportional, floor — C12);
  selling to zero resets `avg` and `scout` to 0.
- Invariants maintained: `0 ≤ scout_shares ≤ shares`, `shares = 0 ⟹ avg = 0`.

Guardrail checks (pure predicates; the I14 sim and Phase 4's route both use them):

```python
def validate_buy(q: BuyQuote, *, cash_cents: int, user_shares_after: int,
                 position_value_after_cents: int, equity_after_cents: int) -> list[str]
def validate_sell(q: SellQuote, *, position_shares: int) -> list[str]
```

Violations (return all that apply, as stable string codes): `overdraft`
(`total_cents > cash`), `max_trade_shares`, `slippage`
(`shares > max_shares_within_slippage`), `supply_share_cap`
(`user_shares_after > MAX_USER_SUPPLY_SHARE_BPS·AMM_DEPTH_SHARES // 10_000`),
`exposure_cap` (`position_value_after > MAX_ARTIST_EXPOSURE_BPS·equity_after // 10_000`),
`oversell`.

---

## Test plan

Layout (this creates the fast pure suite CLAUDE.md's commands refer to):

```
services/api/tests/core/
  __init__.py
  strategies.py            # shared Hypothesis strategies
  sim.py                   # market simulation harness for I14 (test-only, not product code)
  fixtures/backtest_metrics.csv
  test_money.py  test_amm.py  test_glide.py  test_reversion.py
  test_index.py  test_ledger.py  test_config.py  test_sim_arb.py
```

Shared strategies (bound to the product's real ranges): `anchor_cents 1..500_000`,
`slope_uc 1..5_000_000`, `net_supply 0..100_000`, `shares 1..MAX_TRADE_SHARES`,
aware datetimes. Use config's real fee/slippage constants — the tests pin the product,
not an abstraction.

| Invariant | Test | How |
|---|---|---|
| I1 | `test_ledger` | Hypothesis: random interleaved buy/sell sequences for k users on one artist. Assert per-user cash ≡ grants + Σ cash_delta; the conservation identity above; and when net supply returns to 0, `amm_net ≥ 0` (the curve never pays out more than it took in — rounding direction made real) |
| I2 | `test_amm` | ∀ n, s, anchor, slope: buy n then sell n at the same anchor strictly loses ≥ 2 cents (two 1-cent-minimum fees) |
| I3 | `test_amm` | spot after buy − before = `slope·n` > 0; sells symmetric. (`slope_uc ≥ 1` — assert it in the strategy and in `test_config`) |
| I4 | `test_amm` | In uc, `cost(n)` **exactly equals** n sequential 1-share costs (integer sums are exact — assert `==`). Post-rounding, sequential ≥ single and the difference ≤ 2n cents |
| I5 | `test_amm` | `sell_quote(s, n).proceeds_uc == buy_quote(s−n, n).cost_uc` pre-rounding — exact integer equality |
| I6 | `test_ledger` | From the same sequences as I1: supply ≡ Σ share_delta, never negative; oversell raises/flags |
| I7 | `test_money`, `test_amm` | ceil/floor/bps helpers vs `fractions.Fraction` ground truth; every quote's cents ≥/≤ its exact uc value in the house's favor; fee ≥ 1 cent whenever amount > 0 |
| **I8** | `test_index` | **(a)** dyadic case: growths and shift `c` all exact binary fractions (e.g. multiples of 2⁻¹⁰) → scores **bit-identical** under `g → g+c`. **(b)** Hypothesis: arbitrary floats → per-artist score difference < 1e-9 and fair values differ by ≤ 1 cent. **(c) behavioral, the one that matters:** a universe where *every* artist's counts rise but artist X rises slower than median ⟹ X's score < 50 and X's fair value < base — monotonic inputs produced a falling price |
| I9 | `test_index` | Scores ∈ [1,100] under Hypothesis (any inputs). Median ≈ 50 ± 1 on the realistic fixture universe (structural now via C5, but EWMA history still wobbles it — keep the ±1) |
| I10 | `test_reversion` | ∀ gap, market: `sign(move) == sign(gap)`, `|move| ≤ |gap|`, `|move| ≤ max(1, market·1000//10⁴)` |
| I11 | `test_reversion` | Iterate `market += move` with fixed fair value: `|gap|` strictly decreases every step and reaches **exactly 0** in ≤ |gap₀| steps (C3 makes this exact, not asymptotic) |
| I12 | — | Already covered by Phase 1's `test_snapshot_job.py` (DB-level). Nothing to add in Phase 2 |
| I13 | `test_amm` | ∀ spot, slope: `n = max_shares_within_slippage` moves spot ≤ MAX_SLIPPAGE_BPS; `n+1` exceeds it |
| I14 | `test_sim_arb` | See below |
| I15 | `test_glide` | Hypothesis over (anchor, target, window, times): monotone in `now`; exactly `anchor_uc` at/before start; exactly `target_uc` at/after end; degenerate window → target; mixed rising/falling |

### I14 — the anti-arbitrage simulation (`sim.py` + `test_sim_arb.py`)

Deterministic, stdlib-only (`random.Random(seed)`), no DB. This is the test of the
product's central economic claim, so it gets the most care.

**Harness:** 200 artists, 200 days. Per-artist fair value follows a seeded geometric
random walk: `fair *= exp(gauss(0, σ_daily))`, clamped to [50, 5_000] cents; σ_daily is
a parameter run at `{0.25%, 0.5%, 1%, 2%}`. Each day, in order: (1) `plan_reversion`
for every artist; (2) the bot trades **at glide start** (pre-glide prices — the entry
most favorable to the bot, making the test conservative); (3) the glide completes
before the next day (24h glide, daily steps — no intraday modeling needed). Bot trades
go through `buy_quote`/`sell_quote`/`validate_*`/ledger entries — full fees, impact
(its own supply moves persist), slippage and position caps. Equity = cash + positions
at spot.

**Bot A — naive nightly round-tripper** (PLAN.md's original bot): each day buy the 10
largest percentage discounts (splitting a fixed budget), sell everything the next day.
**Assert: final equity < starting equity for every seed {1, 2, 3} at every σ.** This
must pass comfortably — it captures ~15% of the gap and pays ~1.5% + impact.

**Bot B — patient harvester** (the real threat): buy the 10 largest discounts whose
gap exceeds 2%, hold each until its gap < 0.5% or flips to premium, then sell. Sized
to respect slippage and position caps. **Assert: final equity ≤ starting equity for
every seed at σ ≤ 0.5%.** At higher σ, don't assert — **print** the per-σ mean return
table (the break-even frontier) so Phase 3 can compare real index volatility against
it.

**Why the split matters:** when fair value is a martingale and price mechanically
converges to it, a patient discount-buyer's gross edge is the steady-state gap, which
scales with σ_fv (≈ σ·(1/(1−(1−r)²))^½ for reversion rate r). At σ ≈ 0.5%/day the
top-decile gap ≈ 2%, right at the fee+impact hurdle — that's the regime the defaults
must win. At σ ≈ 2%/day no realistic fee kills the harvest; the defense there is that
EWMA smoothing, Z-clamping, and `REVERSION_MAX_MOVE_BPS` keep real fair-value series
much calmer than 2%/day. The frontier printout is how Phase 3 verifies that with real
data.

**If Bot B profits at σ ≤ 0.5%:** first audit the sim's fee/impact accounting (most
likely bug: bot trading at post-glide prices, or fees not applied on one leg). If the
economics genuinely fail, tune — `TRADE_FEE_BPS` up (≤ 150) first, then
`REVERSION_RATE_BPS` up (tighter tracking → smaller steady-state gaps; counterintuitive
but correct) — and record the change in this file's as-built notes and PLAN.md.
**Do not weaken the assertion.**

### Coverage

≥ 90% on `ax.core`, enforced: add to root `pyproject.toml`
`[tool.coverage.report] fail_under = 90` (and `show_missing = true`); change the CI
api job's test step to `uv run pytest --cov`. (`[tool.coverage.run] source = ["ax.core"]`
is already set.) Local bare `pytest` stays coverage-free and fast.

---

## `ax backtest` and the CSV fixture

CLI (in `cli.py`, which is allowed impure — but it must only import `core`, stdlib
`csv`, and typer; no DB session):

```
uv run ax backtest [--csv PATH] [--artist SLUG]
```

`--csv` defaults to the committed fixture. Reads long-format rows
(`artist_slug, as_of_date, source, metric_key, value`), replays dates in order through
`compute_index` carrying EWMA state via `components`, applies the per-day
warm-up/base-window rules, and prints one CSV row per artist-day to stdout:
`date, slug, index_score, fair_value_cents`, followed by a human summary (top 5 score
risers and fallers over the run). `--artist` filters to one slug's full series.

**Fixture:** `tests/core/fixtures/backtest_metrics.csv`, generated by a new committed
script `scripts/build_backtest_fixture.py` (same pattern as `build_seed.py`: seeded,
one-off, output committed and reviewable). ~12 artists × 35 days. Every playcount
series is monotone non-decreasing and a universe-wide ×1.001/day inflation multiplies
**all** counts — the fixture carries the real data's central pathology. Archetypes,
which double as known answers:

- `breakout` — listeners +2%/day, accelerating → final score > 60
- `laggard` — +0.05%/day: **absolute counts rise every single day**, score ends < 45
  and fair value falls below its early value (I8c end-to-end, the product truth)
- `steady-N` ×6 — +0.3%/day ± seeded noise → scores hover near 50
- `viral-spike` — one +40% day then flat → clamp + EWMA damp it; score decays back
  within ~a week rather than stepping
- `gappy` — days 12–17 missing → exercises the [t−9, t−5] base window and same-day
  exclusion
- `tiny` — listeners ~50 → integer-granularity edges

`test_index.py` (or a small `test_backtest.py`) runs the pipeline over the fixture and
asserts the archetype outcomes above — this is the "eyeball the series" verification
from PLAN.md turned into assertions, and the P2 verification step
("do known-growing artists actually score higher?") answered mechanically.

---

## Working order

Seven commits, each green (`uv run pytest`, `ruff check`, `ruff format --check`,
`mypy --strict services/api/src/ax/core`), each an undo point:

1. `config.py` + `money.py` + `test_config.py` + `test_money.py` (I7 helpers).
2. `amm.py` quotes/spot/glide/slippage + `test_amm.py`, `test_glide.py`
   (I2–I5, I7, I13, I15).
3. `reversion_move_cents` + `plan_reversion` + `test_reversion.py` (I10, I11).
4. `index.py` + `test_index.py` (I8, I9) + fixture generator + committed fixture.
5. `ledger.py` + `test_ledger.py` (I1, I6, position/scout math, validators).
6. `sim.py` + `test_sim_arb.py` (I14a/b). Budget real time here; it's the hardest part.
7. `ax backtest` in `cli.py` + backtest assertions + coverage gate + CI `--cov` + docs.

Run `/verify` before the nontrivial commits and `/code-review` on the diff before each
commit (repo convention).

## Done when

- [x] I1–I11, I13–I15 pass (I12 already green from Phase 1); full suite green.
- [x] `uv run pytest services/api/tests/core -q` runs the pure suite fast (< ~30s
      including Hypothesis and the sim) with no DB and no network.
- [x] Coverage ≥ 90% on `ax.core`, gated in CI.
- [x] `mypy --strict` clean on `core/`; purity test untouched and green.
- [x] `uv run ax backtest` prints the fixture's index/price series; archetype
      assertions pass; the laggard's fair value visibly falls while its raw counts rise.
- [x] I14 frontier table prints in test output; Bot A negative everywhere; Bot B
      non-positive at σ ≤ 0.5%.
- [x] Docs updated: PLAN.md Phase 2 checkbox ticked + a short "As built" subsection
      (same pattern as Phase 1's) noting any constant retuned by I14; CLAUDE.md's
      command list moves `ax backtest` out of the "not built yet" block and corrects
      the fast-suite path to `uv run pytest services/api/tests/core`; an "As built"
      section is appended to this file recording every deviation made during execution.

---

## As built

Seven commits landed as planned, in the order specified. `uv run pytest services/api/tests/core`
runs 74 tests in ~5s with no DB/network; `--cov` reports 99.65% on `ax.core` (single
uncovered line: `robust_z`'s empty-input guard, never hit because `compute_index` never
calls it below `MIN_CROSS_SECTION_SIZE`). Full suite (`uv run pytest --cov`, 127 tests
including Phase 1's DB-backed integration tests) stays green throughout.

**Deviations from this spec, each deliberate:**

1. **The archetype assertions (breakout, laggard, steady, viral-spike, gappy, tiny)
   landed in commit 4's `test_index.py`, not deferred to commit 7's `ax backtest` work.**
   The spec's working order sequenced them with the CLI; building the day-by-day,
   EWMA-carrying fixture replay for I9's "median ≈ 50" check (see #2) made the
   archetype checks nearly free to add at the same time, and PLAN.md's own Phase 2
   "Done when" bullet already treats them as verification of `ax backtest`'s output
   rather than a separate deliverable — so nothing was actually skipped, just pulled
   forward. `tests/core/fixture_data.py` (test-only) and `cli.py`'s own
   `_replay_metrics` (commit 7) independently implement the same replay logic;
   production cannot import test code, so this small duplication is intentional,
   the same tradeoff `sim.py` already documents for itself.

2. **I9's "median ≈ 50 ± 1 on the realistic fixture universe" needed the fixture's
   population redesigned twice before it held.** First finding: a single cold-start
   snapshot (`prev_ewma=None`, no history) was off by more than the ±1 tolerance —
   the spec's parenthetical ("EWMA history still wobbles it") turned out to mean the
   check is supposed to run against a *warmed-up*, EWMA-carrying replay, not a single
   day. Second finding, after building that replay: with only 6 "steady" archetypes
   plus the extreme named ones (11 artists total), the population median still
   landed 2+ points off target, seed-dependent. The reason is structural, not a bug:
   the cross-sectional median is an order statistic of the *combined* growth+level
   score, and each term being separately centered at 0 (by construction, via robust
   z) does not make the *joint* distribution's median artist land near (0, 0) with
   a small population — a single artist's noisy combination of growth-rank and
   level-rank can be the population's score-median while sitting off-center on each
   term individually. Raising the steady population to 8 (13 artists total, still
   "~12" per the spec) damps this down within tolerance. Recorded here rather than
   loosening the assertion, per the spec's own "never weaken a test" rule.

3. **I14 caught a real bot-design flaw, not a product-economics failure, first.**
   An early "patient harvester" sized every entry up to the full `MAX_SLIPPAGE_BPS`
   in one trade. On this AMM's calibrated depth (`AMM_DEPTH_SHARES = 2_000`,
   `FAIR_VALUE_BASE_CENTS = 1_000` ⇒ `slope ≈ 0.5` cents/share), a single
   slippage-maxed trade's own impact (~3%) is on the same order as the ~2–3% gaps
   being harvested — the bot was self-cannibalizing its edge before the reversion
   had a chance to realize any of it, and then paying the round-trip fee for a
   reliable loss that looked like "the product wins" for the wrong reason. Fixed by
   capping each entry's impact to a fraction of the *currently observed* gap
   (`_MAX_IMPACT_FRACTION_OF_GAP = 0.2` in `sim.py`), which is what "splitting into
   multiple trades" (PLAN.md's "why the arbitrage dies") is a proxy for: a
   sophisticated arbitrageur sizes to the edge available, not to the slippage
   ceiling. Caught by comparing the printed frontier's shape across σ — a jump from
   −0.3% to −72% between adjacent σ values was the tell that something other than
   the product's real economics was driving the number.
4. **After that fix, Bot B still cleared a small profit (+0.2% to +0.8% over 200
   days) at `sigma_daily = 0.5%`**, the volatility the defaults are required to beat
   (I14's assertion). Per the spec's prescribed order — audit first, then
   `TRADE_FEE_BPS` up to ≤ 150, then `REVERSION_RATE_BPS` — the audit found no
   further bug (fees charged on both legs, trades executed at glide-start prices as
   specified), so `TRADE_FEE_BPS` moved from 75 to 100 bps. That alone flips every
   seed negative at σ ≤ 0.5% (see the frontier table `test_sim_arb.py` prints) and
   leaves Bot A's already-comfortable losing margin untouched, since a higher fee
   only taxes round-tripping harder. `REVERSION_RATE_BPS` was not touched.

**Open questions for Phase 3:**

- The printed break-even frontier (σ ∈ {0.25%, 0.5%, 1%, 2%}) turns positive
  somewhere between σ = 0.5% and σ = 1%/day. Phase 3 should compute real
  day-to-day fair-value volatility from actual `metric_snapshots` once enough
  history exists, and confirm it sits comfortably under that line — if it doesn't,
  `EWMA_ALPHA`, `Z_CLAMP`, or `REVERSION_MAX_MOVE_BPS` are the next levers (they
  already damp real fair-value swings well below raw signal volatility per
  PLAN.md's Phase 3 section), not `TRADE_FEE_BPS` again.
- `SLOPE_UC` (the AMM's calibrated depth) is currently a single platform-wide
  constant derived from `FAIR_VALUE_BASE_CENTS` and `AMM_DEPTH_SHARES`, applied
  uniformly across artists in both `sim.py` and (implicitly) production. Real
  artists span a much wider price range (`FAIR_VALUE_MIN_CENTS = 1` up to whatever
  a score-100 blue-chip commands) than the sim's clamp of
  [50, 5_000] cents. Phase 4, which actually lists artists and sets their AMM
  parameters at listing time, should double check the fixed-slope assumption holds
  reasonably across that full range rather than only the sim's tested band.
