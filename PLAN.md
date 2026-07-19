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
- [ ] **Phase 2** — Pure core + invariant tests
- [ ] **Phase 3** — Index + reversion on real data
- [ ] **Phase 4** — Auth, trading, portfolio API
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

> **Execution spec: [`PHASE2.md`](./PHASE2.md).** Written after a full design review;
> where it and this section disagree (integer glide math, reversion in bps, robust
> level z, I8/I14 test formulations, cap semantics), PHASE2.md is authoritative.

`services/api/src/ax/core/{config,money,amm,index,ledger}.py`. No SQLAlchemy, no FastAPI, no I/O, no `datetime.now()` — time is always a parameter. Purity is enforced mechanically by `tests/test_core_purity.py`, which walks the ASTs and asserts no import outside stdlib. That test is the cheapest guard against the core rotting into DB-coupled mess.

### Index Score

Designed so that **monotonic inputs cannot produce monotonic prices**. `playcount` only ever rises; if the index were built on levels, nothing would ever fall and every position would win. Every input is therefore a cross-sectional z-score of a *growth rate* — if the whole universe inflates, every score is unchanged.

```
g_s(a,t)   = ln(V[a,t] + 1) - ln(V[a,t-7] + 1)              # log growth per signal
z_s(a,t)   = clamp(0.6745 * (g_s - median_s) / MAD_s, ±Z_CLAMP)   # median/MAD, not mean/stdev
Z_s(a,t)   = EWMA_ALPHA * z_s + (1 - EWMA_ALPHA) * Z_s(a,t-1)     # smooth lumpy updates
G(a,t)     = Σ SIGNAL_WEIGHTS[s] * Z_s(a,t)                       # weight registry
S(a,t)     = clamp(zscore(ln(listeners)), ±Z_CLAMP)               # slow size term
IndexScore = clamp(50 + GROWTH_WEIGHT*G + LEVEL_WEIGHT*S, 1, 100)
FairValue  = round(FAIR_VALUE_BASE_CENTS * (IndexScore/50) ** FAIR_VALUE_EXPONENT)
```

Log growth (not percent) is symmetric and immune to small-denominator blowups across a 4-order-of-magnitude size range. Median/MAD stops one viral artist compressing everyone else. Listeners is weighted above playcount because playcount is inflated by superfans re-scrobbling, whereas listeners measures breadth of adoption — which is what "breaking out" actually means.

Missing `t-7` snapshot → fall back to nearest in `[t-9, t-5]`, adjust for actual day gap. None available → artist is `warming_up`, excluded from the cross-section and from listing.

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

### Nightly reversion + glide

```
gap    = fair_value - market_now
move   = clamp(round(gap * REVERSION_RATE), ±round(market_now * REVERSION_MAX_MOVE_BPS/10_000))
anchor_target = anchor_current + move        # supply term untouched
```

Only the anchor moves — **no user's shares or cash change during reversion**, keeping the ledger clean and the job trivially idempotent.

The reversion is not applied as a step. It is stored as an interval and interpolated on read:

```python
def effective_anchor(artist, now) -> int:
    if now >= artist.glide_end_at: return artist.anchor_target_cents
    frac = (now - artist.glide_start_at) / (artist.glide_end_at - artist.glide_start_at)
    return artist.anchor_cents + (artist.anchor_target_cents - artist.anchor_cents) * frac
```

This is the fix for the dead-first-session problem: price moves *continuously*, so a user who buys at 2pm sees P&L change by 2:01pm and the chart is always alive. Zero extra infrastructure — no hourly cron, no websocket, no ticker. `REVERSION_GLIDE_HOURS = 24`, so each glide ends exactly as the next begins. Twelve of the highest-leverage lines in the codebase.

### Why the arbitrage dies

