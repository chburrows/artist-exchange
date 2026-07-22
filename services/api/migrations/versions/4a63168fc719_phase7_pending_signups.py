"""phase7 pending signups

Revision ID: 4a63168fc719
Revises: 8900c4e149ac
Create Date: 2026-07-22 15:33:01.778608

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a63168fc719"
down_revision: str | None = "8900c4e149ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Verify-before-create signup (PLAN.md Phase 7): a request holds here,
    # unconsumed, until the emailed link is clicked -- see
    # `ax.db.models.PendingSignup` for why this is a separate table from
    # `magic_links` rather than a repurposed row there.
    op.create_table(
        "pending_signups",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("requested_username", postgresql.CITEXT(), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_signups")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_pending_signups_token_hash")),
    )
    op.create_index(op.f("ix_pending_signups_email"), "pending_signups", ["email"], unique=False)

    # `users.email` is mandatory from this point on. This will fail if any
    # row still has a NULL email -- deliberately: PLAN.md's "Removing
    # existing users" section makes resetting every user-scoped row a
    # documented *precondition* for this migration, run as a one-time
    # manual statement against each environment (`ax reset` locally; a
    # confirmed TRUNCATE against Railway, never baked into a migration
    # that replays from scratch in CI and every fresh dev/test database).
    op.alter_column("users", "email", existing_type=postgresql.CITEXT(), nullable=False)


def downgrade() -> None:
    op.alter_column("users", "email", existing_type=postgresql.CITEXT(), nullable=True)
    op.drop_index(op.f("ix_pending_signups_email"), table_name="pending_signups")
    op.drop_table("pending_signups")
