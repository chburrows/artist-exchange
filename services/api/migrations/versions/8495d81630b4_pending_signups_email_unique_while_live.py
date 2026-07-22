"""pending signups email unique while live

Revision ID: 8495d81630b4
Revises: 4a63168fc719
Create Date: 2026-07-22 16:18:18.956430

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8495d81630b4"
down_revision: str | None = "4a63168fc719"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `request_signup`'s "at most one live pending signup per address"
    # invariant was previously app-level only (delete-then-insert, no lock),
    # so two concurrent requests for the same new email could both insert.
    # A partial unique index makes the DB reject the second one instead --
    # `request_signup` now does a single `INSERT ... ON CONFLICT` against
    # this exact index rather than a separate delete.
    op.create_index(
        "uq_pending_signups_email_live",
        "pending_signups",
        ["email"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pending_signups_email_live", table_name="pending_signups")
