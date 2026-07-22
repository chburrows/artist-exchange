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
import re
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ax.api.deps import get_email_provider, get_metric_provider
from ax.api.main import app
from ax.core.amm import listing_slope_uc
from ax.db.models import Artist, IndexSnapshot, PriceHistory
from ax.db.session import get_db
from ax.providers.base import ArtistRef, MetricValue, ProviderNotFound
from ax.providers.email import EmailMessage, EmailSendError
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


def _create_database_if_missing(drop_first: bool = False) -> None:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            if drop_first:
                # Terminate stragglers first; DROP DATABASE fails while any
                # session is still connected.
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": TEST_DB_NAME},
                )
                connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))

            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin.dispose()


def _alembic_config() -> Config:
    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(REPO_ROOT, "services/api/migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Create (if needed) and migrate the test database, once per session."""
    _create_database_if_missing()

    try:
        command.upgrade(_alembic_config(), "head")
    except CommandError:
        # The test database is stamped with a revision that no longer
        # exists — the normal result of regenerating a migration or
        # switching branches. The test database holds nothing worth
        # keeping, so rebuild it rather than making the developer work out
        # what "Can't locate revision" means.
        _create_database_if_missing(drop_first=True)
        command.upgrade(_alembic_config(), "head")

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


class FakeEmailProvider:
    """In-memory `EmailProvider`. Records every send so a test can pull
    the magic-link token straight out of the rendered HTML instead of
    reading email, or make a provider fail to exercise the 502 path."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailSendError("simulated provider failure")
        self.sent.append(message)

    def last_link(self) -> str:
        """Pulls the `?token=...` URL out of the most recent message's
        HTML body -- the test-side equivalent of clicking the email."""
        match = re.search(r'href="([^"]+)"', self.sent[-1].html)
        assert match, "no link found in last sent email"
        return match.group(1)

    def last_token(self) -> str:
        return self.last_link().rsplit("token=", 1)[-1]


@pytest.fixture
def email_provider() -> FakeEmailProvider:
    return FakeEmailProvider()


def complete_signup(
    client: TestClient,
    email_provider: FakeEmailProvider,
    username: str,
    *,
    email: str | None = None,
) -> dict:
    """Drives the real request -> consume round trip Phase 7's
    verify-before-create signup requires, standing in for the one-shot
    `POST /auth/signup` every test in this suite called directly before
    email became mandatory. Returns the same `{"user": {...}, "cash_cents":
    ...}` shape `/auth/signup/consume` answers with.

    `email` defaults to `f"{username}@example.com"` -- fine for every
    caller that just needs *a* verified account and doesn't care which
    address it's under."""
    request = client.post(
        "/auth/signup",
        json={"email": email or f"{username}@example.com", "username": username},
    )
    assert request.status_code == 202, request.text
    token = email_provider.last_token()
    consume = client.post("/auth/signup/consume", json={"token": token})
    assert consume.status_code == 201, consume.text
    return consume.json()


@pytest.fixture
def test_settings() -> Settings:
    """Explicit settings, independent of whatever is in the developer's
    `.env` — otherwise a missing local file changes test outcomes."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        lastfm_api_key="test-key",
        internal_job_token=TEST_JOB_TOKEN,
        session_secret="test-session-secret",
        environment="test",
    )


@pytest.fixture
def client(
    session: Session,
    provider: FakeProvider,
    email_provider: FakeEmailProvider,
    test_settings: Settings,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_metric_provider] = lambda: provider
    app.dependency_overrides[get_email_provider] = lambda: email_provider
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


ListArtist = Callable[..., Artist]


@pytest.fixture
def list_artist(session: Session) -> ListArtist:
    """Puts an already-created artist into the listed, tradable state --
    the same fields `jobs/recompute.py._apply_market_state`'s listing
    branch sets, plus the `IndexSnapshot` and `PriceHistory('listing')`
    rows that normally accompany it -- without running the real index
    pipeline. Trade-route tests care about the AMM/ledger mechanics, not
    re-deriving a score from synthetic metric snapshots."""

    def _list(
        artist: Artist,
        *,
        fair_value_cents: int = 1_000,
        index_score: float = 50.0,
        as_of: date | None = None,
        now: datetime | None = None,
    ) -> Artist:
        now = now or datetime.now(UTC)
        as_of = as_of or now.date()

        artist.slope_microcents_per_share = listing_slope_uc()
        artist.anchor_cents = fair_value_cents
        artist.anchor_target_cents = fair_value_cents
        artist.glide_start_at = now
        artist.glide_end_at = now
        artist.listed_at = now

        session.add(
            IndexSnapshot(
                artist_id=artist.id,
                as_of_date=as_of,
                index_score=index_score,
                fair_value_cents=fair_value_cents,
                components={"v": 1},
            )
        )
        session.add(
            PriceHistory(
                artist_id=artist.id,
                market_price_cents=fair_value_cents,
                fair_value_cents=fair_value_cents,
                net_supply=0,
                source="listing",
            )
        )
        session.flush()
        return artist

    return _list
