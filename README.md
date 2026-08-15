# Artist Exchange

A play-money market where users trade shares of musical artists. See `CONCEPT.md` (product) and `PLAN.md` (build) for details.

## Run it locally

First time only — see `SETUP.md` for prerequisites, `.env` values, and secrets.

```bash
docker compose up -d          # Postgres on :5432, adminer on :8080
uv sync                       # Python deps
pnpm install                  # Node deps
uv run alembic upgrade head   # apply migrations
uv run ax reset               # seed artists + fake history + simulated trades
```

### Backend (FastAPI)

```bash
uv run uvicorn ax.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs at http://localhost:8000/docs.

`--host 0.0.0.0` matters on WSL2. Uvicorn otherwise binds WSL's own loopback,
which a browser on the Windows host cannot reach — the page at :3000 loads but
every API call fails with `ERR_CONNECTION_RESET`.

### Frontend (Next.js)

```bash
pnpm dev
```

App at http://localhost:3000. Requires `apps/web/.env.local` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

### Tests

```bash
uv run pytest                              # all Python tests
uv run pytest services/api/tests/core      # fast pure unit tests, no DB/network
pnpm e2e                                    # Playwright
```

## More

- `SETUP.md` — full setup, env vars, secrets, Railway deploy, verifying a deploy
- `CLAUDE.md` — stack, layout, non-negotiable engineering rules
