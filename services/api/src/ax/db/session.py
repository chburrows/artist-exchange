"""Engine and session factory.

Synchronous on purpose. The workload is a nightly batch job plus low-QPS
trading reads; async SQLAlchemy would buy nothing here and would make the
`SELECT ... FOR UPDATE` trade path in Phase 4 harder to reason about.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ax.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        # Railway's managed Postgres drops idle connections; without
        # pre-ping the first query after an idle period fails rather than
        # transparently reconnecting.
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
