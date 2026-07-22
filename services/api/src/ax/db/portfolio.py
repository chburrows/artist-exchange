"""Shared "mark every position to spot" computation.

Originally lived only in `api/routers/portfolio.py::get_portfolio`.
`jobs/leaderboard.py` needs the exact same cash-plus-positions-at-spot
number for every user, every night, to write `equity_snapshots` --
duplicating the loop would let the two drift on what "equity" even means
(e.g. one of them forgetting a delisted artist's position still marks to
its last price). Factored out so there is exactly one implementation.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.core.money import uc_to_cents_nearest
from ax.db.market import latest_price_history_rows, spot_cents
from ax.db.models import Artist, BalanceCache, PositionCache


@dataclass(frozen=True)
class PositionSnapshot:
    artist_id: int
    artist_slug: str
    artist_name: str
    shares: int
    avg_cost_cents: int
    spot_price_cents: int
    market_value_cents: int
    unrealized_pnl_cents: int
    realized_pnl_cents: int
    scout_shares: int


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash_cents: int
    equity_cents: int
    positions: list[PositionSnapshot] = field(default_factory=list)


def compute_portfolio_snapshot(session: Session, user_id: int, now: datetime) -> PortfolioSnapshot:
    """Cash plus every held position, marked to the current spot price --
    reads only `balance_cache`/`position_cache`, the O(1) derived-from-
    the-ledger path (CLAUDE.md rule 8), never the ledger itself."""
    balance = session.get(BalanceCache, user_id)
    cash_cents = balance.cash_cents if balance is not None else 0

    position_rows = list(
        session.scalars(
            select(PositionCache).where(PositionCache.user_id == user_id, PositionCache.shares > 0)
        )
    )
    artist_ids = [row.artist_id for row in position_rows]
    artists = {a.id: a for a in session.scalars(select(Artist).where(Artist.id.in_(artist_ids)))}
    price_rows = latest_price_history_rows(session, artist_ids)

    positions: list[PositionSnapshot] = []
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
            PositionSnapshot(
                artist_id=artist.id,
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

    return PortfolioSnapshot(cash_cents=cash_cents, equity_cents=equity_cents, positions=positions)
