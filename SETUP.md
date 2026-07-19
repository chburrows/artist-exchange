# Setup

## Prerequisites

| Tool | Required | Notes |
|---|---|---|
| Docker | 24+ with Compose v2 | Postgres runs in Compose; the apps run on the host for speed |
| Node | 20+ | |
| pnpm | 10+ | `corepack enable pnpm` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| gh | any | for CI and secret management |

Python 3.12 is installed and managed by `uv` — you do not need it on the host. Do not use the system `python3` (3.10 on WSL); type behavior and `datetime.UTC` differ from the container.

## First run

```bash
git clone <repo> && cd artist-exchange
docker compose up -d                  # Postgres on :5432, adminer on :8080
uv sync                               # Python 3.12 + deps
pnpm install
cp services/api/.env.example services/api/.env
cp apps/web/.env.example apps/web/.env.local
# fill in the values below, then:
uv run ax reset                       # migrate + seed + fake history + simulated trades
```

`ax reset` takes under 30 seconds and leaves you with ~200 artists, 120 days of synthetic history, and populated portfolios and leaderboards. You can build UI against it immediately without waiting for real snapshots to accumulate.

## Secrets

`secrets.env` at the repo root is a **personal reference file only**. It is gitignored, and the application never reads it. Copy values out of it by hand into the two `.env` files below.

### `services/api/.env`

| Key | Source | Notes |
|---|---|---|
| `DATABASE_URL` | local: `postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange` | Railway injects this in production |
| `LASTFM_API_KEY` | `secrets.env` | |
| `LASTFM_SHARED_SECRET` | `secrets.env` | not needed for `artist.getInfo`, but keep them together |
| `INTERNAL_JOB_TOKEN` | generate: `openssl rand -hex 32` | bearer token for `/internal/jobs/*` |
| `SESSION_SECRET` | generate: `openssl rand -hex 32` | signs session cookies |
| `ENVIRONMENT` | `local` \| `test` \| `production` | |
| `WEB_ORIGIN` | `http://localhost:3000` locally; the Railway web URL in production | the single allowed CORS origin |

### `apps/web/.env.local`

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` locally; the Railway API URL in production |

**Never** put a secret in a `NEXT_PUBLIC_*` variable — those are compiled into the static bundle and are fully public.

## Railway deploy

As of Phase 1 only **Postgres** and **api** need to exist. The `web`
service arrives with Phase 5.

The Docker **build context is the repo root**, not `services/api` — the uv
workspace root (`pyproject.toml`, `uv.lock`) and `alembic.ini` live there.
`services/api/railway.json` already encodes this, along with the release
command and health check, so most of the setup below is just secrets.

### 1. Postgres

Add the managed Postgres plugin to the project. It exposes a
`DATABASE_URL` that the api service references — do not copy the value,
reference it, so a credential rotation does not silently break the api.

### 2. api

Create a service from this GitHub repo. Railway reads
`services/api/railway.json`, which sets:

- **Dockerfile**: `services/api/Dockerfile`
- **Release command**: `alembic upgrade head` — migrations run on every
  deploy, before the new container takes traffic
- **Health check**: `/health` (liveness only; it deliberately does not
  touch the database, so a brief DB blip cannot trigger a restart loop)

Set the root directory to `/` (the repo root) so the build context is
right, then set these variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | reference the Postgres service's variable |
| `LASTFM_API_KEY` | from `secrets.env` |
| `LASTFM_SHARED_SECRET` | from `secrets.env` |
| `INTERNAL_JOB_TOKEN` | `openssl rand -hex 32` — keep this value, GitHub needs it too |
| `SESSION_SECRET` | `openssl rand -hex 32` |
| `ENVIRONMENT` | `production` |
| `WEB_ORIGIN` | the web URL once Phase 5 deploys; until then anything |

Then generate a public domain for the service and note the URL.

### 3. Seed the production universe

The artist universe is a one-time load. From the Railway service shell,
or locally with `DATABASE_URL` pointed at production:

```bash
uv run ax seed-artists
```

Re-running is safe — it matches on `slug` and updates identity fields
only, never market state.

## GitHub Actions secrets

```bash
gh secret set INTERNAL_JOB_TOKEN     # exactly the api service's value
gh secret set API_BASE_URL           # e.g. https://api-production-xxxx.up.railway.app
```

The nightly workflow POSTs to `$API_BASE_URL/internal/jobs/snapshot` with
that bearer token at 07:00 UTC. It has `workflow_dispatch` enabled, so you
can trigger it by hand from the Actions tab, optionally passing an `as_of`
date to backfill or re-run a specific night.

**Manual re-runs are always safe** — the job is idempotent on
`(artist_id, as_of_date)`, verified locally against the live API and
covered by the I12 tests.

## Verifying the deploy

```bash
curl -fsS "$API_BASE_URL/health"

# Should 401 — the endpoint is public, the token is the only guard.
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API_BASE_URL/internal/jobs/snapshot"

# Trigger a real run and watch the summary.
gh workflow run nightly-snapshot.yml
gh run watch
```

Then confirm the data landed, and confirm a second run does not duplicate
it:

```sql
SELECT as_of_date, count(*), count(DISTINCT artist_id)
FROM metric_snapshots GROUP BY as_of_date ORDER BY as_of_date;
```

A full run is ~200 artists / 400 rows and takes about 50 seconds. Run the
workflow twice and confirm the row count is **unchanged** — that is
invariant I12 observed in production.

**Then check again 24 hours later, unattended.** Phase 1 is not done until
the cron has fired on its own: everything downstream depends on history
that only accumulates in wall-clock time, and Last.fm has no history API
to backfill a missed night from.

## Verifying the setup

```bash
uv run pytest                                    # should be green
docker compose exec postgres psql -U postgres artist_exchange -c \
  "SELECT count(*) FROM metric_snapshots;"       # non-zero after `ax reset`
pnpm dev                                         # http://localhost:3000
```
