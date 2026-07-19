"""Declarative base, naming convention, and schema-wide type defaults.

Two things are set here that are easy to get wrong once per column and
impossible to get wrong once per schema:

`NAMING_CONVENTION` — without it, Alembic autogenerate invents names for
unnamed constraints and `alembic check` reports spurious drift on every
run. Set once, here, before any migration exists.

`type_annotation_map` — the defaults that keep CLAUDE.md rules true by
construction rather than by vigilance:

  - `int` -> BIGINT. Money is integer cents in BIGINT everywhere (rule 1),
    and Last.fm playcounts alone exceed 2^31, so there is no int column in
    this schema that wants to be 32-bit.
  - `datetime` -> TIMESTAMP WITH TIME ZONE. A naive timestamp on
    `glide_start_at`/`glide_end_at` would silently make the glide
    interpolation wrong by however many hours the server is offset from
    UTC. Mapping the bare type covers `Mapped[datetime | None]` too, which
    a per-column `Annotated` alias does *not* — that gap produced seven
    naive columns on the first autogenerate run.
"""

from datetime import datetime

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TIMESTAMP

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        int: BigInteger,
        datetime: TIMESTAMP(timezone=True),
    }
