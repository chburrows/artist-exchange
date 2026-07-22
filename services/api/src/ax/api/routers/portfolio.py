"""`GET /portfolio` (PLAN.md Phase 4): cash plus every held position,
marked to the current spot price. `GET /portfolio/history` (Phase 6):
the daily equity series `jobs/leaderboard.py` snapshots nightly, behind
the Portfolio page's range-selector chart.

Reads `balance_cache`/`position_cache` -- the O(1) derived-from-the-
ledger path (CLAUDE.md rule 8) -- never the ledger itself. A portfolio
page hit on every load is exactly the hot path those caches exist for;
`jobs/reconcile.py` is what keeps them trustworthy.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ax.api.deps import CurrentUserDep, DbDep
from ax.db.models import EquitySnapshot
from ax.db.portfolio import compute_portfolio_snapshot

router = APIRouter(tags=["portfolio"])


class PortfolioPosition(BaseModel):
    artist_slug: str
    artist_name: str
    shares: int
    avg_cost_cents: int
    spot_price_cents: int
    market_value_cents: int
    unrealized_pnl_cents: int
    realized_pnl_cents: int
    scout_shares: int


class PortfolioResponse(BaseModel):
    cash_cents: int
    equity_cents: int
    positions: list[PortfolioPosition]


@router.get("/portfolio")
def get_portfolio(db: DbDep, user: CurrentUserDep) -> PortfolioResponse:
    snapshot = compute_portfolio_snapshot(db, user.id, datetime.now(UTC))
    return PortfolioResponse(
        cash_cents=snapshot.cash_cents,
        equity_cents=snapshot.equity_cents,
        positions=[
            PortfolioPosition(
                artist_slug=p.artist_slug,
                artist_name=p.artist_name,
                shares=p.shares,
                avg_cost_cents=p.avg_cost_cents,
                spot_price_cents=p.spot_price_cents,
                market_value_cents=p.market_value_cents,
                unrealized_pnl_cents=p.unrealized_pnl_cents,
                realized_pnl_cents=p.realized_pnl_cents,
                scout_shares=p.scout_shares,
            )
            for p in snapshot.positions
        ],
    )


class EquityPoint(BaseModel):
    as_of_date: str
    equity_cents: int
    cash_cents: int


class PortfolioHistoryResponse(BaseModel):
    points: list[EquityPoint]


@router.get("/portfolio/history")
def get_portfolio_history(db: DbDep, user: CurrentUserDep) -> PortfolioHistoryResponse:
    """Real daily equity, oldest first -- written by `jobs/leaderboard.py`,
    not computed live. A brand-new account, or one that signed up before
    tonight's job has run once, legitimately has zero points: the
    frontend's `PortfolioValueChart` already renders an honest "not
    enough history yet" state for fewer than two points, so there is
    nothing to backfill or fake here (CLAUDE.md: an honest absence beats
    a stub)."""
    stmt = (
        select(EquitySnapshot)
        .where(EquitySnapshot.user_id == user.id)
        .order_by(EquitySnapshot.as_of_date)
    )
    return PortfolioHistoryResponse(
        points=[
            EquityPoint(
                as_of_date=row.as_of_date.isoformat(),
                equity_cents=row.equity_cents,
                cash_cents=row.cash_cents,
            )
            for row in db.scalars(stmt)
        ]
    )
