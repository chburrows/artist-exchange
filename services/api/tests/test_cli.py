"""`ax promote-admin` and the `fake-history` guards added alongside the
admin-clearing work: a fresh-universe check (re-running standalone
against an already-seeded universe used to silently misalign
`metric_snapshots` against published `index_snapshots`/`price_history`
-- see `_fake_history`'s docstring) and a per-day quarantine auto-clear
(synthetic data has no real manipulation to catch, so a long backfill
must not end with most of the universe permanently frozen).

These commands build their own DB session via `session_scope()`
(`ax.db.session`), not FastAPI's `Depends(get_db)`, so they can't use the
`client`/`session` dependency-override fixtures the router tests do.
Instead `get_sessionmaker` is monkeypatched to bind to the same test
engine, mirroring `test_trades_api.py::test_concurrent_buys_on_one_artist_serialize`'s
"commits for real, cleans up after itself" pattern -- the only other place
in the suite that needs a real, independently-committing session against
the test database.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

import ax.db.session as db_session
from ax.cli import app
from ax.core.config import MIN_CROSS_SECTION_SIZE
from ax.db.models import Artist, FlaggedArtist, IndexSnapshot, MetricSnapshot, PriceHistory, User

runner = CliRunner()


@pytest.fixture
def real_session(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[OrmSession]:
    """Points `ax.db.session.session_scope` (what every CLI command uses)
    at the test database instead of whatever `DATABASE_URL` resolves to
    locally, and hands back a session on the same engine for setup/
    assertions. Real commits, not a rolled-back savepoint -- cleanup is
    each test's own responsibility, same as the concurrency test this
    pattern is borrowed from."""
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: SessionLocal)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_promote_admin_grants_flag(real_session: OrmSession) -> None:
    username = f"promotee-{uuid4().hex[:8]}"
    user = User(username=username, email=f"{username}@example.com")
    real_session.add(user)
    real_session.commit()

    try:
        result = runner.invoke(app, ["promote-admin", "--username", username])

        assert result.exit_code == 0, result.output
        real_session.refresh(user)
        assert user.is_admin is True
    finally:
        real_session.execute(delete(User).where(User.id == user.id))
        real_session.commit()


def test_promote_admin_errors_for_unknown_user(real_session: OrmSession) -> None:
    result = runner.invoke(app, ["promote-admin", "--username", "no-such-user"])

    assert result.exit_code == 1
    assert "no such user" in result.output


def test_fake_history_refuses_on_nonempty_universe(real_session: OrmSession) -> None:
    suffix = uuid4().hex[:8]
    artist = Artist(
        slug=f"nonempty-{suffix}",
        name="Nonempty",
        lastfm_name="Nonempty",
        tier="growth",
    )
    real_session.add(artist)
    real_session.flush()
    real_session.add(
        MetricSnapshot(
            artist_id=artist.id,
            as_of_date=datetime.now(UTC).date(),
            source="lastfm",
            metric_key="listeners",
            value=1000,
        )
    )
    real_session.commit()

    try:
        result = runner.invoke(app, ["fake-history", "--days", "3", "--seed", "1"])

        assert result.exit_code == 1
        assert "ax reset" in result.output
    finally:
        real_session.execute(delete(MetricSnapshot).where(MetricSnapshot.artist_id == artist.id))
        real_session.execute(delete(Artist).where(Artist.id == artist.id))
        real_session.commit()


def test_fake_history_auto_clears_same_day_quarantine_flags(real_session: OrmSession) -> None:
    """At population size 10 (== `MIN_CROSS_SECTION_SIZE`), PLAN.md
    documents that `PERCENTILE_MOVE_THRESHOLD`'s nearest-rank percentile
    always flags whichever artist moved most that day -- so a real GBM
    backfill over this population reliably raises at least one flag,
    giving this test a genuine (not vacuous) exercise of the auto-clear
    path: some flag must have existed to clear, and none may remain open
    afterward.
    """
    suffix = uuid4().hex[:8]
    artists = [
        Artist(
            slug=f"fh-{suffix}-{i}",
            name=f"FH {suffix} {i}",
            lastfm_name=f"FH {suffix} {i}",
            tier="growth",
        )
        for i in range(MIN_CROSS_SECTION_SIZE)
    ]
    real_session.add_all(artists)
    real_session.commit()
    artist_ids = [a.id for a in artists]

    try:
        result = runner.invoke(app, ["fake-history", "--days", "10", "--seed", "7"])
        assert result.exit_code == 0, result.output

        all_flags = real_session.scalars(
            select(FlaggedArtist).where(FlaggedArtist.artist_id.in_(artist_ids))
        ).all()
        assert len(all_flags) > 0, "expected the known n=10 percentile-move quirk to fire"
        assert all(f.cleared_at is not None for f in all_flags)
        assert all(f.cleared_by == "ax fake-history" for f in all_flags)
    finally:
        real_session.execute(delete(FlaggedArtist).where(FlaggedArtist.artist_id.in_(artist_ids)))
        real_session.execute(delete(PriceHistory).where(PriceHistory.artist_id.in_(artist_ids)))
        real_session.execute(delete(IndexSnapshot).where(IndexSnapshot.artist_id.in_(artist_ids)))
        real_session.execute(delete(MetricSnapshot).where(MetricSnapshot.artist_id.in_(artist_ids)))
        real_session.execute(delete(Artist).where(Artist.id.in_(artist_ids)))
        real_session.commit()
