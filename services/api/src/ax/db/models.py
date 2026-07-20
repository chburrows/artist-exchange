"""SQLAlchemy models — the whole v1 schema.

The full data model lands in one migration rather than one per phase, so
production carries the finished shape from the first deploy and later
phases are code-only. Tables beyond Phase 1's reach (users, transactions,
caches) are unused until Phase 4 but their design is already locked in
PLAN.md.

Structural rules enforced here rather than by convention:
  - every money column is BIGINT cents, never float, never NUMERIC — see
    the `type_annotation_map` in `base.py`, which makes that the default
    for the whole schema
  - `transactions` is append-only; there is no updated_at, and nothing in
    the codebase may UPDATE or DELETE it
  - `metric_snapshots` is long-format, so adding a YouTube signal is an
    INSERT of new `source`/`metric_key` rows and needs no migration
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ax.db.base import Base

# JSONB on Postgres, plain JSON on anything else (keeps the models
# importable by tooling that reflects against SQLite).
JsonB = JSONB().with_variant(JSON(), "sqlite")

TIER_GROWTH = "growth"
TIER_BLUE_CHIP = "blue_chip"

SOURCE_LASTFM = "lastfm"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # citext: usernames and emails are case-insensitively unique, enforced
    # by the column type rather than by remembering to .lower() at every
    # call site.
    username: Mapped[str] = mapped_column(CITEXT, unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The raw session token never touches the database. A DB leak must not
    # hand the attacker usable sessions.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class MagicLink(Base):
    """PLAN.md's schema is `(id, email, token_hash, expires_at, used_at)` —
    this adds `user_id`, a deliberate deviation, for the same reason
    `price_history` deviated from its own PLAN.md spec (see that class).

    Without `user_id`, consuming a link would have to resolve the target
    user by looking up `email` against `users.email` at consume time. That
    makes "attach a new email" unsafe: a link is issued for an address
    before it's proven to belong to the requester, so if attach wrote
    `users.email` immediately, an attacker could pre-claim a victim's real
    address on the attacker's own account. The victim, later requesting
    their *own* password-less recovery for that address, would receive a
    link that logs them into the attacker's account instead.

    Binding `user_id` at link-creation time (always the account the link
    is *for*, chosen server-side — the current session for an attach
    request, or a lookup-by-email for a recovery request) removes the
    ambiguity: consuming a link always logs in as that specific user, and
    only then, having proven mailbox control, stamps `users.email`.
    """

    __tablename__ = "magic_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(CITEXT, index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Artist(Base):
    """The one table with mutable market state. Everything else is append-only.

    The market-state columns are nullable because a seeded artist is not
    yet listed: it needs MIN_SNAPSHOTS_TO_LIST snapshots before an index
    score exists to anchor a price to. Until then `listed_at` is NULL and
    the artist is `warming_up` — present in the universe, absent from the
    cross-section and from listing.
    """

    __tablename__ = "artists"
    __table_args__ = (
        CheckConstraint(
            f"tier IN ('{TIER_GROWTH}', '{TIER_BLUE_CHIP}')",
            name="tier_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(Text)

    # lastfm_name is the canonical name the API answers to, which is not
    # always our display name. Resolved once at seed time so the nightly
    # job never has to guess or re-resolve.
    lastfm_name: Mapped[str] = mapped_column(Text)
    lastfm_mbid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    tier: Mapped[str] = mapped_column(String(16))
    listed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    delisted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --- mutable market state (set at listing, moved by Phase 3 reversion) ---
    slope_microcents_per_share: Mapped[int | None] = mapped_column(nullable=True)
    anchor_cents: Mapped[int | None] = mapped_column(nullable=True)
    anchor_target_cents: Mapped[int | None] = mapped_column(nullable=True)
    glide_start_at: Mapped[datetime | None] = mapped_column(nullable=True)
    glide_end_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class MetricSnapshot(Base):
    """Long-format raw observations from external providers.

    The composite primary key *is* the idempotency mechanism (CLAUDE.md
    rule 7): the nightly job upserts ON CONFLICT, so a retried Action or a
    manual re-run can never double-write.
    """

    __tablename__ = "metric_snapshots"

    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    value: Mapped[int]
    fetched_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class IndexSnapshot(Base):
    """Computed index score per artist per day.

    The one place floats are legitimate: `index_score` genuinely is a
    statistic, not money. `fair_value_cents` derived from it is money, and
    is integer.

    `components` carries the z-scores, the EWMA state, and any quarantine
    flag and reason — the audit trail for why a score moved, which is what
    makes the Phase 3 review queue possible.
    """

    __tablename__ = "index_snapshots"
    __table_args__ = (Index("ix_index_snapshots_as_of_date", "as_of_date"),)

    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)

    index_score: Mapped[float] = mapped_column(Float)
    fair_value_cents: Mapped[int]
    components: Mapped[dict[str, object]] = mapped_column(JsonB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PriceHistory(Base):
    """Append-only market price series, one row per price-moving event.

    PLAN.md specified `PK (artist_id, at)`. That is deliberately *not* what
    this is, because a timestamp cannot safely be part of an identity here:

    1. Two price-moving events for one artist at the same instant would
       violate the key, rejecting a user's trade for a reason unrelated to
       their trade. The `SELECT ... FOR UPDATE` artist lock does not
       prevent it — see (2).
    2. Postgres `now()` is *transaction start* time, not statement time,
       and the row lock is acquired after the transaction begins. So the
       order transactions start and the order they execute can differ, and
       two rows can be written with timestamps that invert their real
       execution order. Reading `ORDER BY at` then yields a state sequence
       that never happened — net_supply moving 2 -> 1 across two
       consecutive buys.

    A surrogate key makes collisions structurally impossible and leaves
    `at` free to be purely descriptive. `id` also breaks ties in insertion
    order, so `ORDER BY at, id` is stable even for genuinely simultaneous
    events.

    See the `at` column for the other half of the fix.
    """

    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint(
            "source IN ('trade', 'reversion', 'listing')",
            name="source_valid",
        ),
        # PLAN.md writes this as (artist_id, at DESC), but Postgres scans a
        # btree backwards at the same cost, so a plain ascending index
        # serves `WHERE artist_id = ? ORDER BY at DESC` identically. Kept
        # plain because an explicit DESC makes it an expression index,
        # which autogenerate cannot compare — that reports drift from
        # `alembic check` on every run forever.
        Index("ix_price_history_artist_id_at", "artist_id", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))

    # `clock_timestamp()`, NOT `now()`. `now()` is frozen at transaction
    # start, so under lock contention it records when a trade *queued*
    # rather than when it executed — which inverts the series order.
    # `clock_timestamp()` reads the real clock at INSERT, after the lock.
    # As a server default it is also the value you get by omitting the
    # column, so the correct behavior is the one you get for free.
    at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))

    market_price_cents: Mapped[int]
    fair_value_cents: Mapped[int | None] = mapped_column(nullable=True)
    net_supply: Mapped[int]
    source: Mapped[str] = mapped_column(String(16))


class Transaction(Base):
    """The ledger. APPEND-ONLY — no UPDATE, no DELETE, ever (CLAUDE.md rule 2).

    Corrections are new compensating rows. Balances and positions are
    *derived* from this table; the caches are an optimization, never the
    source of truth.

    `index_score_at_trade` and `fair_value_cents_at_trade` are denormalized
    deliberately: they are immutable history that the Talent Scout
    leaderboard depends on. Recomputing them later from snapshots would be
    both slow and wrong.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('GRANT', 'BUY', 'SELL', 'FEE')",
            name="kind_valid",
        ),
        Index("ix_transactions_user_id_created_at", "user_id", "created_at"),
        Index("ix_transactions_artist_id_created_at", "artist_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # NULL for GRANT rows, which are not about any particular artist.
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(8))

    cash_delta_cents: Mapped[int]
    # Signed, so a negative position (shorting, deferred) is representable
    # without a schema change.
    share_delta: Mapped[int] = mapped_column(server_default=text("0"))
    exec_price_cents: Mapped[int | None] = mapped_column(nullable=True)

    index_score_at_trade: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_value_cents_at_trade: Mapped[int | None] = mapped_column(nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PositionCache(Base):
    """Derived from the ledger, written in the SAME transaction as the
    ledger append under `SELECT ... FOR UPDATE` on the artist row
    (CLAUDE.md rule 8). `v_positions` is the definition of truth; this is
    an O(1) read path. Never update it independently.
    """

    __tablename__ = "position_cache"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )

    shares: Mapped[int] = mapped_column(server_default=text("0"))
    # Micro-cents: a weighted-average cost basis needs sub-cent precision
    # to avoid drift over many trades. Divided down at the display boundary.
    avg_cost_microcents: Mapped[int] = mapped_column(server_default=text("0"))
    realized_pnl_cents: Mapped[int] = mapped_column(server_default=text("0"))
    # Shares bought while the artist was below the Talent Scout discovery
    # thresholds — the basis of the scout leaderboard.
    scout_shares: Mapped[int] = mapped_column(server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class BalanceCache(Base):
    __tablename__ = "balance_cache"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    cash_cents: Mapped[int] = mapped_column(server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FlaggedArtist(Base):
    """Oracle-manipulation review queue (Phase 3).

    A flagged artist's index score is *held at its previous value* until
    cleared — not zeroed, not deleted. Fail-safe by design: a false
    positive costs one day of staleness, a true positive costs the attacker
    their entire thesis.
    """

    __tablename__ = "flagged_artists"

    artist_id: Mapped[int] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)

    reason: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, object]] = mapped_column(JsonB, server_default=text("'{}'::jsonb"))
    cleared_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
