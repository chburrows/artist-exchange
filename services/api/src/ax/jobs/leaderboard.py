"""Nightly leaderboard snapshot (PLAN.md Phase 6).

PLAN.md: "Portfolio % return and Talent Scout leaderboards, as a
materialized view refreshed by the nightly job -- leaderboards are the
one place staleness is genuinely fine." Meant to run last in the nightly
Action, after `reconcile` -- it reads `balance_cache`/`position_cache`,
so it wants those already trustworthy for the night.

Two things get written, both via `ax.db.portfolio.compute_portfolio_snapshot`
(the same cash-plus-positions-at-spot computation `GET /portfolio` uses
live, run here once per user instead):

- **`equity_snapshots`** -- one row per user per night, upserted on
  `(user_id, as_of_date)` (CLAUDE.md rule 7's idempotency shape, same as
  `metric_snapshots`). This is real history: `GET /portfolio/history`
  reads it back for the Portfolio page's range-selector chart, and the
  portfolio-return leaderboard ranks off its latest date.
- **`leaderboard_scout`** -- one row per user with a currently-held
  scout-qualified position, holding their single best find (highest
  return %, using the position's blended `avg_cost_cents` -- there is no
  cost basis tracked separately for just the scout-qualified shares).
  Rebuilt from scratch every run (delete-all then insert), not upserted
  incrementally: a user whose best find was sold since last night must
  disappear from the table, not linger with yesterday's row. This is a
  deliberate structural choice after `flagged_artists` taught the same
  lesson the hard way pre-Phase-3-fix -- a table meant to reflect
  *current* state must never be append-only.

No `FOR UPDATE` locking: this job only reads `balance_cache`/
`position_cache`, never writes them. A concurrent trade landing between
this job's read of one user and its write is the same bounded,
self-correcting risk `jobs/reconcile.py` already accepts for its own
lock-free reads -- tomorrow night's snapshot reflects the true state
either way.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ax.db.models import EquitySnapshot, LeaderboardScout, User
from ax.db.portfolio import compute_portfolio_snapshot

log = logging.getLogger(__name__)


@dataclass
class LeaderboardResult:
    as_of_date: date
    users_processed: int = 0
    scout_rows: int = 0

    def summary(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "users_processed": self.users_processed,
            "scout_rows": self.scout_rows,
        }


def run_leaderboard_snapshot(
    session: Session, as_of_date: date, *, now: datetime
) -> LeaderboardResult:
    result = LeaderboardResult(as_of_date=as_of_date)

    # Materialized up front, not a live cursor: the loop commits per user
    # below (same reasoning as jobs/reconcile.py -- a single commit at the
    # end would hold every touched row for the whole run).
    user_ids = list(session.scalars(select(User.id)))

    scout_rows: list[dict[str, object]] = []
    for user_id in user_ids:
        snapshot = compute_portfolio_snapshot(session, user_id, now)

        stmt = insert(EquitySnapshot).values(
            user_id=user_id,
            as_of_date=as_of_date,
            equity_cents=snapshot.equity_cents,
            cash_cents=snapshot.cash_cents,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "as_of_date"],
            set_={
                "equity_cents": stmt.excluded.equity_cents,
                "cash_cents": stmt.excluded.cash_cents,
            },
        )
        session.execute(stmt)

        best_return_bps: int | None = None
        best_position = None
        for position in snapshot.positions:
            # avg_cost_cents == 0 can't happen for a real buy (every trade
            # costs at least 1 cent, C7), but guarding division is cheap
            # insurance against a future data path that could leave one.
            if position.scout_shares <= 0 or position.avg_cost_cents <= 0:
                continue
            return_bps = (
                (position.spot_price_cents - position.avg_cost_cents)
                * 10_000
                // position.avg_cost_cents
            )
            if best_return_bps is None or return_bps > best_return_bps:
                best_return_bps = return_bps
                best_position = position

        if best_position is not None and best_return_bps is not None:
            scout_rows.append(
                {
                    "user_id": user_id,
                    "best_artist_id": best_position.artist_id,
                    "entry_price_cents": best_position.avg_cost_cents,
                    "return_bps": best_return_bps,
                    "scout_shares": best_position.scout_shares,
                    "as_of_date": as_of_date,
                }
            )

        result.users_processed += 1
        session.commit()

    # Full replace, not an upsert -- see module docstring. Both statements
    # run in the same transaction/commit, so no reader ever observes an
    # empty table between the delete and the reinsert.
    session.execute(delete(LeaderboardScout))
    if scout_rows:
        session.execute(insert(LeaderboardScout).values(scout_rows))
    result.scout_rows = len(scout_rows)
    session.commit()

    log.info(
        "leaderboard snapshot for %s: %s users, %s scout rows",
        as_of_date,
        result.users_processed,
        result.scout_rows,
    )
    return result
