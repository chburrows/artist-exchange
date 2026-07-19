"""Integration test harness — real Postgres, no network.

Two decisions worth stating, because both are easy to get subtly wrong:

**A separate database, migrated with Alembic.** Tests run against
`artist_exchange_test`, not the dev database, so a test run never destroys
local data. It is built by running the real migrations rather than
`create_all`, which means every test run also proves the migration chain
applies to an empty database — the check that catches "works locally,
breaks on deploy".

**Each test in an outer transaction, rolled back at teardown.** The
session joins that transaction with
`join_transaction_mode="create_savepoint"`. That matters specifically
because `run_snapshot` commits per artist: with a plain binding those
commits would end the outer transaction and leak rows into the next test.
As savepoints, the job's real commit behavior is exercised faithfully and
the outer rollback still cleans up everything.

Settings and the provider are supplied through `app.dependency_overrides`
rather than by monkeypatching module attributes, because FastAPI resolves
`Depends(get_settings)` to the function object captured at import time —
patching the name afterwards has no effect on an already-built route.
"""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ax.api.deps import get_metric_provider
from ax.api.main import app
from ax.db.models import Artist
from ax.db.session import get_db
from ax.providers.base import ArtistRef, MetricValue, ProviderNotFound
from ax.settings import Settings, get_settings

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

TEST_DB_NAME = "artist_exchange_test"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+psycopg://postgres:postgres@localhost:5432/{TEST_DB_NAME}",
)

# Derived from TEST_DATABASE_URL rather than hardcoded: a hardcoded admin
# URL silently disagrees with an overridden TEST_DATABASE_URL, so the
# fixture would create the database on one server and the tests would read
# from another.
_TEST_URL = make_url(TEST_DATABASE_URL)
TEST_DB_NAME = _TEST_URL.database or TEST_DB_NAME
ADMIN_URL = _TEST_URL.set(database="postgres")

TEST_JOB_TOKEN = "test-job-token"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Create (if needed) and migrate the test database, once per session."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(REPO_ROOT, "services/api/migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    test_engine = create_engine(TEST_DATABASE_URL)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    # `expire_on_commit=False` to match the production sessionmaker. With
    # the default (True), every per-artist commit in `run_snapshot`
    # expires the loaded Artist objects and the next iteration re-SELECTs
    # them — so the tests would exercise a different session configuration
    # than production, and N+1 reloads that production never performs.
    db = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


class FakeProvider:
    """In-memory `MetricProvider`.

    Keyed by artist name, records its calls, and can be told to fail for
    specific artists — enough to drive every branch of the snapshot job
    without a network round trip or rate-limit budget.
    """

    source = "lastfm"

    def __init__(
        self,
        metrics: dict[str, dict[str, int]] | None = None,
        *,
        not_found: set[str] | None = None,
        raises: dict[str, Exception] | None = None,
    ) -> None:
        self.metrics = metrics or {}
        self.not_found = not_found or set()
        self.raises = raises or {}
        self.calls: list[str] = []

    def fetch(self, ref: ArtistRef) -> list[MetricValue]:
        self.calls.append(ref.name)
        if ref.name in self.raises:
            raise self.raises[ref.name]
        if ref.name in self.not_found:
            raise ProviderNotFound(ref.name)
        values = self.metrics.get(ref.name, {"listeners": 1000, "playcount": 5000})
        return [MetricValue(key, value) for key, value in values.items()]


@pytest.fixture
def provider() -> FakeProvider:
    """The provider the API fixture serves. Mutate it before calling."""
    return FakeProvider()


@pytest.fixture
def test_settings() -> Settings:
    """Explicit settings, independent of whatever is in the developer's
    `.env` — otherwise a missing local file changes test outcomes."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        lastfm_api_key="test-key",
        internal_job_token=TEST_JOB_TOKEN,
        environment="test",
    )


@pytest.fixture
def client(
    session: Session, provider: FakeProvider, test_settings: Settings
) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_metric_provider] = lambda: provider
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


ArtistFactory = Callable[..., Artist]


@pytest.fixture
def make_artist(session: Session) -> ArtistFactory:
    """Insert an artist and return it. Slugs are made unique per call so a
    test can create several artists with the same display name."""
    created = 0

    def _make(
        name: str,
        *,
        tier: str = "growth",
        mbid: str | None = None,
        delisted: bool = False,
    ) -> Artist:
        nonlocal created
        created += 1
        artist = Artist(
            slug=f"{name.lower().replace(' ', '-')}-{created}",
            name=name,
            lastfm_name=name,
            lastfm_mbid=mbid,
            tier=tier,
            delisted_at=datetime(2020, 1, 1, tzinfo=UTC) if delisted else None,
        )
        session.add(artist)
        session.flush()
        return artist

    return _make


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_JOB_TOKEN}"}