- 75 bps each leg → **1.5% round trip**, vs. `REVERSION_RATE = 0.15` capturing 15% of the gap per night. The gap must exceed ~10% of price just to break even.
- **Price impact self-limits**: buying the discount raises spot via the supply term, shrinking the gap being harvested.
- `MAX_SLIPPAGE_BPS` forces large arbs to split into multiple trades, each paying full fee.
- Position caps stop a whale cornering the single biggest discount.

Invariant I14 tests exactly this as a 200-day simulation. Real edge must come from anticipating the *index* — i.e. scouting talent, which is the product.

### `core/config.py` starting values

```python
STARTING_BALANCE_CENTS      = 1_000_000   # $10,000
FAIR_VALUE_BASE_CENTS       = 1_000       # $10 at index 50
FAIR_VALUE_EXPONENT         = 1.6
INDEX_MIN, INDEX_MAX        = 1.0, 100.0
GROWTH_WEIGHT               = 10.0
LEVEL_WEIGHT                = 6.0
Z_CLAMP                     = 3.0
EWMA_ALPHA                  = 0.4
GROWTH_LOOKBACK_DAYS        = 7
MIN_SNAPSHOTS_TO_LIST       = 8
SIGNAL_WEIGHTS              = {"lastfm.listeners": 0.60, "lastfm.playcount": 0.40}
AMM_DEPTH_SHARES            = 2_000
TRADE_FEE_BPS               = 75
MAX_SLIPPAGE_BPS            = 300
MAX_TRADE_SHARES            = 500
REVERSION_RATE              = 0.15
REVERSION_MAX_MOVE_BPS      = 1_000
REVERSION_GLIDE_HOURS       = 24
MAX_ARTIST_EXPOSURE_BPS     = 2_500
MAX_USER_SUPPLY_SHARE_BPS   = 2_000
SCOUT_DISCOVERY_INDEX_MAX   = 45.0
SCOUT_DISCOVERY_PRICE_CENTS = 1_000
SESSION_TTL_DAYS            = 90
MAGIC_LINK_TTL_MINUTES      = 15
```

**Done when:** invariants I1–I15 pass, ~90% coverage on `core/`, and `ax backtest` prints an index/price series from a CSV fixture.

---

## Phase 3 — Index + reversion on real data (~1–2 days)

`jobs/recompute.py`: read `metric_snapshots` → compute the cross-sectional index → write `index_snapshots` and `price_history` → set each artist's glide window. Appended to the nightly Action, after the snapshot step.

### Oracle manipulation — the attack the AMM guardrails do *not* cover

The fee/slippage/position-cap guardrails defend against arbitraging the *gap* between market price and fair value. They do nothing against someone who can move **fair value itself**. Last.fm has weak anti-fraud and scrobble bots are cheap, so the attack is:

> buy a small growth-tier artist → point scrobble bots at them → listener growth rises → index score rises → fair value rises → the glide walks market price up over 24h → sell into it.

Nothing anomalous happens from the system's perspective; the fundamentals genuinely "improved." This risk exists regardless of whether the repo is public — a public repo only shortens the attacker's discovery time from a week to an afternoon. **Do not treat repo privacy as a mitigation.**

### Mitigation (build in this phase)

1. **Ratio-divergence flag.** Bot scrobbles distort the listeners↔playcount relationship: playcount explodes while unique listeners barely move (a few accounts looping). Compute `playcount_growth − listeners_growth` per artist per day; flag anything beyond ~3 MAD from the universe.
2. **Quarantine flagged artists.** A flagged artist's index score is **held at its previous value** — not zeroed, not deleted — until cleared. Nightly job writes the flag and reason into `index_snapshots.components`; the artist still trades, its fair value simply stops responding. Fail-safe: a false positive costs one day of staleness, a true positive costs the attacker their whole thesis.
3. **Percentile review queue.** Any artist whose index moves more than the 99th percentile of daily moves lands in a `flagged_artists` table for a manual look before affecting price. At 200 artists this is a two-minute daily task and doubles as data-quality monitoring.
4. **Already helping, for free:** `EWMA_ALPHA = 0.4` damps a one-day spike to ~40% of its raw effect, and `REVERSION_MAX_MOVE_BPS` caps how fast a manipulated score converts into price. Together these turn a one-night smash-and-grab into a multi-day operation with a visible footprint — which is what makes a daily review queue sufficient rather than token.

