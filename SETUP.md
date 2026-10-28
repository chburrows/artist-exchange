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
| `RESEND_API_KEY` | [resend.com](https://resend.com) dashboard → API Keys | magic-link email delivery |
| `EMAIL_FROM_ADDRESS` | `Artist Exchange <noreply@artistexchange.chburrows.com>` | domain is verified in Resend (SPF/DKIM), so this delivers to any address — no sandbox restriction |
| `INTERNAL_JOB_TOKEN` | generate: `openssl rand -hex 32` | bearer token for `/internal/jobs/*` |
| `SESSION_SECRET` | generate: `openssl rand -hex 32` | HMAC key for session/magic-link token hashing (`ax.core.auth.hash_token`) |
| `ENVIRONMENT` | `local` \| `test` \| `production` | also controls the session cookie's `Secure`/`SameSite` flags — see `api/routers/auth.py` |
| `WEB_ORIGIN` | `http://localhost:3000` locally; the Railway web URL in production | the single allowed CORS origin, and the base URL magic links point at |

### `apps/web/.env.local`

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` locally; the Railway API URL in production |

**Never** put a secret in a `NEXT_PUBLIC_*` variable — those are compiled into the static bundle and are fully public.

## Railway deploy

Three services: **Postgres**, **api**, **web**.

The Docker **build context is the repo root** for both app services, not
`services/api` or `apps/web` — the uv workspace root (`pyproject.toml`,
`uv.lock`, `alembic.ini`) and the pnpm workspace root (`pnpm-workspace.yaml`,
`pnpm-lock.yaml`) both live there. `services/api/railway.json` and
`apps/web/railway.json` already encode this, along with each service's
release/health-check config, so most of the setup below is just secrets.

### 1. Postgres

Add the managed Postgres plugin to the project. It exposes a
`DATABASE_URL` that the api service references — do not copy the value,
reference it, so a credential rotation does not silently break the api.

**Keep the database private.** Do not leave a TCP proxy (public
networking) on the Postgres service. The api reaches it over the private
network; a proxy only exists so a human can run `railway connect
Postgres`. Add one for the duration of that task, then delete it. Railway
assigns a new port each time, so nothing stale lingers.

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
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (a reference, never a pasted value) |
| `LASTFM_API_KEY` | from `secrets.env` |
| `RESEND_API_KEY` | from the Resend dashboard — a **sending-access** key restricted to the domain, not full access |
| `EMAIL_FROM_ADDRESS` | `Artist Exchange <noreply@artistexchange.chburrows.com>` — domain is already verified in Resend |
| `INTERNAL_JOB_TOKEN` | `openssl rand -hex 32` — keep this value, GitHub needs it too |
| `SESSION_SECRET` | `openssl rand -hex 32` |
| `ENVIRONMENT` | `production` |
| `PORT` | `8000` — the port the container listens on, and the custom domain's target port |
| `WEB_ORIGIN` | the web service's public URL — leave a placeholder for now, come back and set it once step 3 below gives you the real one, then redeploy api |

Then generate a public domain for the service and note the URL — this is
`NEXT_PUBLIC_API_BASE_URL` for step 3.

`LASTFM_SHARED_SECRET` is deliberately **not** set in Railway. The app
only calls unsigned methods and never reads it; a secret the app does not
need is pure exposure if the platform leaks its env vars.

### 3. web

Create a second service from the same GitHub repo. Railway reads
`apps/web/railway.json`, which sets:

- **Dockerfile**: `apps/web/Dockerfile`
- **Health check**: `/` (the app is a static export — there is no `/health`
  endpoint, just static files, so the health check is "does the server
  respond at all")

Set the root directory to `/` (the repo root), same reason as api, then set:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | the api service's public URL from step 2 |

**This one has to be set before the first build, not after.** Next.js
inlines every `NEXT_PUBLIC_*` variable into the static JS bundle at
`next build` time — there is no server at runtime to read it from later,
unlike api's env vars. Railway forwards a Dockerfile-building service's
variables in as Docker build args automatically, and `apps/web/Dockerfile`
declares `ARG NEXT_PUBLIC_API_BASE_URL` to receive it, so setting it as a
normal service variable (not a special "build variable") is enough — just
set it *before* triggering the first deploy. If you change it later, you
must trigger a fresh build (a redeploy of the same image will keep serving
the old baked-in value).

Then generate a public domain for the service, note the URL, and go back
to step 2 to set the api service's `WEB_ORIGIN` to it — magic-link emails
and CORS both depend on that value being the real web URL, not the
placeholder. Redeploy api after changing it.

### 4. Seed the production universe

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
can trigger it by hand from the Actions tab to re-run today's night.

**Manual re-runs are always safe** — the job is idempotent on
`(artist_id, as_of_date)`, verified locally against the live API and
covered by the I12 tests.

**There is no backfill.** The snapshot endpoint rejects any `as_of` other
than today (UTC) with a 422. Last.fm only reports current counts, so
filing them under another date would fabricate history, both by
overwriting a real value and by filling a gap that the growth window then
reads as the past. A night that fails must be re-run **the same UTC day**,
or it stays a gap. A missing day is absorbed, because growth rates
read their base from a ±`GROWTH_BASE_WINDOW_DAYS` window
(`core/index.py: pick_base_snapshot`), not from one exact day.

## Verifying the deploy

```bash
curl -fsS "$API_BASE_URL/health"

# Web is a static export -- a 200 here just proves the container is
# serving files. Load it in a browser to confirm it can actually reach
# the api (open the network tab; requests should hit $API_BASE_URL, not
# localhost -- a stale build means NEXT_PUBLIC_API_BASE_URL was set after
# the last build, see step 3 above).
curl -fsS "$WEB_URL/" > /dev/null && echo "web is up"

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

## Rotating production secrets

Last done **2026-10-28**, after Railway's Oct 21 incident in which an
attacker decrypted a subset of customer env vars. Every secret was rotated;
forensics found no sign of use. If it happens again:

- **Postgres password:** Postgres → Config → Connection → **Regenerate**.
  It changes the password inside the engine *and* the variable, restarts
  Postgres (dropping every old connection), and redeploys services that
  reference it. Never edit `POSTGRES_PASSWORD` by hand — the engine only
  reads it on first init, so the two drift apart and every connection
  fails.
- **Commit other api variable changes first** (hold Alt and click Deploy
  to commit without redeploying), so Regenerate's automatic api redeploy
  picks everything up at once.
- **`INTERNAL_JOB_TOKEN`** lives in two places: the api variable and the
  GitHub secret. Update both before the next 07:00 UTC run.
- **`SESSION_SECRET`** rotation logs everyone out. That is the point: it
  invalidates any session forged with the old value.
- **Last.fm** has no regenerate button — create a new API account and
  suspend the old one.
- `railway variables --json` prints **resolved** values, so it can't tell
  a `${{reference}}` from a pasted literal. Check the dashboard.

## Hibernating production

Railway has no "pause". To stop paying while not developing, cancel the
Hobby plan (Billing → Active Plan → Cancel Plan): the workspace drops to
the Free plan and Railway stops every deployment. Railway documents Hobby
volumes as deleted **60 days after cancellation**, so treat the project as
possibly gone and keep your own dump.

**Currently hibernated** since 2026-10-28 (plan active until 2026-11-18).
The verified dump and the full restore notes (region, image, variable
names, domains, CNAME targets) are in `~/ax-backups/` on the dev machine,
outside the repo — the dump contains user emails, and this repo is public.

To hibernate:

1. Add a temporary TCP proxy to Postgres and dump with a **`postgres:18`
   client** (host tools are v14, Compose is v16 — both too old for the
   server):
   `docker run --rm -e DBURL -v ~/ax-backups:/out postgres:18 sh -c 'pg_dump "$DBURL" -Fc --no-owner --no-acl -f /out/artist-exchange-$(date +%F).dump'`
2. Restore it into a throwaway `postgres:18` container and compare row
   counts with production. Then delete the TCP proxy.
3. `gh workflow disable nightly-snapshot.yml`, then cancel the plan.

The cost is a permanent gap in `metric_snapshots`: there is no backfill
(see "GitHub Actions secrets" above).

To resume:

1. **Project still there:** upgrade to Hobby, then redeploy Postgres first
   (check `SELECT max(as_of_date), count(*) FROM metric_snapshots`), then
   api, then web. Check both custom domains are active.
2. **Project gone:** rebuild per "Railway deploy" above, in region `sfo`.
   After creating Postgres and **before** api's first deploy, add a
   temporary TCP proxy, `pg_restore --no-owner --no-acl -d "$DBURL"` the
   dump (again with a `postgres:18` client), then delete the proxy. Skip
   `ax seed-artists`. Re-add both custom domains and point the two
   Cloudflare CNAMEs at the new targets Railway shows — the URL variables
   and GitHub's `API_BASE_URL` all use the custom domains, so they stay
   unchanged. Set a new `INTERNAL_JOB_TOKEN` in both places.
3. Run the checks in "Verifying the deploy", then
   `gh workflow enable nightly-snapshot.yml`. Index scores come back after
   about 5–9 nights, once the growth lookback has history again.

## Verifying the setup

```bash
uv run pytest                                    # should be green
docker compose exec postgres psql -U postgres artist_exchange -c \
  "SELECT count(*) FROM metric_snapshots;"       # non-zero after `ax reset`
pnpm dev                                         # http://localhost:3000
```
