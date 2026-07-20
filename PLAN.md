# Artist Exchange — v1 Build Plan

## Context

`/home/cameron/artist-exchange` is an empty repo (zero commits) containing only `CONCEPT.md`, `temp-instructions.md`, and `secrets.env`. The concept: a play-money market where users buy and sell "shares" of musical artists, where price is anchored to a real popularity index derived from public data. The goal is a product that reaches real users fast, then iterates — with good enough bones to become a business.

This plan turns the concept into a phased build. Two things shaped it most:

1. **A hard data dependency.** Week-over-week growth cannot be computed until weeks of snapshots exist, and Last.fm exposes no history. So the snapshotter ships to production *first*, before any UI, and accumulates real history while everything else is built.
2. **An economic flaw that had to be designed around.** A deterministic nightly reversion toward a publicly computable fair value creates a risk-free arbitrage: buy the biggest discount, sell the biggest premium, never evaluate an artist. That would let players win at a talent-scouting game without scouting talent. Fees, partial reversion, slippage limits, and position caps exist specifically to make that strategy unprofitable.

### Decisions locked with the user

| | |
|---|---|
| Pricing | Hybrid AMM retained (index-only pricing was considered and rejected) |
| V1 in | Universe, index, AMM pricing, buy/sell, portfolio, per-artist chart, leaderboards |
| V1 out | Shorting, tournaments, streaks/safety net, mobile, real money, paid data providers |
| Stack | Next.js SPA · FastAPI + SQLAlchemy 2.0 + Alembic · Postgres |
| Hosting | All-in on Railway (web + api + managed Postgres), Dockerfile-first for portability |
| Jobs | GitHub Actions cron → POST protected `/internal/jobs/snapshot`, idempotent |
| Auth | Self-built: claim-a-username → session cookie, optional email + magic link |

### Environment (verified, not assumed)

Docker 2.28 + daemon running · Node 20.20 · pnpm 10.33 · gh CLI present.
**Gaps to close in Phase 0:** `uv` not installed; system Python is 3.10 but we target 3.12 to match the container. No `psql` on host — use `docker compose exec`.

---

## Progress

- [x] **Phase 0** — Hygiene, project docs, CI skeleton
- [x] **Phase 1** — Schema, snapshotter — *deployed to Railway 2026-07-19; unattended cron confirmed 2026-07-19 (schedule-trigger run, 200/200 artists, 400 rows upserted, `max(fetched_at)` 09:01 UTC verified in prod DB)*
- [x] **Phase 2** — Pure core + invariant tests — *I1–I11, I13–I15 green (I12 already covered by Phase 1); 99.65% coverage on `ax.core`; `ax backtest` replays the committed fixture; `TRADE_FEE_BPS` retuned 75→100 bps after the I14 sim (see "As built" below)*
- [x] **Phase 3** — Index + reversion on real data — *`jobs/recompute.py` + `/internal/jobs/recompute` + `ax recompute`, appended to the nightly Action after `snapshot`; oracle-manipulation quarantine (ratio-divergence + percentile-move, both human-cleared) implemented and covered by 17 new integration tests against real Postgres; 150 tests green, 99.67% coverage on `ax.core`. **Not yet verified against real accumulated data** — Railway deploy and this Phase 3 work landed the same UTC day, so production has one day of `metric_snapshots`, not the weeks `MIN_SNAPSHOTS_TO_LIST`/real-volatility verification needs (see "As built" below)*
- [x] **Phase 4** — Auth, trading, portfolio API — *claim-a-username + session cookie + magic-link recovery (Resend), `POST /trades/quote`+`POST /trades` under a fixed `balance_cache`-then-artist `FOR UPDATE` lock order, `GET /artists`/`{slug}`/`{slug}/history`, `GET /portfolio`, `jobs/reconcile.py` rebuilding both caches from the ledger nightly; `jobs/recompute.py` retrofitted with the same artist-row lock. 212 tests green, 99.68% coverage on `ax.core`; local smoke test against the real dev DB confirmed a ~2% fee-driven round-trip loss (see "As built" below)*
- [ ] **Phase 5** — The SPA
- [ ] **Phase 6** — Leaderboards, discovery, polish

---

## Phase 0 — Hygiene, project docs, CI skeleton (~half day)

- [x] `.gitignore` committed first, alone
- [x] `PLAN.md`, `CLAUDE.md`, `SETUP.md`
- [x] `CONCEPT.md` revised to match locked v1 scope
- [x] `uv` installed, Python 3.12 toolchain
- [x] `pyproject.toml`, `pnpm-workspace.yaml`, `docker-compose.yml`
- [x] `ci.yml` green

**`.gitignore` is committed first, alone, before any broad `git add`.** `secrets.env` is currently untracked in a repo with no commits, so there is no history to scrub and no key rotation needed — provided that ordering holds. This is the single most time-sensitive step in the plan.

### Documents to write into the repo (first commit after `.gitignore`)

**`PLAN.md`** — this plan, copied into the repo verbatim so it survives sessions and is versioned alongside the code. Phase checkboxes get ticked as work lands.

**`CLAUDE.md`** — the file loaded automatically every session; the highest-leverage thing in the repo for keeping week-12 work consistent with week-1 work. Contents:

- *Project*: one-paragraph description; pointer to `CONCEPT.md` (product truth) and `PLAN.md` (build truth).
- *Stack*: Next.js SPA (static export) · FastAPI + SQLAlchemy 2.0 + Alembic · Postgres · Railway · uv/pnpm.
- *Commands*: `ax reset` / `ax seed-artists` / `ax fake-history` / `ax simulate-trades`, `uv run pytest`, `pnpm dev`, `pnpm e2e`, `alembic upgrade head`, `docker compose up -d`.
- *Layout*: the directory tree, with a one-line purpose per top-level directory.
- *Non-negotiable rules*, stated as rules rather than suggestions:
  - Money is **integer cents (bigint)**. Never float, never `NUMERIC`, on any price or balance column.
  - `transactions` is **append-only**. No `UPDATE`, no `DELETE`, ever.
  - `core/` is **pure** — no SQLAlchemy, no FastAPI, no I/O, no `datetime.now()`. Time is always a parameter. Enforced by `tests/test_core_purity.py`.
  - All tunable economics live in `core/config.py`. Never inline a magic number in `amm.py` or `index.py`.
  - Every index input is a **cross-sectional z-score of a growth rate**, never a level. See invariant I8 and the reasoning behind it.
  - Rounding always favors the market: buys round up, sells round down.
  - Job endpoints must be **idempotent on `(artist_id, as_of_date)`**.
  - Balances/positions are derived from the ledger; caches are written in the *same transaction* as the ledger append.
- *Gotchas*: Last.fm `playcount` is monotonic (hence I8); Last.fm skews older/indie/Western and is weakest exactly on the growth tier; `fake-history` is dev-only and must never reach production display; Python target is 3.12 while the host has 3.10 — use `uv`.
- *Conventions*: commit at every phase boundary; `/verify` before nontrivial commits; `/code-review` on the diff.

**`SETUP.md`** — which `secrets.env` key goes into which `.env`, and how to get a Railway deploy running from scratch.

### Then

`pyproject.toml` (uv, ruff, mypy), `pnpm-workspace.yaml`, `docker-compose.yml` (postgres:16 + adminer; apps run on host for speed), `ci.yml`.

Install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and let it manage the 3.12 toolchain.

**Done when:** `docker compose up -d && pnpm install && uv sync` works, CI is green, and `CLAUDE.md` / `PLAN.md` / `SETUP.md` are committed.

---

## Phase 1 — Schema, snapshotter, deployed ← critical path (~2–3 days)

Everything downstream depends on data that only accumulates in wall-clock time. Ship this to production in week one.

Build `db/models.py`, the initial Alembic migration, `providers/lastfm.py`, `jobs/snapshot.py`, the bearer-token `/internal/jobs/snapshot` endpoint, `.github/workflows/nightly-snapshot.yml`, a curated `data/artists_seed.json` (~200 artists across growth + blue-chip tiers), and the Railway deploy of api + Postgres.

