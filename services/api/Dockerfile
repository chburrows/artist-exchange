# Build context is the REPO ROOT, not services/api — the uv workspace root
# (pyproject.toml + uv.lock) and alembic.ini both live there, and
# `uv sync --locked` needs the lockfile that resolves the whole workspace.
#
#   docker build -f services/api/Dockerfile .
#
FROM python:3.12-slim AS base

# Pinned rather than :latest so a rebuild months from now resolves the
# same dependencies. An unpinned toolchain makes "it built in June" and
# "it fails in September" indistinguishable from a code change.
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, in their own layer: the manifests change rarely and
# the source changes constantly, so this keeps the slow resolve cached
# across ordinary code deploys.
COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml services/api/pyproject.toml
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY services/api services/api

RUN uv sync --locked --no-dev

# Non-root: if the app is ever compromised, the blast radius should not
# include the container filesystem.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# `sh -c` so ${PORT} expands — Railway assigns the port at runtime and
# routes to it; a hardcoded port makes the health check fail with no
# obvious cause. `exec` so uvicorn *replaces* the shell rather than
# running as its child: otherwise SIGTERM on a redeploy goes to sh, never
# reaches uvicorn, and every deploy waits out the kill timeout instead of
# shutting down gracefully.
CMD ["sh", "-c", "exec uvicorn ax.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
