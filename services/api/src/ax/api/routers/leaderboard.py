"""`GET /leaderboard/portfolio` and `GET /leaderboard/scout` (PLAN.md
Phase 6). Both read tables `jobs/leaderboard.py` refreshes nightly, never
compute live -- "leaderboards are the one place staleness is genuinely
fine" (PLAN.md).

Public: browsing the rankings needs no account. `CurrentUserOptionalDep`
lets a logged-in caller also get their own row (`you`) even when it falls
outside the top slice returned in `rows`, without requiring a second
request or forcing every visitor to be authenticated just to see who's
winning.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from ax.api.deps import CurrentUserOptionalDep, DbDep
from ax.core.config import STARTING_BALANCE_CENTS
from ax.db.models import Artist, EquitySnapshot, LeaderboardScout, User

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

TOP_N = 25


class PortfolioLeaderboardRow(BaseModel):
    rank: int
    username: str
    return_bps: int
    is_you: bool


class PortfolioLeaderboardResponse(BaseModel):
    as_of_date: str | None
    rows: list[PortfolioLeaderboardRow]
    you: PortfolioLeaderboardRow | None


def _return_bps(equity_cents: int) -> int:
    return (equity_cents - STARTING_BALANCE_CENTS) * 10_000 // STARTING_BALANCE_CENTS


@router.get("/portfolio")
def get_portfolio_leaderboard(
    db: DbDep, user: CurrentUserOptionalDep
) -> PortfolioLeaderboardResponse:
    latest_date = db.scalar(select(func.max(EquitySnapshot.as_of_date)))
    if latest_date is None:
        # No nightly snapshot has ever run -- an honest empty state, not a
        # fabricated ranking (CLAUDE.md: an absence beats a stub).
        return PortfolioLeaderboardResponse(as_of_date=None, rows=[], you=None)

    stmt = (
        select(User.id, User.username, EquitySnapshot.equity_cents)
        .join(EquitySnapshot, EquitySnapshot.user_id == User.id)
        .where(EquitySnapshot.as_of_date == latest_date)
        .order_by(EquitySnapshot.equity_cents.desc())
    )

    all_rows = [
        PortfolioLeaderboardRow(
            rank=rank,
            username=username,
            # `equity_cents` (used only to derive this) is deliberately
            # not in the response -- a public leaderboard should show
            # other users' relative performance, not their exact play-
            # money balance.
            return_bps=_return_bps(equity_cents),
            is_you=user is not None and user_id == user.id,
        )
        for rank, (user_id, username, equity_cents) in enumerate(db.execute(stmt), start=1)
    ]

    you = next((row for row in all_rows if row.is_you), None)
    return PortfolioLeaderboardResponse(
        as_of_date=latest_date.isoformat(), rows=all_rows[:TOP_N], you=you
    )


class ScoutLeaderboardRow(BaseModel):
    rank: int
    username: str
    artist_slug: str
    artist_name: str
    entry_price_cents: int
    return_bps: int
    is_you: bool


class ScoutLeaderboardResponse(BaseModel):
    as_of_date: str | None
    rows: list[ScoutLeaderboardRow]
    you: ScoutLeaderboardRow | None


@router.get("/scout")
def get_scout_leaderboard(db: DbDep, user: CurrentUserOptionalDep) -> ScoutLeaderboardResponse:
    latest_date = db.scalar(select(func.max(LeaderboardScout.as_of_date)))
    if latest_date is None:
        return ScoutLeaderboardResponse(as_of_date=None, rows=[], you=None)

    stmt = (
        select(
            User.id,
            User.username,
            Artist.slug,
            Artist.name,
            LeaderboardScout.entry_price_cents,
            LeaderboardScout.return_bps,
        )
        .select_from(LeaderboardScout)
        .join(User, User.id == LeaderboardScout.user_id)
        .join(Artist, Artist.id == LeaderboardScout.best_artist_id)
        .order_by(LeaderboardScout.return_bps.desc())
    )

    all_rows = [
        ScoutLeaderboardRow(
            rank=rank,
            username=username,
            artist_slug=artist_slug,
            artist_name=artist_name,
            entry_price_cents=entry_price_cents,
            return_bps=return_bps,
            is_you=user is not None and user_id == user.id,
        )
        for rank, (user_id, username, artist_slug, artist_name, entry_price_cents, return_bps) in (
            enumerate(db.execute(stmt), start=1)
        )
    ]

    you = next((row for row in all_rows if row.is_you), None)
    return ScoutLeaderboardResponse(
        as_of_date=latest_date.isoformat(), rows=all_rows[:TOP_N], you=you
    )
