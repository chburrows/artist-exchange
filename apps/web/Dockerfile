# Build context is the REPO ROOT, not apps/web — the pnpm workspace root
# (pnpm-workspace.yaml + pnpm-lock.yaml) lives there.
#
#   docker build -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=https://... .
#
FROM node:20-slim AS build

RUN corepack enable pnpm

WORKDIR /app

# Manifests first, in their own layer: they change rarely and the source
# changes constantly, so this keeps the slow install cached across
# ordinary code deploys. See services/api/Dockerfile for the same pattern.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web

# `output: 'export'` (next.config.ts) makes this build produce static
# files in apps/web/out/, not a Next.js server — `next start` does not
# work against an export build, hence serving `out/` with a static file
# server in the run stage below instead.
#
# Must be a build ARG, not a runtime env var: `NEXT_PUBLIC_*` values are
# inlined into the JS bundle by `next build` itself, so there is nothing
# left to read at container start. Railway forwards a Dockerfile-building
# service's variables in as build args automatically, so setting this as
# a normal service variable on Railway is enough — no extra config needed
# there, but locally it must be passed with `--build-arg`.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

RUN pnpm --filter web build


FROM node:20-slim AS run

# Pinned rather than :latest — see services/api/Dockerfile for why.
RUN npm install --global serve@14.2.4

# Non-root: if the app is ever compromised, the blast radius should not
# include the container filesystem.
RUN useradd --create-home --uid 10001 appuser
USER appuser

WORKDIR /app
COPY --from=build --chown=appuser:appuser /app/apps/web/out ./out

EXPOSE 3000

# `sh -c` so ${PORT} expands — Railway assigns the port at runtime and
# routes to it; a hardcoded port makes the health check fail with no
# obvious cause. `exec` so `serve` *replaces* the shell rather than
# running as its child: otherwise SIGTERM on a redeploy goes to sh, never
# reaches serve, and every deploy waits out the kill timeout instead of
# shutting down gracefully.
#
# No `-s` (SPA rewrite-to-index.html): `next build` already emits a real
# `out/404.html` and a `<route>.html` per top-level page (clean URLs,
# which `serve` resolves natively), so an SPA fallback would silently
# turn every genuine 404 into a 200 for the home page instead of using
# the page Next already generated for that case.
CMD ["sh", "-c", "exec serve ./out -l ${PORT:-3000}"]
