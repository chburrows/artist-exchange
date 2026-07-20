"""`GET /portfolio` (PLAN.md Phase 4): cash plus every held position,
marked to the current spot price.

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
from ax.core.money import uc_to_cents_nearest
from ax.db.market import latest_price_history_rows, spot_cents
from ax.db.models import Artist, BalanceCache, PositionCache

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
    now = datetime.now(UTC)

    balance = db.get(BalanceCache, user.id)
    cash_cents = balance.cash_cents if balance is not None else 0

    position_rows = list(
        db.scalars(
            select(PositionCache).where(PositionCache.user_id == user.id, PositionCache.shares > 0)
        )
    )
    artist_ids = [row.artist_id for row in position_rows]
    artists = {a.id: a for a in db.scalars(select(Artist).where(Artist.id.in_(artist_ids)))}
    price_rows = latest_price_history_rows(db, artist_ids)

    positions: list[PortfolioPosition] = []
    equity_cents = cash_cents
    for row in position_rows:
        artist = artists.get(row.artist_id)
        price_row = price_rows.get(row.artist_id)
        if artist is None or price_row is None:
            continue

        spot_price_cents = spot_cents(artist, price_row.net_supply, now)
        market_value_cents = row.shares * spot_price_cents
        avg_cost_cents = uc_to_cents_nearest(row.avg_cost_microcents)
        unrealized_pnl_cents = market_value_cents - row.shares * avg_cost_cents

        equity_cents += market_value_cents
        positions.append(
            PortfolioPosition(
                artist_slug=artist.slug,
                artist_name=artist.name,
                shares=row.shares,
                avg_cost_cents=avg_cost_cents,
                spot_price_cents=spot_price_cents,
                market_value_cents=market_value_cents,
                unrealized_pnl_cents=unrealized_pnl_cents,
                realized_pnl_cents=row.realized_pnl_cents,
                scout_shares=row.scout_shares,
            )
        )

    return PortfolioResponse(cash_cents=cash_cents, equity_cents=equity_cents, positions=positions)
