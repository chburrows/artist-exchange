"""phase4 auth trading views

Revision ID: 8981d053248e
Revises: c41902cb242e
Create Date: 2026-07-20 11:13:26.239920

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8981d053248e"
down_revision: str | None = "c41902cb242e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `users.email` must be unique for the same reason `username` already
    # is: `consume_magic_link` (api/routers/auth.py) treats an
    # `IntegrityError` on `user.email = link.email` as its signal that a
    # concurrent request already attached this exact address to another
    # account -- a signal only a real unique constraint can ever raise.
    # `email` stays nullable (an unattached account has none); Postgres
    # unique constraints permit any number of NULLs, only non-NULL
    # duplicates are rejected.
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])

    # `magic_links.user_id` -- a deliberate deviation from PLAN.md's
    # literal schema, same category of deviation as price_history's
    # surrogate key. See the docstring on `ax.db.models.MagicLink` for
    # why: without it, an "attach this email" request can't safely defer
    # writing `users.email` until the link is actually clicked, which
    # opens an email-hijack-via-unverified-attach window. No existing
    # `magic_links` rows exist in production (nothing has ever written to
    # this table), so a straight NOT NULL add is safe.
    op.add_column("magic_links", sa.Column("user_id", sa.BigInteger(), nullable=False))
    op.create_index(op.f("ix_magic_links_user_id"), "magic_links", ["user_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_magic_links_user_id_users"),
        "magic_links",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # `v_balances` / `v_positions` -- PLAN.md's "definition of truth"
    # (CLAUDE.md rule 8): plain SUMs over the append-only ledger, never
    # written to directly. `position_cache`/`balance_cache` are the O(1)
    # read path; `jobs/reconcile.py` is what keeps them honest against
    # these views.
    #
    # `v_positions` intentionally sums only `share_delta` (current
    # shares) -- NOT avg_cost/realized_pnl/scout_shares, which are
    # order-dependent (a weighted-average cost basis isn't a SQL
    # aggregate) and can only be rebuilt by replaying `transactions`
    # through `ax.core.ledger.apply_buy`/`apply_sell` in order, which is
    # exactly what `jobs/reconcile.py` does for the cache fields this
    # view can't express.
    op.execute(
        """
        CREATE VIEW v_balances AS
        SELECT user_id, SUM(cash_delta_cents) AS cash_cents
        FROM transactions
        GROUP BY user_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_positions AS
        SELECT user_id, artist_id, SUM(share_delta) AS shares
        FROM transactions
        WHERE artist_id IS NOT NULL
        GROUP BY user_id, artist_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_positions")
    op.execute("DROP VIEW IF EXISTS v_balances")

    op.drop_constraint(op.f("fk_magic_links_user_id_users"), "magic_links", type_="foreignkey")
    op.drop_index(op.f("ix_magic_links_user_id"), table_name="magic_links")
    op.drop_column("magic_links", "user_id")

    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