Idempotency comes from the primary key `(artist_id, as_of_date, source, metric_key)` with `ON CONFLICT DO UPDATE`, so re-runs and manual retries are always safe. Last.fm allows ~5 req/s; 200 artists sequential with backoff is ~40s, no concurrency needed.

**Done when:** `metric_snapshots` grows by ~200 rows nightly in production, unattended.

### As built

Local verification against the live Last.fm API: **200/200 artists, 400 rows, 51.9s**, zero not-found and zero failures. Run twice for the same date, the row count stayed at 400 — I12 observed on real data, not just in tests. 42 tests green; `alembic check` clean; the image builds, serves `/health` in 2s, and stops in 0.4s.

Decisions and surprises worth carrying forward:

- **The whole schema shipped in one migration**, not just Phase 1's tables. The data model was already fully specified, so production carries the finished shape from the first deploy and later phases are code-only.
- **Last.fm reports "artist not found" as HTTP 200** with an error body. A provider that trusts the status code records garbage as a real observation. The body is parsed for `error` before anything else.
- **`Mapped[datetime | None]` silently ignores an `Annotated` column alias.** The first autogenerate produced seven *naive* timestamp columns, including `glide_start_at`/`glide_end_at` — which would have made the Phase 2 glide interpolation wrong by the server's UTC offset. Fixed at the root with `type_annotation_map` on `Base`, so it cannot recur for any future column.
- **httpx logs full request URLs at INFO, and ours carry `api_key`.** The first live run wrote the Last.fm key into the logs; in production that would put a secret into Railway's log aggregator. `logging_config.py` exists solely to prevent this.
- **The artist universe is generated from the API, not hand-written**, so every entry is guaranteed to resolve — hence zero not-found on a full run. `scripts/build_seed.py` is the one-off generator; its output is committed and reviewable.
- **The seed generator must round-robin across genre tags.** Concatenating them looked equivalent but wasn't: resolution stops at the target count, so the first few tags filled the entire growth tier. The first run produced a "growth tier" of shoegaze, hyperpop and midwest emo with zero reggaeton, k-pop, grime or jungle.
- **Artists named entirely in non-Latin scripts slugify to the empty string**, which collides on `artists.slug`. They fall back to a stable hash of the name.
- **`alembic/env.py` must not overwrite an explicitly-supplied `sqlalchemy.url`.** It did, which meant the test harness migrated — and would have written to — the developer's real database.
- **`price_history` took a surrogate key instead of `(artist_id, at)`**, the one deliberate departure from the data model above. Both the collision and the ordering-inversion behind that decision were reproduced against a live database — see "Why `price_history` has a surrogate key".

Deferred to Phase 4, where the trading semantics are settled: the `v_balances` / `v_positions` views. The tables they read from exist; the views do not yet.

### Deploy notes (Railway, 2026-07-19)

Three things were wrong in a way that only surfaces at deploy time, all now fixed:

- **`releaseCommand` is Heroku, not Railway.** Verified against `railway.schema.json`; the correct key is `preDeployCommand`. Railway ignores unknown keys silently, so `alembic upgrade head` would never have run — and because `/health` deliberately does not touch the database, the service would have looked healthy while every real query failed against an empty schema.
- **Railway emits `DATABASE_URL` as `postgresql://`**, which SQLAlchemy resolves to psycopg2. This project uses psycopg 3, so the raw variable crashed the API on boot. Normalized in `settings.py` so the Railway variable can be referenced directly rather than hand-copied.
- **`railway.json` lives at `services/api/railway.json`, not the repo root.** The Docker build context must be the repo root (that is where `uv.lock` and `alembic.ini` are), so the service's Root Directory is `/` — which means Railway does *not* find the config automatically. The service's config-as-code path must be set explicitly, or the equivalent fields set in the dashboard.

A 502 on `/health` is a routing problem, never a database one: the endpoint answers 200 with a completely unreachable `DATABASE_URL`. Check the port before anything else.

### Confirming the cron

The nightly Action fires at **07:00 UTC**. Because `as_of_date` is the UTC date at fire time, a manual run earlier on the same UTC day means the scheduled run **upserts that same date** rather than adding one — the row count stays flat, which is idempotency working, not a failure.

So the check is *not* "row count doubled". It is:

1. `gh run list --workflow=nightly-snapshot.yml` shows a run whose trigger is `schedule`, not `workflow_dispatch`.
2. `SELECT as_of_date, count(*), max(fetched_at) ... GROUP BY as_of_date` shows `max(fetched_at)` at or after 07:00 UTC.

"At or after", not "at": GitHub delays scheduled workflows under load — on-the-hour crons are the most congested slots, and hours-late (or occasionally dropped) runs are documented behavior. A late `fetched_at` is normal; only a missing run for a whole UTC day is a real gap.

A genuinely new `as_of_date` appears only after a UTC day with no manual run — for this deploy, the *second* night.

**Confirmed 2026-07-19**: schedule-trigger run fired 09:01 UTC (2h GitHub delay), succeeded on attempt 1 — 200/200 artists, 400 rows upserted, zero not-found/failed; `max(fetched_at)` 09:01 UTC verified in the production DB.

---

## Phase 2 — The pure core and its tests (~2–3 days)

`services/api/src/ax/core/{config,money,amm,index,ledger}.py`. No SQLAlchemy, no FastAPI, no I/O, no `datetime.now()` — time is always a parameter. Purity is enforced mechanically by `tests/test_core_purity.py`, which walks the ASTs and asserts no import outside stdlib. That test is the cheapest guard against the core rotting into DB-coupled mess.

Built from a pre-implementation design review that corrected several things below that would otherwise have put a float in a money path or left an edge case unspecified. This section shows the corrected, as-built formulas directly.

### Index Score

Designed so that **monotonic inputs cannot produce monotonic prices**. `playcount` only ever rises; if the index were built on levels, nothing would ever fall and every position would win. Every input is therefore a cross-sectional z-score of a *growth rate* — if the whole universe inflates, every score is unchanged.

```
g_s(a,t)   = (ln(V[a,t] + 1) - ln(V[a,t-base] + 1)) * GROWTH_LOOKBACK_DAYS / gap_days
             # base snapshot is whichever day in [t-9, t-5] is closest to t-7 (tie -> older);
             # rescaled linearly to a nominal 7-day rate when the actual gap isn't 7
z_s(a,t)   = clamp(0.6745 * (g_s - median_s) / max(MAD_s, ROBUST_Z_MIN_MAD), ±Z_CLAMP)
             # median/MAD, not mean/stdev; MAD floored so a cross-section where more than
             # half the artists have identical growth can't divide by zero
Z_s(a,t)   = z_s                                          on an artist's first observation
           = EWMA_ALPHA * z_s + (1 - EWMA_ALPHA) * Z_s(a,t-1)   otherwise
G(a,t)     = Σ SIGNAL_WEIGHTS[s] * Z_s(a,t)                       # weight registry
S(a,t)     = clamp(0.6745 * (ln(listeners+1) - median) / max(MAD, ROBUST_Z_MIN_MAD), ±Z_CLAMP)
             # the SAME robust z as the growth terms, not mean/stdev — centers the
             # population median at (structurally) 0, which is what makes I9 hold
IndexScore = clamp(50 + GROWTH_WEIGHT*G + LEVEL_WEIGHT*S, INDEX_MIN, INDEX_MAX)
FairValue  = max(FAIR_VALUE_MIN_CENTS, int(FAIR_VALUE_BASE_CENTS * (IndexScore/50) ** FAIR_VALUE_EXPONENT + 0.5))
             # round-half-up (not Python's banker's-rounding `round()`), floored at 1 cent
```

If fewer than `MIN_CROSS_SECTION_SIZE` artists are eligible on a given day (missing any configured signal disqualifies an artist for that day), the cross-section is skipped entirely — no scores published, rather than statistics computed on a noisy handful.

Log growth (not percent) is symmetric and immune to small-denominator blowups across a 4-order-of-magnitude size range. Median/MAD stops one viral artist compressing everyone else. Listeners is weighted above playcount because playcount is inflated by superfans re-scrobbling, whereas listeners measures breadth of adoption — which is what "breaking out" actually means.

Missing `t-7` snapshot → fall back to the nearest day in `[t-9, t-5]` as shown above. None available → artist is `warming_up`, excluded from the cross-section and from listing.

