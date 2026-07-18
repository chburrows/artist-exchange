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
| `ENVIRONMENT` | `local` \| `production` | |

### `apps/web/.env.local`

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` locally; the Railway API URL in production |

**Never** put a secret in a `NEXT_PUBLIC_*` variable — those are compiled into the static bundle and are fully public.

## Railway deploy

Three services in one project:

1. **Postgres** — add the managed Postgres plugin. It provides `DATABASE_URL`.
2. **api** — deploy from `services/api/Dockerfile`. Set `LASTFM_API_KEY`, `LASTFM_SHARED_SECRET`, `INTERNAL_JOB_TOKEN`, `SESSION_SECRET`, `ENVIRONMENT=production`. Reference `DATABASE_URL` from the Postgres service. Run `alembic upgrade head` as the release command.
3. **web** — deploy from `apps/web/Dockerfile`, with `NEXT_PUBLIC_API_BASE_URL` pointing at the api service's public URL.

Both services deploy on push to `main`.

## GitHub Actions secrets

Set via `gh secret set <NAME>`:

| Secret | Value |
|---|---|
| `INTERNAL_JOB_TOKEN` | must match the api service's value exactly |
| `API_BASE_URL` | the Railway api public URL |

The nightly workflow POSTs to `$API_BASE_URL/internal/jobs/snapshot` with that bearer token. It has `workflow_dispatch` enabled, so you can trigger it by hand from the Actions tab — safe at any time, because the job is idempotent on `(artist_id, as_of_date)`.

## Verifying the setup

```bash
uv run pytest                                    # should be green
docker compose exec postgres psql -U postgres artist_exchange -c \
  "SELECT count(*) FROM metric_snapshots;"       # non-zero after `ax reset`
pnpm dev                                         # http://localhost:3000
```
