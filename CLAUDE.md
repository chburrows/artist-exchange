# CLAUDE.md — Artist Exchange

## What this is

A play-money market where users buy and sell "shares" of musical artists, betting on whether their popularity will rise. Each artist has an **Index Score** derived from real public data (Last.fm listener/scrobble counts, snapshotted nightly by us) and a **Market Price** set by user trading through an AMM. Nightly, the market price glides part of the way toward the index-derived fair value — so being early to a genuinely rising artist is rewarded. That "talent scout" mechanic is the product.

- **`CONCEPT.md`** is product truth — what we're building and why.
- **`PLAN.md`** is build truth — phases, schema, formulas, invariants. Read it before starting any phase.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js, static export (`output: 'export'`) — a true SPA, no SSR data path |
| Backend | FastAPI + SQLAlchemy 2.0 (typed) + Alembic |
| Database | Postgres 16 |
| Hosting | Railway (web + api + managed Postgres), Dockerfile-first |
| Jobs | GitHub Actions cron → POST to a protected internal endpoint |
| Tooling | `uv` (Python), `pnpm` (Node) |

Python targets **3.12** to match the container. The WSL host has 3.10 — always go through `uv`, never bare `python3`.

## Commands

```bash
docker compose up -d          # Postgres + adminer
uv sync                       # Python deps
pnpm install                  # Node deps

uv run pytest                 # all Python tests
uv run pytest tests/core      # the fast, pure unit tests
uv run alembic upgrade head   # apply migrations
uv run alembic check          # fail if models drift from migrations

uv run ax reset               # drop + migrate + seed + fake history + simulated trades (<30s)
uv run ax seed-artists        # load the curated artist universe
uv run ax fake-history --days 120 --seed 42
uv run ax simulate-trades --users 50 --days 120
uv run ax backtest            # print an index/price series from fixtures

pnpm dev                      # Next.js dev server
pnpm build                    # static export
pnpm e2e                      # Playwright
```

No `psql` on the host — use `docker compose exec postgres psql -U postgres artist_exchange`.

## Layout

```
apps/web/                 Next.js SPA (static export)
  components/             PriceChart is the signature UI — market price vs fair value
  lib/api.ts              generated from the FastAPI OpenAPI schema; do not hand-edit
services/api/src/ax/
  core/                   PURE math: config, money, amm, index, ledger
  db/                     SQLAlchemy models + session
  api/routers/            HTTP layer
  jobs/                   snapshot, recompute, reconcile
  providers/              external data sources behind a shared protocol
  cli.py                  seed / fake-history / simulate-trades / reset / backtest
```

## Non-negotiable rules

These are rules, not preferences. Violating one is a bug even if tests pass.

1. **Money is integer cents (`BIGINT`).** Never float, never `NUMERIC`, on any price, balance, or fee. Sub-cent intermediate math uses micro-cents (integer), divided down at the boundary.
2. **`transactions` is append-only.** No `UPDATE`, no `DELETE`, ever. Corrections are new compensating rows.
3. **`core/` is pure.** No SQLAlchemy, no FastAPI, no I/O, no `datetime.now()` — time is always a parameter. Enforced mechanically by `tests/test_core_purity.py`, which walks the ASTs and rejects any import outside stdlib.
4. **All tunable economics live in `core/config.py`.** Never inline a magic number in `amm.py` or `index.py`. These constants get tuned against live data; they must be findable in one place.
5. **Every index input is a cross-sectional z-score of a growth rate, never a level.** See rule-behind-the-rule in Gotchas.
6. **Rounding always favors the market.** Buys round up, sells round down. Every round trip must be strictly lossy.
7. **Job endpoints are idempotent** on `(artist_id, as_of_date)`. Re-running a job must never double-write or append a ledger row.
8. **Balances and positions are derived from the ledger.** `v_balances` / `v_positions` are the definition of truth; `balance_cache` / `position_cache` are written in the *same DB transaction* as the ledger append, under `SELECT ... FOR UPDATE` on the artist row. Never update a cache independently.

## Gotchas

- **Last.fm `playcount` is monotonic — it only ever goes up.** If the index were built on levels, no price would ever fall and every position would win. This is why rule 5 exists, and why invariant **I8** (adding a constant to every artist's log-growth leaves every score bit-identical) is the most important test in the repo. If I8 breaks, the product is broken.
- **Last.fm skews older, more indie/rock, more Western** — which makes it weakest at detecting exactly the TikTok-driven breakout artists in our growth tier. A YouTube signal is the planned second input; `metric_snapshots` is long-format and `SIGNAL_WEIGHTS` is a registry specifically so adding it is one dict entry plus a provider class, with no migration.
- **The nightly reversion is a glide, not a step.** `effective_anchor()` interpolates between `anchor_cents` and `anchor_target_cents` over 24h, so price moves continuously and a user's P&L changes minutes after they trade. Do not "simplify" this into a discrete nightly jump — it is the fix for the dead-first-session problem.
- **Reversion moves only the anchor.** No user's shares or cash change during reversion. This keeps the ledger clean and makes the job trivially idempotent.
- **`ax fake-history` is dev-only.** It must never be run against production or surfaced as real data.
- **Talent Scout depends on denormalized columns.** `transactions.index_score_at_trade` and `fair_value_cents_at_trade` are written at trade time and are immutable history — recomputing them later from snapshots would be both slow and wrong.
- **Right of publicity**: every artist page carries a "not affiliated with or endorsed by" disclaimer, and v1 uses generated geometric avatars, not artist photography.

## Conventions

- Commit at every phase boundary; keep commits small enough to be an undo button.
- Run `/verify` before nontrivial commits — exercise the behavior, don't just run tests.
- Run `/code-review` on the diff before committing.
- Decisions that matter go in `CLAUDE.md`, `PLAN.md`, or a commit message — never only in a chat session.
- New economic constants go in `core/config.py` with a comment explaining what tuning it up or down does.