**`components` (written to `index_snapshots.components`) is a versioned API, not a debug dump:**

```json
{"v": 1,
 "signals": {"lastfm.listeners": {"g": 0.0123, "z": 0.45, "ewma": 0.31, "gap_days": 7},
             "lastfm.playcount":  {"...": "..."}},
 "level_z": 1.2, "growth_term": 0.38, "level_term": 1.2, "score_pre_clamp": 61.0}
```

`ewma` is next day's `prev_ewma` — the smoothing state round-trips through this dict. Phase 3 adds quarantine keys to this same structure (never restructures it); Phase 6's audit trail reads it too.

**Adding YouTube later is one dict entry in `SIGNAL_WEIGHTS` plus a provider class.** No migration, because `metric_snapshots` is long-format.

### AMM — linear bonding curve with a mutable anchor

Chosen over LMSR and constant-product because it has an exact closed form in integer arithmetic (no float in a money path), a trivial inverse (slippage checkable before execution), and — critically — it **separates price-from-trading from price-from-fundamentals**, which is exactly the hybrid this product needs. LMSR tangles the two.

```
spot_price(a,t) = effective_anchor(a,t) + slope * net_supply(a)
slope_microcents = round(FAIR_VALUE_BASE_CENTS * 1_000_000 / AMM_DEPTH_SHARES)

buy  n from supply s:  cost_uc     = n*anchor_uc + slope_uc*(n*s + n*(n-1)//2)
                       cost_cents  = ceil(cost_uc / 1_000_000)        # buys round UP
sell n from supply s:  proceeds_uc = n*anchor_uc + slope_uc*(n*(s-n) + n*(n-1)//2)
                       proceeds    = floor(proceeds_uc / 1_000_000)   # sells round DOWN
fee = ceil(amount * TRADE_FEE_BPS / 10_000)                           # both legs
```

Rounding always favors the market, never the user. That asymmetry plus the fee makes every round trip strictly lossy.

**Position/exposure cap semantics (non-obvious, needed by Phase 4's trade route and Phase 6's leaderboard):**

- `MAX_USER_SUPPLY_SHARE_BPS` is a share of `AMM_DEPTH_SHARES` (a fixed depth constant → 400 shares at current defaults), **not** of an artist's live net supply. Supply-relative would be degenerate: the first buyer of any artist would instantly own 100% and be blocked.
- `MAX_ARTIST_EXPOSURE_BPS` is a user's post-trade position value in one artist as a fraction of their *total post-trade equity* (cash + all positions, marked to spot) — checked per trade, not per artist in isolation.
- A buy is **scout-qualified** iff `index_score_at_trade < SCOUT_DISCOVERY_INDEX_MAX` **and** `exec_price_cents < SCOUT_DISCOVERY_PRICE_CENTS` — AND, not OR, so buying a merely-dipped blue-chip doesn't count as scouting an unknown. Selling reduces `scout_shares` proportionally (floored), which resists gaming the Talent Scout leaderboard by buying qualified shares then topping up with a large disqualifying purchase before trimming a sliver on exit.

### Nightly reversion + glide

Integer microcents end to end — no float ever touches this path:

```
gap_cents = fair_value_cents - market_cents
raw       = abs(gap_cents) * REVERSION_RATE_BPS // 10_000                    # truncating division
cap       = max(REVERSION_MIN_MOVE_CENTS, market_cents * REVERSION_MAX_MOVE_BPS // 10_000)
move      = sign(gap_cents) * min(cap, max(REVERSION_MIN_MOVE_CENTS, raw))
anchor_target = anchor_current + move        # supply term untouched
```

`REVERSION_MIN_MOVE_CENTS` exists because truncating division alone makes any gap under ~6–7 cents produce a zero move forever — the floor is what makes convergence exact rather than asymptotic (I11). `anchor_current` above is always the **current interpolated effective anchor**, not the stale stored `anchor_cents`/`anchor_target_cents` endpoint — the cron fires late in practice (observed 2h late on day one in production), and starting a new glide from a stale endpoint would jump price discontinuously at reversion time, exactly what the glide exists to prevent.

Only the anchor moves — **no user's shares or cash change during reversion**, keeping the ledger clean and the job trivially idempotent.

The reversion is not applied as a step. It is stored as an interval and interpolated on read, in integer microcents:

```python
def effective_anchor_uc(anchor_uc, target_uc, glide_start, glide_end, now) -> int:
    if now >= glide_end or glide_end <= glide_start: return target_uc
    if now <= glide_start: return anchor_uc
    elapsed = (now - glide_start) // timedelta(microseconds=1)   # exact int, no float
    total   = (glide_end - glide_start) // timedelta(microseconds=1)
    return anchor_uc + (target_uc - anchor_uc) * elapsed // total
```

This is the fix for the dead-first-session problem: price moves *continuously*, so a user who buys at 2pm sees P&L change by 2:01pm and the chart is always alive. Zero extra infrastructure — no hourly cron, no websocket, no ticker. `REVERSION_GLIDE_HOURS = 24`, so each glide ends exactly as the next begins.

### Why the arbitrage dies

