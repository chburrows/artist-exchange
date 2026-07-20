"""FastAPI application.

Phase 1 is deliberately thin: a health check and the protected job
endpoint. The product API (artists, trades, portfolio) lands in Phase 4 —
this exists now only so the snapshotter can be deployed and start
accumulating history, which is the one thing that cannot be hurried later.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ax.api.routers import artists, auth, internal, portfolio, trades
from ax.logging_config import configure_third_party_logging
from ax.settings import get_settings

# Must run before the first outbound request: httpx logs full URLs, and
# ours carry the Last.fm API key.
configure_third_party_logging()

app = FastAPI(
    title="Artist Exchange API",
    version="0.1.0",
    # apps/web/lib/api.ts is generated from this schema, so the OpenAPI
    # document is a build input, not just documentation.
    openapi_url="/openapi.json",
)

settings = get_settings()

# The web app is a static export on a different origin, so it is always
# cross-origin — even in production. Locked to a single known origin
# rather than "*" because Phase 4 introduces cookie auth, and credentialed
# requests with a wildcard origin are both forbidden by browsers and a bad
# idea.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(internal.router)
app.include_router(auth.router)
app.include_router(trades.router)
app.include_router(artists.router)
app.include_router(portfolio.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness only — deliberately does not touch the database.

    Railway restarts a container that fails its health check. If this
    probed Postgres, a brief DB blip would kill an otherwise healthy API
    and turn a recoverable incident into a restart loop.
    """
    return {"status": "ok", "environment": settings.environment}
