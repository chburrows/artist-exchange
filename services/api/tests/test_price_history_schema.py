"""Schema guarantees for `price_history`.

These pin a decision that deviates from PLAN.md's stated `PK (artist_id,
at)`, so the reasoning has to live somewhere executable — otherwise a
future reader "restores" the documented key and silently reintroduces both
bugs below.

Phase 4 writes to this table; nothing does yet. These tests exercise the
schema directly so the guarantees are locked in before the code that
depends on them exists.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.db.models import PriceHistory
from tests.conftest import ArtistFactory

SAME_INSTANT = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)


def test_two_events_at_the_same_instant_are_allowed(
    session: Session, make_artist: ArtistFactory
) -> None:
    """With `PK (artist_id, at)` the second row raised a unique violation —
    rejecting a user's trade for a reason unrelated to their trade.

    Reachable despite the `SELECT ... FOR UPDATE` artist lock, because
    `now()` is transaction-start time and the lock is acquired after the
    transaction begins.
    """
    artist = make_artist("Contended")

    session.add_all(
        [
            PriceHistory(
                artist_id=artist.id,
                at=SAME_INSTANT,
                market_price_cents=1000,
                net_supply=1,
                source="trade",
            ),
            PriceHistory(
                artist_id=artist.id,
                at=SAME_INSTANT,
                market_price_cents=1100,
                net_supply=2,
                source="trade",
            ),
        ]
    )
    session.flush()

    rows = session.scalars(select(PriceHistory).where(PriceHistory.artist_id == artist.id)).all()
    assert len(rows) == 2


def test_id_breaks_ties_in_insertion_order(session: Session, make_artist: ArtistFactory) -> None:
    """`ORDER BY at, id` must be stable for genuinely simultaneous events,
    so the chart never renders two same-instant rows in arbitrary order."""
    artist = make_artist("Simultaneous")

    for supply in (1, 2, 3):
        session.add(
            PriceHistory(
                artist_id=artist.id,
                at=SAME_INSTANT,
                market_price_cents=1000 + supply,
                net_supply=supply,
                source="trade",
            )
        )
        session.flush()

    ordered = session.scalars(
        select(PriceHistory)
        .where(PriceHistory.artist_id == artist.id)
        .order_by(PriceHistory.at, PriceHistory.id)
    ).all()

    assert [row.net_supply for row in ordered] == [1, 2, 3]


def test_at_defaults_to_statement_time_not_transaction_time(
    session: Session, make_artist: ArtistFactory
) -> None:
    """The column default must be `clock_timestamp()`, not `now()`.

    `now()` is frozen at transaction start, so two rows inserted at
    different moments in one transaction would carry identical timestamps —
    and under lock contention a row's timestamp would record when the trade
    *queued* rather than when it executed, inverting the series order.
    """
    artist = make_artist("Timed")

    first = PriceHistory(artist_id=artist.id, market_price_cents=1000, net_supply=1, source="trade")
    session.add(first)
    session.flush()

    # Force real time to pass within the same transaction.
    session.execute(select(1).select_from(select(1).subquery()))
    import time

    time.sleep(0.01)

    second = PriceHistory(
        artist_id=artist.id, market_price_cents=1100, net_supply=2, source="trade"
    )
    session.add(second)
    session.flush()
    session.refresh(first)
    session.refresh(second)

    # Under `now()` these would be byte-identical.
    assert second.at > first.at
