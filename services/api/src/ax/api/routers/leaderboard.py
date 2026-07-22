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

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

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

    # `LIMIT` in SQL, not a Python slice after the fact -- with the
    # `(as_of_date, equity_cents)` index this reads only the top `TOP_N`
    # rows instead of sorting and materializing every user in the table on
    # every anonymous page load.
    top_stmt = (
        select(User.id, User.username, EquitySnapshot.equity_cents)
        .join(EquitySnapshot, EquitySnapshot.user_id == User.id)
        .where(EquitySnapshot.as_of_date == latest_date)
        .order_by(EquitySnapshot.equity_cents.desc())
        .limit(TOP_N)
    )

    rows = [
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
        for rank, (user_id, username, equity_cents) in enumerate(db.execute(top_stmt), start=1)
    ]

    you = next((row for row in rows if row.is_you), None)
    if you is None and user is not None:
        you = _find_you_portfolio(db, latest_date, user)

    return PortfolioLeaderboardResponse(as_of_date=latest_date.isoformat(), rows=rows, you=you)


def _find_you_portfolio(
    db: DbSession, latest_date: date, user: User
) -> PortfolioLeaderboardRow | None:
    """The caller's own rank when it falls outside `TOP_N` -- a row lookup
    plus a `COUNT`, not a re-run of the full ranked query, so a logged-in
    visitor never forces a full-table scan just to see their own rank."""
    my_equity = db.scalar(
        select(EquitySnapshot.equity_cents).where(
            EquitySnapshot.user_id == user.id, EquitySnapshot.as_of_date == latest_date
        )
    )
    if my_equity is None:
        return None

    rank = (
        db.scalar(
            select(func.count())
            .select_from(EquitySnapshot)
            .where(
                EquitySnapshot.as_of_date == latest_date,
                EquitySnapshot.equity_cents > my_equity,
            )
        )
        + 1
    )
    return PortfolioLeaderboardRow(
        rank=rank, username=user.username, return_bps=_return_bps(my_equity), is_you=True
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

    # `as_of_date` filter kept explicit here even though the nightly job
    # (jobs/leaderboard.py) currently guarantees every row shares one date
    # via delete-all-then-insert -- this endpoint shouldn't rely on that
    # invariant holding forever to avoid silently mixing two nights' rows.
    # `LIMIT` in SQL for the same reason as the portfolio endpoint above.
    top_stmt = (
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
        .where(LeaderboardScout.as_of_date == latest_date)
        .order_by(LeaderboardScout.return_bps.desc())
        .limit(TOP_N)
    )

    rows = [
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
            enumerate(db.execute(top_stmt), start=1)
        )
    ]

    you = next((row for row in rows if row.is_you), None)
    if you is None and user is not None:
        you = _find_you_scout(db, latest_date, user)

    return ScoutLeaderboardResponse(as_of_date=latest_date.isoformat(), rows=rows, you=you)


def _find_you_scout(db: DbSession, latest_date: date, user: User) -> ScoutLeaderboardRow | None:
    """Same shape as `_find_you_portfolio` -- the caller's own scout row
    when it falls outside `TOP_N`, without re-running the full query."""
    my_row = db.execute(
        select(
            Artist.slug,
            Artist.name,
            LeaderboardScout.entry_price_cents,
            LeaderboardScout.return_bps,
        )
        .select_from(LeaderboardScout)
        .join(Artist, Artist.id == LeaderboardScout.best_artist_id)
        .where(LeaderboardScout.user_id == user.id, LeaderboardScout.as_of_date == latest_date)
    ).first()
    if my_row is None:
        return None
    artist_slug, artist_name, entry_price_cents, return_bps = my_row

    rank = (
        db.scalar(
            select(func.count())
            .select_from(LeaderboardScout)
            .where(
                LeaderboardScout.as_of_date == latest_date,
                LeaderboardScout.return_bps > return_bps,
            )
        )
        + 1
    )
    return ScoutLeaderboardRow(
        rank=rank,
        username=user.username,
        artist_slug=artist_slug,
        artist_name=artist_name,
        entry_price_cents=entry_price_cents,
        return_bps=return_bps,
        is_you=True,
    )
