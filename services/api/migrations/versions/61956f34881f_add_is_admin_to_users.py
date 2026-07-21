"""add is_admin to users

Revision ID: 61956f34881f
Revises: 8981d053248e
Create Date: 2026-07-21 15:24:54.363343

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "61956f34881f"
down_revision: str | None = "8981d053248e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Gates the new /admin/* endpoints (`api/deps.py::get_current_admin_user`).
    # No code path anywhere sets this to true except `ax promote-admin`,
    # run by someone who already has database/deploy access -- there is
    # deliberately no self-service or first-user-is-admin path. Defaults
    # false so every existing and future signup starts unprivileged.
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