- 100 bps each leg → **2% round trip**, vs. `REVERSION_RATE_BPS = 1_500` (15%) capturing 15% of the gap per night — the gap must exceed roughly 13% of price just to break even for a bot that round-trips nightly.
- **Price impact self-limits**: buying the discount raises spot via the supply term, shrinking the gap being harvested. But this is not automatic protection against a *smart* bot — see below.
- `MAX_SLIPPAGE_BPS` forces large arbs to split into multiple trades, each paying full fee. A bot that instead spends its whole budget up to the slippage ceiling in one trade can self-erase its own edge in a single shot (Phase 2's simulation found exactly this failure mode in its own test harness — see "As built"); the real defense is that doing so is *worse* for the bot, not that the platform prevents it.
- Position caps stop a whale cornering the single biggest discount (see cap semantics above).

Invariant I14 verified this with two adversaries, not one: a naive nightly round-tripper (loses comfortably at every volatility tested) and a patient harvester that holds each position until its own gap converges (the real threat — profitable only once daily fair-value volatility exceeds roughly 0.5–1%/day; see "As built" and Phase 3's note on checking this against real data). Real edge must come from anticipating the *index* — i.e. scouting talent, which is the product.

### `core/config.py` values (as built)

```python
STARTING_BALANCE_CENTS      = 1_000_000   # $10,000
FAIR_VALUE_BASE_CENTS       = 1_000       # $10 at index 50
FAIR_VALUE_EXPONENT         = 1.6
FAIR_VALUE_MIN_CENTS        = 1           # floor so a score-1 artist still quotes a positive price
INDEX_MIN, INDEX_MAX        = 1.0, 100.0
GROWTH_WEIGHT               = 10.0
LEVEL_WEIGHT                = 6.0
Z_CLAMP                     = 3.0
ROBUST_Z_MIN_MAD            = 1e-6        # MAD floor; avoids divide-by-zero on a static cross-section
MIN_CROSS_SECTION_SIZE      = 10          # below this, skip the day rather than publish noise
EWMA_ALPHA                  = 0.4
GROWTH_LOOKBACK_DAYS        = 7
GROWTH_BASE_WINDOW_DAYS     = 2           # base snapshot accepted in [t-9, t-5]
MIN_SNAPSHOTS_TO_LIST       = 8
SIGNAL_WEIGHTS              = {"lastfm.listeners": 0.60, "lastfm.playcount": 0.40}
AMM_DEPTH_SHARES            = 2_000
TRADE_FEE_BPS               = 100         # retuned from 75 during Phase 2 -- see "As built"
MAX_SLIPPAGE_BPS            = 300
MAX_TRADE_SHARES            = 500
REVERSION_RATE_BPS          = 1_500       # integer bps, not a float rate
REVERSION_MAX_MOVE_BPS      = 1_000
REVERSION_MIN_MOVE_CENTS    = 1           # floor so a nonzero gap always converges to exactly 0
REVERSION_GLIDE_HOURS       = 24
MAX_ARTIST_EXPOSURE_BPS     = 2_500       # of a user's post-trade total equity
MAX_USER_SUPPLY_SHARE_BPS   = 2_000       # of AMM_DEPTH_SHARES (-> 400 shares), NOT of live net supply
SCOUT_DISCOVERY_INDEX_MAX   = 45.0
SCOUT_DISCOVERY_PRICE_CENTS = 1_000
SESSION_TTL_DAYS            = 90
MAGIC_LINK_TTL_MINUTES      = 15
```

**Done when:** invariants I1–I15 pass, ~90% coverage on `core/`, and `ax backtest` prints an index/price series from a CSV fixture.

### As built

All formulas above are what actually shipped (not what PLAN.md originally proposed pre-review — the differences: integer microcent glide math instead of float, bps-based reversion with a minimum-move floor, robust median/MAD z-scores on both the growth and level terms, and the two-bot I14 simulation instead of one). Full pure-core suite (`services/api/tests/core`, 74 tests) runs in ~5s with no DB and no network; `--cov` gives 99.65% on `ax.core` against the 90% gate.

Decisions and surprises worth carrying forward:

- **I14's simulation caught a real bot-design bug before it became a false pass.** An early "patient harvester" sized each entry up to the full `MAX_SLIPPAGE_BPS` budget in one trade. On this AMM's calibrated depth (`AMM_DEPTH_SHARES = 2_000`), that single trade's own price impact (~3%) is comparable to the ~2–3% gaps it was trying to harvest — the bot was erasing its own edge before the reversion ever got a chance to realize it, then eating the round-trip fee on top for a reliable, sizeable loss. Fixed by capping each entry's impact to a fraction of the currently observed gap, leaving room for the reversion itself to do the work. This is the sim behaving exactly as intended: it is supposed to find the best adversary the guardrails must beat, not the first bot that happens to lose. Caught by an implausible discontinuity in the printed break-even frontier (a jump from -0.3% to -72% between adjacent volatility values) — worth the same skepticism toward any future simulation whose output jumps around implausibly.
- **`TRADE_FEE_BPS` raised 75 → 100 bps.** With the sizing bug fixed, the patient harvester still cleared a small profit (+0.2–0.8% over 200 simulated days) at `sigma_daily = 0.5%`, the volatility regime the defaults are required to win. Per the tuning order the design review prescribed (fee first, then `REVERSION_RATE_BPS`), raising the fee alone flips every seed negative at that volatility without touching the reversion rate. Bot A's margins were untouched (a higher fee only makes round-tripping worse for it). The printed frontier (`test_sim_arb.py`) turns positive somewhere between `sigma_daily=0.5%` and `1%` — see Phase 3's note on checking this against real data.
- **The backtest fixture needed 8 "steady" artists, not 2–3, to make the population median land near 50.** The cross-sectional median is an order statistic of the *combined* growth+level score, not of either marginal term alone — each term can be separately well-centered by construction (robust z) while a single noisy draw still visibly shifts the population median, if the "normal" majority is too small relative to the deliberately extreme named archetypes (breakout, laggard, viral-spike). A larger steady population damps that sampling noise down to the documented ±1 (I9).
- **I9's "median ≈ 50" check needed a real day-by-day EWMA-carrying replay of the fixture**, not a single cold-start (`prev_ewma=None`) snapshot — a single-day check was off by more than the ±1 tolerance in early iterations. `tests/core/fixture_data.py`'s `replay()` does this; `ax backtest` (`cli.py`) does the same thing again independently, since production code cannot import test code.
- **The archetype assertions (breakout > 60, laggard < 45 with falling fair value, steady "hovering" strictly between the extremes, viral-spike spike-then-decay, gappy's window fallback, tiny's integer edges) landed in `test_index.py` alongside the fixture itself**, rather than waiting for the `ax backtest` CLI work — building the fixture-replay harness for I9 made them nearly free to add immediately, and this section's own "Done when" bullet already treats them as part of `ax backtest`'s verification, not a separate step.

---

## Phase 3 — Index + reversion on real data (~1–2 days)

`jobs/recompute.py`: read `metric_snapshots` → compute the cross-sectional index → write `index_snapshots` and `price_history` → set each artist's glide window. Appended to the nightly Action, after the snapshot step.

### Oracle manipulation — the attack the AMM guardrails do *not* cover

The fee/slippage/position-cap guardrails defend against arbitraging the *gap* between market price and fair value. They do nothing against someone who can move **fair value itself**. Last.fm has weak anti-fraud and scrobble bots are cheap, so the attack is:

> buy a small growth-tier artist → point scrobble bots at them → listener growth rises → index score rises → fair value rises → the glide walks market price up over 24h → sell into it.

Nothing anomalous happens from the system's perspective; the fundamentals genuinely "improved." This risk exists regardless of whether the repo is public — a public repo only shortens the attacker's discovery time from a week to an afternoon. **Do not treat repo privacy as a mitigation.**

### Mitigation (build in this phase)

1. **Ratio-divergence flag.** Bot scrobbles distort the listeners↔playcount relationship: playcount explodes while unique listeners barely move (a few accounts looping). Compute `playcount_growth − listeners_growth` per artist per day; flag anything more than ~3 MAD *above* the universe median — one-sided, since a large negative divergence (listeners outpacing playcount) isn't the bot-scrobble signature and flagging it would risk quarantining a genuinely breaking-out artist.
2. **Quarantine flagged artists.** A flagged artist's index score is **held at its previous value** — not zeroed, not deleted — until cleared. Nightly job writes the flag and reason into `index_snapshots.components`; the artist still trades, its fair value simply stops responding. Fail-safe: a false positive costs one day of staleness, a true positive costs the attacker their whole thesis.
3. **Percentile review queue.** Any artist whose index moves more than the 99th percentile of daily moves lands in a `flagged_artists` table for a manual look before affecting price. At 200 artists this is a two-minute daily task and doubles as data-quality monitoring.
4. **Already helping, for free:** `EWMA_ALPHA = 0.4` damps a one-day spike to ~40% of its raw effect, and `REVERSION_MAX_MOVE_BPS` caps how fast a manipulated score converts into price. Together these turn a one-night smash-and-grab into a multi-day operation with a visible footprint — which is what makes a daily review queue sufficient rather than token.

**The real long-term fix is the second signal.** Gaming Last.fm and YouTube simultaneously is dramatically harder than gaming one. This promotes the YouTube provider from "nice v2 upgrade" to part of the market-integrity story — pull it forward if Phase 3 shows Last.fm is noisy or if any manipulation appears.

### Checking real volatility against Phase 2's break-even frontier

Phase 2's I14 simulation (`services/api/tests/core/test_sim_arb.py`) showed a patient discount-buying bot stops reliably losing money somewhere between `sigma_daily = 0.5%` and `1%` of daily fair-value volatility — the printed frontier table gives the exact per-volatility mean returns from that run. Once a few weeks of real `index_snapshots` exist, compute the actual day-to-day volatility of `fair_value_cents` per artist and confirm the real series sits comfortably under that line. If it doesn't, the next levers — in order — are `EWMA_ALPHA` (down, more damping), `Z_CLAMP` (down, tighter outlier control), or `REVERSION_MAX_MOVE_BPS` (down, slower conversion into price); these already exist specifically to keep real fair-value swings much calmer than raw signal volatility. `TRADE_FEE_BPS` and `REVERSION_RATE_BPS` were already tuned against the simulation in Phase 2 and should not need to move again for this.

**Done when:** real fair-value curves exist for ~200 artists across the weeks Phase 1 has been accumulating (first moment the product's core claim is visibly true), and the divergence flag runs nightly with a reviewable queue.

### As built

`jobs/recompute.py` + `POST /internal/jobs/recompute` + `ax recompute`, mirroring Phase 1's snapshot job/endpoint/CLI shape exactly. Appended as a second step in `nightly-snapshot.yml`, after `snapshot`. Three decisions were confirmed with the user before implementation, since this is the mechanism defending against the one attack the AMM's own guardrails don't cover:

- **Both flag triggers (ratio-divergence and percentile-move) quarantine, sharing one mechanism.** Either one holds `index_score`/`fair_value_cents` at the previous value via a single `flagged_artists` row and a `quarantine` key in `index_snapshots.components`.
- **Clearing is human-in-the-loop, not auto-clear.** A quarantine persists across days — even ones where the trigger doesn't refire — until `flagged_artists.cleared_at` is set by hand. No clearing UI exists yet; direct DB access is the review tool, same as Phase 1's own verification approach. **Follow-up for a later phase: surface `flagged_artists` (open + recently-cleared) in an admin view instead of relying on direct DB access indefinitely.**
- **A first-eligible-day flag keeps the artist `warming_up`** rather than listing it with a suppressed price — there's no previous value to hold to, and publishing anything at all on a flagged first day is exactly the listing-day manipulation scenario the check exists to catch.

Decisions and surprises worth carrying forward:

- **A held day's entire `components` — not just the top-level score — is copied forward from the previous snapshot, with a `quarantine` audit key appended.** This freezes the per-signal EWMA carry state too, not only the published score: if EWMA continued absorbing a flagged day's inflated z-score at `EWMA_ALPHA=0.4`, the *next* day's fresh computation would already have partially absorbed the manipulation even while "held," quietly defeating the quarantine. The audit key still records what the real computation produced that day (`quarantine.would_have_computed`), so a reviewer — and `_effective_fair_value`-style test/monitoring code — can see the suppressed value without it ever entering the published series.
- **`PERCENTILE_MOVE_THRESHOLD`'s nearest-rank percentile always flags the single biggest mover at small population sizes.** At n=10–12 (this repo's test populations, and not far from being a real concern even at the full 200-artist universe on a quiet day), "beyond the 99th percentile of daily moves" is mathematically just "the largest value in the sample" — even when that value is driven by nothing but integer-rounding noise on an otherwise perfectly flat series. This isn't a bug (the check is working as specified), but it means percentile-move and ratio-divergence routinely co-fire on the same manipulated artist, and an entirely unrelated artist can occasionally trip percentile-move on an ordinary day. Worth watching once real 200-artist cross-sections accumulate — if it flags too often in practice, the fix is requiring a minimum absolute move alongside the percentile rank, not raising the percentile.
- **Listing and reversion share one idempotency story, but reversion is keyed off `index_snapshots` existence for `(artist_id, as_of_date)`, not off state on the `artists` row.** Listing is naturally idempotent (`listed_at IS NULL` only fires once). Reversion's idempotency check was originally keyed off whether `glide_start_at` already fell on `as_of_date` — which only worked by coincidence, since `glide_start_at` is always stamped from wall-clock `now`, never from `as_of_date`; a backdated `as_of` (a backfill) made that coincidence permanently false, so every retry re-derived and double-applied a new glide. Fixed by querying, once before the per-artist loop begins, which artists already have an `index_snapshots` row for exactly `as_of_date` — independent of `now` — and skipping reversion for any artist in that set.
- **Quarantine detection runs after that day's cross-sectional median/MAD have already been computed, so a caught manipulator's data has already influenced every other artist's z-scores for that day before being suppressed from publication.** `compute_index` produces one cross-section that every artist's growth/level z-scores are measured against; `_ratio_divergence_flags`/`_percentile_move_flags` then look at that output to decide who gets quarantined — too late to exclude the flagged artist from the statistics everyone else was scored against. Median/MAD robustness (the same mechanism behind I8) keeps one artist's distortion small at real population sizes, and the quarantine still suppresses that artist's own *published* score — but it does not undo its (small) contribution to that day's baseline for everyone else. A real fix is iterative outlier-exclusion (compute → detect → exclude → recompute the cross-section without the flagged artist → repeat until stable), which is a bigger structural change than warranted for Phase 3's population sizes and threat model. Accepted as a known, documented limitation; revisit if a real incident's blast radius on *other* artists' scores becomes visible in production.
- **`pick_base_snapshot` moved from a `cli.py`-private helper into `ax.core.index` as a public function.** Phase 2 had it duplicated once already (`cli.py` and the test-only `tests/core/fixture_data.py`, deliberately, since production code can't import test code) — but `jobs/recompute.py` is a second *production* consumer of the identical base-window rule, and nothing about it touches I/O, so triplicating it across two real job modules had no purity justification. `robust_z` similarly grew an optional `clamp` keyword (default `Z_CLAMP`, unchanged for every existing caller) so the ratio-divergence check can ask for an unclamped z-score — the score path's own ±3 clamp would otherwise make "beyond 3 MAD" indistinguishable from "clamped at the boundary."
- **The AMM's fixed listing slope (`FAIR_VALUE_BASE_CENTS * 1_000_000 / AMM_DEPTH_SHARES`) now has one real home, `ax.core.amm.listing_slope_uc()`.** It had been recomputed inline in Phase 2's `sim.py` and was about to be recomputed a third time here; both now call the same function.
- **Not yet verified against real accumulated data.** The Railway deploy (Phase 1) and this phase's implementation landed on the same UTC day, so production holds exactly one day of `metric_snapshots` — nowhere near `MIN_SNAPSHOTS_TO_LIST` (8), let alone the "weeks" this phase's own "Done when" and the real-volatility check above both need. `ax recompute` against the live dev database confirms the honest, correct behavior for that state (`eligible: 0`, no writes) rather than erroring — but the actual product claim (real fair values, some going down, divergence flag on real Last.fm noise) remains to be confirmed once enough nights have accumulated. Re-run the P3 verification steps below then; don't treat this phase as fully closed until that happens.
- **Test coverage:** 17 new integration tests against real Postgres (`test_recompute_job.py`, `test_internal_api_recompute.py`) covering warming-up gating, cross-section-too-small skip, listing, reversion, same-day idempotency for both, ratio-divergence and percentile-move quarantine (including that a matched proportional jump does *not* read as ratio-divergence), multi-day quarantine persistence and human-clearing, first-day-flag exclusion, and an end-to-end I8 check (a laggard's fair value falling while its own raw counts keep rising, through the real job and a real database rather than `compute_index` in isolation). 150 tests total, 99.67% coverage on `ax.core` against the 90% gate.

---

## Phase 4 — Auth, trading, portfolio API (~3–4 days)

Claim-a-username → session cookie → `STARTING_BALANCE_CENTS` `GRANT` ledger row, all in one DB transaction. Optional email attach + magic link recovery.

`POST /trades` quotes then executes under `SELECT ... FOR UPDATE` on the artist row, appending the ledger row and updating caches atomically. Plus `GET /portfolio`, `GET /artists`, `GET /artists/{slug}/history`, and `jobs/reconcile.py`.

**`jobs/recompute.py` must start taking the same `FOR UPDATE` lock on the artist row once this lands.** It currently runs lock-free — deliberately, per its own docstring — because no concurrent writer exists yet; that stops being true the moment `POST /trades` ships. Without the lock, a trade and a nightly reversion can race on `anchor_cents`/`anchor_target_cents`/`position_cache` for the same artist. Retrofit this in the same PR that adds the trade route, not after.

**`slope_microcents_per_share` is set per artist at listing time in this phase** — Phase 2's simulation validated the fixed-slope formula (`FAIR_VALUE_BASE_CENTS * 1_000_000 / AMM_DEPTH_SHARES`) only across a simulated `[50, 5_000]`-cent fair-value band with one platform-wide constant. Real listed artists will span a wider range (`FAIR_VALUE_MIN_CENTS = 1` cent up to whatever a top blue-chip scores). Confirm the fixed-slope assumption — and therefore the slippage/impact guardrails it feeds — holds reasonably at both ends of the real range before trusting it unmodified; if a score-1 artist or a runaway blue-chip behaves oddly under the AMM, a per-tier or per-artist slope is the fix, not a global constant change.

**Done when:** a shell script runs signup → quote → buy → portfolio → sell → portfolio and shows the expected fee-driven round-trip loss.

### As built

`api/routers/{auth,trades,artists,portfolio}.py`, `jobs/reconcile.py` + `/internal/jobs/reconcile` + `ax reconcile` (appended as a third nightly-workflow step, after `recompute`), `core/auth.py` (pure token hashing/TTL math), `providers/email.py` (Resend), and a new migration (`v_balances`/`v_positions` views, `magic_links.user_id`). 212 tests green, 99.68% coverage on `ax.core` against the 90% gate. Verified against the real dev DB, not just the integration suite: a manually-listed artist, signed up over real HTTP with cookies, round-tripped a 5-share buy/sell for a ~2.04% loss (102 cents on a 5,005-cent trade) — `TRADE_FEE_BPS = 100` on both legs plus the AMM's own slippage, exactly PLAN.md's "Done when" claim.

**Post-review fixes (same phase, before merge):** an 8-angle code review of the diff turned up eight real issues, all fixed and covered by a 213th test:
- `_replay_response`'s FEE-row lookup matched by `(artist_id, created_at)` equality — unsound whenever two of a user's trades share one DB transaction (every test session does, via the shared savepoint) — and could raise `MultipleResultsFound` on an idempotent retry. Fixed to match by `id` adjacency, the same rule `jobs/reconcile.py._true_positions` already used; regression test reproduces the collision against the old code before confirming the fix.
- `users.email` had no unique constraint despite `consume_magic_link` catching `IntegrityError` as its collision guard — the guard was dead code. Added `uq_users_email` to the Phase 4 migration.
- `jobs/reconcile.py` and `jobs/recompute.py` each looped over every user/artist taking a `FOR UPDATE` lock per iteration but committed only once at the end, so locks accumulated for the whole run instead of per-row — serializing `POST /trades` behind the entire nightly job rather than one row's worth of work. Both now commit per iteration; safe because both are already idempotent per-row.
- `execute_trade` computed the unlocked, best-effort `_other_positions_value_cents` exposure check *after* acquiring the balance_cache/artist locks, needlessly extending their hold time. Moved before lock acquisition.
- `artists.py` and `trades.py` each reimplemented "is this artist tradable" independently. Extracted to `db/market.py::is_tradable`, keeping each router's own status code (404 vs. 409) as a documented, deliberate per-endpoint choice rather than accidental drift.
- `auth.py`'s cookie-setting and cookie-clearing code independently recomputed the same `Secure`/`SameSite` pair; a browser only clears a cookie whose attributes match exactly. Extracted to one `_cookie_attrs` helper.
- `get_email_provider` built a fresh `httpx.Client` (and paid a fresh TLS handshake) on every request. Now injects a process-lifetime shared client into `ResendEmailProvider`.

Two decisions confirmed with the user before implementation, since both touch external services and secrets:

- **Magic-link delivery is a real ESP (Resend), not a logged link.** `RESEND_API_KEY` + `EMAIL_FROM_ADDRESS` (defaulting to Resend's zero-setup sandbox sender, which only delivers to the account owner's own inbox — swap in a verified domain before this needs to reach real users) join `SESSION_SECRET` et al. in `services/api/.env`. `providers/email.py` mirrors `providers/base.py`'s shape (a `Protocol` + one concrete implementation behind a FastAPI dependency) so auth tests substitute a fake and never touch the network or spend quota.

Decisions and surprises worth carrying forward:

- **`magic_links` gained a `user_id` column, a deliberate deviation from PLAN.md's literal `(id, email, token_hash, expires_at, used_at)` schema** — the same category of departure as `price_history`'s surrogate key. Without it, "attach a new email" would have to write `users.email` before the link is clicked (or resolve the target user by looking up `email` at consume time), which lets an attacker pre-claim a victim's real address on the attacker's own account; the victim's own later recovery request for that address would then log them into the attacker's account. Binding `user_id` at link-creation time — the current session for an attach, a lookup-by-email for a recovery request — means a link is always "log in as this specific user," and only consuming it ever writes `users.email`. See `db/models.py`'s `MagicLink` docstring.
- **`POST /trades` is two endpoints, not one.** PLAN.md's summary ("`POST /trades` quotes then executes") described the internal quote-then-commit shape, but the "Done when" script's own "signup → quote → buy" sequence needs a real preview step a client can call without committing anything — so `POST /trades/quote` (read-only, no lock) and `POST /trades` (the real thing, under lock) are separate routes. The quote is necessarily best-effort: state can move between preview and execution, same as any live market.
- **Lock order is `balance_cache` row, then the artist row — not just the artist row PLAN.md's retrofit note anticipated.** A single-lock design (artist only) leaves the overdraft check racy: a user trading two *different* artists concurrently could have both requests read the same pre-trade cash, both pass the check independently, and jointly overdraw the account, since neither trade's artist-row lock has anything to do with the other. Locking the user's own `balance_cache` row first closes this — two different users never contend on it (different rows) and the same user trading two different artists always contends on it (the same row), so a fixed order can't deadlock against the per-artist lock. `MAX_ARTIST_EXPOSURE_BPS`, in contrast, is checked against a best-effort, unlocked mark-to-market of the user's other positions — a soft guardrail intentionally not worth serializing a user's entire trading history behind.
- **`jobs/recompute.py`'s retrofit locks per-artist, right before that artist's own mutation** (`session.refresh(artist, with_for_update=True)`), not once for the whole ~200-artist cross-section — holding every row lock for the full computation would serialize trades against the nightly job for no reason, since only the subset actually being listed or reverted needs one. `net_supply` for the reversion gap calculation still comes from a batched pre-loop read, not a fresh query under that lock; a trade committing in the narrow window between them leaves that night's gap measurement one trade stale. Bounded and self-correcting (next night's reversion sees the true current gap) — the same category of accepted risk Phase 3 already documented for quarantine-baseline pollution, not a ledger-correctness issue.
- **`jobs/reconcile.py` replays the ledger through the real `ax.core.ledger.apply_buy`/`apply_sell`, not a SQL aggregate**, because `avg_cost_microcents` and `realized_pnl_cents` are order-dependent — `v_positions` (the migration's new view) covers only `SUM(share_delta)`, which is why it exists as a `shares`-only view rather than the fuller thing its name might suggest. `v_balances`, a plain `SUM(cash_delta_cents)`, has no such gap and is queried directly.
- **The first fee-pairing implementation was wrong, and the bug was real, not a test artifact — the test that caught it exercises a case production can hit too.** BUY/SELL rows were matched to their paired FEE row by `(artist_id, created_at)`, reasoning that both are written in the same DB transaction and therefore share the identical `now()` (CLAUDE.md rule 9). That's true, but *any two trades that happen to share a DB transaction* also share that same `now()` — which every trade in one integration test does (the shared-savepoint session fixture never really commits between calls), and which nothing rules out for a future batch-trading tool run inside one transaction. The `(artist_id, created_at)` dict silently let a later trade's FEE overwrite an earlier one's in the lookup, corrupting the replayed cost basis. Fixed by matching structurally instead: `write_entries` always writes a trade's FEE row immediately after its BUY/SELL leg in the same flush, so pairing by adjacency in `(created_at, id)` order is correct regardless of how many trades share a transaction. Caught by `test_no_drift_after_a_clean_trade_history` — a "nothing should be reported" test, which is exactly the shape of test worth trusting when it fails unexpectedly.
- **`slope_microcents_per_share` was already being set at listing time before this phase started** — Phase 3's `jobs/recompute.py._apply_market_state` does it on first listing, not something newly added here as PLAN.md's original phase text anticipated. Nothing to change; the fixed-slope-range caveat from that phase still stands unverified against a real wide fair-value spread, since production has no listed artists yet (see Phase 3's "As built").

### Deploying this phase (Railway + Resend)

Not yet deployed as of this writing — this is what deploying it requires, so the step isn't rediscovered from scratch later. `RESEND_API_KEY` and the verified sending domain are ready; setting the two Railway variables below and redeploying is what's left. Unlike Phase 1's Railway deploy notes above, there is no "as built" gotcha list here yet; add one when this actually ships.

**Resend account** — done:

1. Signed up at [resend.com](https://resend.com); the free tier is enough for this product's volume (transactional magic-link emails only, no marketing send).
2. `RESEND_API_KEY` created from the dashboard's **API Keys** page.
3. `artistexchange.chburrows.com` verified as a sending domain (SPF/DKIM), so delivery is not limited to the sandbox sender's "only the Resend account owner's own inbox" restriction. `EMAIL_FROM_ADDRESS` is `Artist Exchange <noreply@artistexchange.chburrows.com>`.

**New Railway variables on the `api` service** (in addition to everything Phase 1 already lists — `DATABASE_URL`, `LASTFM_API_KEY`, `LASTFM_SHARED_SECRET`, `INTERNAL_JOB_TOKEN`, `SESSION_SECRET`, `ENVIRONMENT`, `WEB_ORIGIN`):

| Variable | Value | Notes |
|---|---|---|
| `RESEND_API_KEY` | from the Resend dashboard | required — `get_email_provider` (`api/deps.py`) returns 503 on every `/auth/email` and `/auth/magic-link` call if this is unset, same fail-closed shape as a missing `LASTFM_API_KEY` |
| `EMAIL_FROM_ADDRESS` | `Artist Exchange <noreply@artistexchange.chburrows.com>` | verified domain — delivers to any address, not just the operator's own Resend account inbox |

`SESSION_SECRET` already exists from Phase 1's variable list but is genuinely load-bearing starting this phase: it's the HMAC key every session and magic-link token is hashed with (`ax.core.auth.hash_token`), not just a cookie-signing placeholder. Rotating it invalidates every live session and every unconsumed magic link — expected, not a bug, if it's ever intentionally rotated.

**No new GitHub Actions secrets.** `jobs/reconcile.py`'s nightly step (`.github/workflows/nightly-snapshot.yml`) reuses the existing `INTERNAL_JOB_TOKEN` and `API_BASE_URL`.

**`WEB_ORIGIN` is now also where magic links point** (`{WEB_ORIGIN}/auth/verify?token=...`), not just the CORS origin — that route doesn't exist until Phase 5 builds the SPA, so magic links are consumable via a direct `GET {API_BASE_URL}/auth/magic-link/consume?token=...` call in the meantime (what the Phase 4 verification steps below do), not by clicking the link as a real user would.

**Verifying the deploy**, once the variables above are set and the api service has redeployed:

```bash
# /auth/email requires a session cookie (it's "attach email to my account"),
# so use /auth/magic-link for an anonymous check — it takes no session and
# always replies 202 regardless of whether the address has an account.
# Should be 503 until RESEND_API_KEY is set, then 202.
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API_BASE_URL/auth/magic-link" \
  -H 'content-type: application/json' -d '{"email":"you@example.com"}'
```
A signup → email-attach → check-inbox → consume round trip against the deployed `API_BASE_URL` (mirroring the local curl sequence in the Phase 4 verification steps) is the real confirmation — with the domain verified, this can be run against any real inbox, not just the Resend account owner's own.

---

## Phase 5 — The SPA (~4–5 days)

Next.js static export (`output: 'export'`), TanStack Query, TypeScript client generated from the FastAPI OpenAPI schema. Artist list with tier filter; artist page with **the signature dual-line chart (market price solid, index fair value dashed)** plus the per-artist "not affiliated with or endorsed by" disclaimer; trade ticket with live quote and slippage warning; portfolio page.

**No artist photography in v1** — generated geometric avatars from a name hash. Sidesteps both image licensing and right-of-publicity exposure, and is cheaper to build.

**Done when:** a friend can sign up and trade in a browser.

---

## Phase 6 — Leaderboards, discovery, polish (~2–3 days)

Portfolio % return and Talent Scout leaderboards, as a materialized view refreshed by the nightly job — leaderboards are the one place staleness is genuinely fine. Discovery feeds ("Fastest growing under $10", "Biggest movers", "New listings"). Playwright E2E. Shareable portfolio card.

Talent Scout works because `transactions` denormalizes `index_score_at_trade` and `fair_value_cents_at_trade` at write time. Those values are immutable history — recomputing them later from snapshots would be both slow and wrong.

---

## Data model

Money is `BIGINT` cents everywhere. Floats appear only in `index_snapshots`, where the value genuinely is a statistic — never on a price or balance column.

```sql
users(id, username citext unique, email citext null, created_at)
sessions(id, user_id, token_hash bytea unique, expires_at, revoked_at)
magic_links(id, email, token_hash bytea unique, expires_at, used_at)

artists(id, slug, name, lastfm_mbid, lastfm_name,
        tier check in ('growth','blue_chip'), listed_at, delisted_at,
        -- the ONLY mutable market state; everything else append-only
        slope_microcents_per_share, anchor_cents, anchor_target_cents,
        glide_start_at, glide_end_at)

-- long-format: adding YouTube = inserting rows, zero migration
metric_snapshots(artist_id, as_of_date, source, metric_key, value bigint, fetched_at,
                 PK (artist_id, as_of_date, source, metric_key))

index_snapshots(artist_id, as_of_date, index_score float, fair_value_cents bigint,
                components jsonb, PK (artist_id, as_of_date))

-- surrogate PK, NOT (artist_id, at) — see "Why price_history has a surrogate key"
price_history(id bigserial, artist_id, at default clock_timestamp(),
              market_price_cents, fair_value_cents, net_supply,
              source check in ('trade','reversion','listing'), PK (id))

transactions(id bigserial, user_id, artist_id, kind check in ('GRANT','BUY','SELL','FEE'),
             cash_delta_cents bigint, share_delta bigint, exec_price_cents,
             index_score_at_trade, fair_value_cents_at_trade,
             idempotency_key unique null, created_at)          -- APPEND-ONLY

position_cache(user_id, artist_id, shares, avg_cost_microcents,
               realized_pnl_cents, scout_shares, PK (user_id, artist_id))
balance_cache(user_id PK, cash_cents, updated_at)

-- oracle-manipulation review queue (Phase 3)
flagged_artists(artist_id, as_of_date, reason text, detail jsonb,
                cleared_at timestamptz null, cleared_by text null,
                PK (artist_id, as_of_date))
```

Indexes: `transactions(user_id, created_at)`, `transactions(artist_id, created_at)`, `price_history(artist_id, at)`, `index_snapshots(as_of_date)`.

The `price_history` index is plain ascending, not `at DESC`: Postgres scans a btree backwards at the same cost, and an explicit `DESC` makes it an expression index that autogenerate cannot compare — reporting drift from `alembic check` on every run forever.

### Why `price_history` has a surrogate key

This is the one place the schema deliberately departs from the design above, decided in Phase 1 and verified against a live database. `PK (artist_id, at)` is unsafe for two independent reasons.

**A timestamp is not an identity.** Two price-moving events for one artist at the same instant violate the key, so a user's trade gets rejected for a reason that has nothing to do with their trade.

**`now()` is transaction-start time, not statement time**, and the `SELECT ... FOR UPDATE` artist lock is acquired *after* the transaction begins. So the order transactions start and the order they execute can differ, and two rows can be written with timestamps that invert their real execution order:

```
A: BEGIN (now() pinned to T1)          ... slow to reach the lock
B: BEGIN (now() pinned to T2, later)   ... reaches the lock first
B: acquires lock, trades, writes at=T2
A: acquires lock, trades, writes at=T1   <- executed second, timestamped first
```

Reproduced with two concurrent connections: reading `ORDER BY at` returned `net_supply` of **2 then 1** — supply decreasing across two consecutive buys, a state sequence that never happened. That series is what PriceChart plots, so the bug is directly visible in the signature UI.

The fix is both halves together:

1. **`id bigserial` primary key.** Collisions become structurally impossible, and `id` breaks ties in insertion order, so `ORDER BY at, id` is stable even for genuinely simultaneous events.
2. **`at` defaults to `clock_timestamp()`**, which reads the real clock at INSERT, after the lock. As a *column default* it is also what you get by omitting the column — the correct behavior is the one you get for free, rather than a rule every future insert site has to remember.

Locked in by `tests/test_price_history_schema.py`. **Never write `now()` into `price_history.at`** — it silently reintroduces both bugs.

### Deriving positions without being slow

1. **`v_balances` / `v_positions` SQL views are the definition of truth** (`SUM(cash_delta_cents) GROUP BY user_id`). Correct by construction, never on the hot path.
2. **`position_cache` / `balance_cache` are written in the same DB transaction as the ledger append**, under the artist row lock. O(1) per trade and per read. Because the write is atomic with the append, drift is structurally impossible absent a bug.
3. **`jobs/reconcile.py` runs nightly**, asserts cache == view for every user, and auto-repairs from the view on mismatch. This is what makes layer 2 safe to trust.

Rejected: materialized views (can't refresh per-trade; a stale portfolio right after your own trade is terrible UX) and compute-on-read (O(lifetime trades) per page load — fine in week 1, unusable by month 6).

Cost basis is **weighted average**, not FIFO lots — one integer field instead of a lot table and consumption logic, and entirely defensible in a play-money game.

---

## Invariants to unit-test

Hypothesis for I1–I7.

| # | Invariant |
|---|---|
| I1 | Cash conservation: `Σ cash_delta + fees_burned == Σ grants`, always |
| I2 | No round-trip profit: buy `n` then immediately sell `n` strictly loses, for all `n`, all supplies |
| I3 | Monotonicity: buys strictly raise spot, sells strictly lower it |
| I4 | Path independence: `cost(n)` == `n` sequential 1-share buys, up to non-negative rounding error |
| I5 | Curve symmetry: sell proceeds `s → s-n` == buy cost `s-n → s`, pre-fee, up to rounding direction |
| I6 | No negative supply, no overselling; supply is exactly `Σ share_delta` |
| I7 | Rounding always favors the house, for every operation |
| **I8** | **Cumulative-metric immunity: adding a constant to every artist's log-growth leaves every z-score (and therefore score) unchanged.** Proven three ways — bit-identical on dyadic inputs, identical to within a derived floating-point-error tolerance on arbitrary floats (see `test_index.py`), and behaviorally on realistic monotonically-increasing counts (a slower-than-median grower still ends up scoring below 50, fair value below the artist's own earlier value). The direct test that prices can fall — the most important test in the repo |
| I9 | Scores always in `[1,100]`; universe median ≈ 50 ± 1 on a realistic population (structural via the level term's robust z; the growth term's EWMA carry can still nudge it, hence the ±1 rather than exact) |
| I10 | Reversion moves strictly toward fair value, never past it, never beyond `REVERSION_MAX_MOVE_BPS` |
| I11 | Reversion is a contraction: iterating with fixed fair value converges monotonically to exactly zero gap (not asymptotically) |
| I12 | Snapshot idempotency: running twice for the same `(artist_id, as_of_date)` yields identical state, zero extra ledger rows |
| I13 | Any trade passing the slippage guard moves price ≤ `MAX_SLIPPAGE_BPS` |
| I14 | Anti-arb, tested against two adversaries over a simulated 200-artist/200-day market: a naive nightly round-tripper (must lose at every volatility tested) and a patient harvester that holds each position until its own gap converges (must not profit at `sigma_daily ≤ 0.5%`, the volatility real fair value is expected to stay under — see Phase 3's note on verifying this against real data) |
| I15 | Glide is continuous and monotone; equals `anchor` at start, `anchor_target` at end |

---

## Testing strategy

- **Unit — the bulk of the effort.** `core/` only, pytest + Hypothesis. No DB, no fixtures, fast. 90%+ coverage on `core/`, enforced as a build gate. This is where correctness actually lives.
- **Integration.** pytest + httpx `ASGITransport` against real Postgres (compose locally, GH Actions `services:` in CI), each test in an outer transaction rolled back at teardown. Cover: signup grants exactly once; concurrent buys on one artist don't corrupt supply (two threads contending on `FOR UPDATE`); snapshot idempotency against a live DB; and **`position_cache` == `v_positions` after a randomized 500-trade sequence** — the test that justifies the entire cache design.
- **E2E — deliberately thin, 4 specs.** Playwright: claim username → buy → see position; artist chart renders both series; leaderboard loads; magic-link recovery. E2E is for wiring, not logic.
- **Not tested:** component snapshots, CSS, most React. Deliberate.

---

## Local dev and faking history

`services/api/src/ax/cli.py` — the iteration-speed unlock:

- `ax seed-artists` — load the 200-artist seed.
- `ax backtest` *(built in Phase 2)* — replay a long-format metrics CSV through the real `compute_index` pipeline, carrying EWMA state day to day; defaults to the committed fixture, `--artist` filters to one slug's full series. No DB, no network — this is `core/` exercised against a CSV instead of `metric_snapshots`.
- `ax fake-history --days 120 --seed 42` — generate synthetic `metric_snapshots` via a GBM walk on listeners with a monotonic playcount derived from it, **so the fake data carries the same pathology as the real data** and genuinely exercises the index formula. Then run the real recompute job over each historical date in order. Deterministic under `--seed`.
- `ax simulate-trades --users 50 --days 120` — random agents trading through the real AMM and real ledger path, producing realistic price history, populated leaderboards, non-empty portfolios.
- `ax reset` — drop, migrate, and all of the above in one command, under 30 seconds.

Phase 5 UI work never waits on real history, charts have real shape from day one, and every local DB is reproducible. (I14's anti-arbitrage simulation, `services/api/tests/core/sim.py`, is a separate, self-contained seeded market generator used only by the test suite — it does not go through `ax fake-history`.)

The honest answer to cold start is still the phase ordering: Phase 1 ships in week one, so by the time Phase 5 lands there are 6+ weeks of *real* snapshots. **The fake-history tool is for dev speed and must never be used for production display.**

---

## CI

`.github/workflows/ci.yml`, on PR and push to main, parallel jobs:

- **api** — `ruff check` · `ruff format --check` · `mypy --strict src/ax/core` (looser elsewhere) · `pytest` with a Postgres service container · coverage gate on `core/`.
- **migrations** — `alembic upgrade head` on a clean DB, then `alembic check`. Fails if models drift from migrations, the most common source of "works locally, breaks in prod" in a SQLAlchemy repo.
- **web** — `pnpm lint` · `tsc --noEmit` · `pnpm build` · Playwright against the compose stack.
- **purity** — the AST check that `core/` imports nothing beyond stdlib.
- **docker** — build both Dockerfiles, so a Railway deploy is never the first time an image gets built.

`nightly-snapshot.yml`: `cron: '0 7 * * *'` (after Last.fm's daily settle), `workflow_dispatch` enabled for manual re-runs, `curl -f -H "Authorization: Bearer ${{ secrets.INTERNAL_JOB_TOKEN }}"`, retry 3× with backoff, failure notification. Manual re-runs are always safe because of the idempotent primary key.

---

## Verification

**Per phase, in order:**

- **P0** — `docker compose up -d && pnpm install && uv sync`; CI green. Confirm `git log -p` shows `.gitignore` as the first commit and `secrets.env` is absent from `git ls-files`. Confirm `CLAUDE.md`, `PLAN.md`, and `SETUP.md` are committed, and that `CONCEPT.md` has been revised to move shorting/tournaments to the deferred section and to record the index formula, guardrail constants, and glide mechanism decided in this session.
- **P1** — Trigger the Action manually via `workflow_dispatch`; confirm `metric_snapshots` gains ~200 rows. Run it twice and confirm the row count is unchanged (I12 in production). Check again 24h later, unattended.
- **P2** — `uv run pytest` green, coverage ≥90% on `core/`. Run `ax backtest` and eyeball the index series for plausibility — do known-growing artists actually score higher?
- **P3** — Query `index_snapshots` for real dates; plot fair value for a few artists and sanity-check direction against what you know about those artists. **Confirm some artists' fair values went DOWN** — that's the real-world I8 check.
- **P4** — Run the signup → buy → portfolio → sell script; verify the round trip loses ~2% (`TRADE_FEE_BPS = 100` each leg, retuned in Phase 2) and `SELECT * FROM v_balances` matches `balance_cache`.
- **P5** — Use `/run` to launch the app and click through it; then have one real friend sign up and trade unattended, and watch where they hesitate.
- **P6** — `pnpm e2e` green; leaderboards populate from `ax simulate-trades` data.

**Ongoing, before each commit:** `/verify` for behavior, `/code-review` on the diff. Commit at every phase boundary.

---

## Deferred, with the seams already in place

- **Shorting** — `transactions.share_delta` is signed, so negative positions are representable without a schema change.
- **YouTube signal** — one `SIGNAL_WEIGHTS` entry plus a `providers/` class; `metric_snapshots` is already long-format.
- **Tournaments** — a filtered leaderboard over a date range with a fresh `GRANT`; the ledger already supports it.
- **Chartmetric/Soundcharts** — same provider seam as YouTube.
