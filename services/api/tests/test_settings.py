"""Settings normalization.

Covers the boundary where a managed provider's connection string meets
SQLAlchemy's driver resolution — the one place a correct-looking
environment variable produces a crash at connect time rather than a
validation error at startup.
"""

import pytest

from ax.settings import Settings


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        # What Railway actually injects.
        (
            "postgresql://user:pw@host.railway.internal:5432/railway",
            "postgresql+psycopg://user:pw@host.railway.internal:5432/railway",
        ),
        # Legacy scheme still emitted by some providers.
        (
            "postgres://user:pw@host:5432/db",
            "postgresql+psycopg://user:pw@host:5432/db",
        ),
        # Already explicit — must be left exactly alone.
        (
            "postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange",
            "postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange",
        ),
    ],
)
def test_database_url_is_normalized_to_psycopg3(supplied: str, expected: str) -> None:
    """Without this, a raw Railway DATABASE_URL crashes the API on boot
    with `ModuleNotFoundError: No module named 'psycopg2'`."""
    assert Settings(database_url=supplied).database_url == expected


def test_normalized_url_actually_resolves_a_dialect() -> None:
    """Asserting on the string is not enough — the point is that
    SQLAlchemy can build an engine from it without psycopg2 installed."""
    from sqlalchemy import create_engine

    settings = Settings(database_url="postgresql://user:pw@host:5432/db")
    engine = create_engine(settings.database_url)

    assert engine.dialect.driver == "psycopg"
