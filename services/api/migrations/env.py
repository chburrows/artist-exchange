"""Alembic environment.

Imports `ax.db.models` for its side effect of populating `Base.metadata`,
which is what makes both autogenerate and `alembic check` see the models.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ax.db import models  # noqa: F401  (registers all tables on Base.metadata)
from ax.db.base import Base
from ax.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Only fall back to settings when a URL was not supplied explicitly. The
# test harness sets one to point at `artist_exchange_test`; overwriting it
# here would silently migrate — and let tests write to — the developer's
# real database instead.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without compare_type, a bigint -> int narrowing slips through
            # `alembic check` silently — which on a money column would be
            # a real bug.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