**The real long-term fix is the second signal.** Gaming Last.fm and YouTube simultaneously is dramatically harder than gaming one. This promotes the YouTube provider from "nice v2 upgrade" to part of the market-integrity story — pull it forward if Phase 3 shows Last.fm is noisy or if any manipulation appears.

**Done when:** real fair-value curves exist for ~200 artists across the weeks Phase 1 has been accumulating (first moment the product's core claim is visibly true), and the divergence flag runs nightly with a reviewable queue.

---

## Phase 4 — Auth, trading, portfolio API (~3–4 days)

Claim-a-username → session cookie → `STARTING_BALANCE_CENTS` `GRANT` ledger row, all in one DB transaction. Optional email attach + magic link recovery.

`POST /trades` quotes then executes under `SELECT ... FOR UPDATE` on the artist row, appending the ledger row and updating caches atomically. Plus `GET /portfolio`, `GET /artists`, `GET /artists/{slug}/history`, and `jobs/reconcile.py`.

**Done when:** a shell script runs signup → quote → buy → portfolio → sell → portfolio and shows the expected fee-driven round-trip loss.

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
| **I8** | **Cumulative-metric immunity: adding a constant to every artist's log-growth leaves every index score bit-identical.** The direct test that prices can fall — the most important test in the repo |
| I9 | Scores always in `[1,100]`; universe median ≈ 50 ± 1 |
| I10 | Reversion moves strictly toward fair value, never past it, never beyond `REVERSION_MAX_MOVE_BPS` |
| I11 | Reversion is a contraction: iterating with fixed fair value converges monotonically |
| I12 | Snapshot idempotency: running twice for the same `(artist_id, as_of_date)` yields identical state, zero extra ledger rows |
| I13 | Any trade passing the slippage guard moves price ≤ `MAX_SLIPPAGE_BPS` |
| I14 | Anti-arb: a bot buying the 10 biggest discounts / selling the 10 biggest premiums nightly has negative expected return over 200 simulated days |
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
- `ax fake-history --days 120 --seed 42` — generate synthetic `metric_snapshots` via a GBM walk on listeners with a monotonic playcount derived from it, **so the fake data carries the same pathology as the real data** and genuinely exercises the index formula. Then run the real recompute job over each historical date in order. Deterministic under `--seed`.
- `ax simulate-trades --users 50 --days 120` — random agents trading through the real AMM and real ledger path, producing realistic price history, populated leaderboards, non-empty portfolios.
- `ax reset` — drop, migrate, and all of the above in one command, under 30 seconds.

Phase 5 UI work never waits on real history, charts have real shape from day one, and every local DB is reproducible. The `--seed 42` fixtures also feed the I14 simulation.

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
- **P4** — Run the signup → buy → portfolio → sell script; verify the round trip loses ~1.5% and `SELECT * FROM v_balances` matches `balance_cache`.
- **P5** — Use `/run` to launch the app and click through it; then have one real friend sign up and trade unattended, and watch where they hesitate.
- **P6** — `pnpm e2e` green; leaderboards populate from `ax simulate-trades` data.

**Ongoing, before each commit:** `/verify` for behavior, `/code-review` on the diff. Commit at every phase boundary.

---

## Deferred, with the seams already in place

- **Shorting** — `transactions.share_delta` is signed, so negative positions are representable without a schema change.
- **YouTube signal** — one `SIGNAL_WEIGHTS` entry plus a `providers/` class; `metric_snapshots` is already long-format.
- **Tournaments** — a filtered leaderboard over a date range with a fresh `GRANT`; the ledger already supports it.
- **Chartmetric/Soundcharts** — same provider seam as YouTube.
