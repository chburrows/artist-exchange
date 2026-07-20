"""Read helpers for "what is this artist's price right now" -- shared by
the trade route, the artist listing/detail routes, and portfolio
mark-to-market, so there is exactly one place that knows how to turn an
`Artist` row's stored glide state into a live spot price.
"""

from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ax.core.amm import effective_anchor_uc, spot_price_uc
from ax.core.money import cents_to_uc, uc_to_cents_nearest
from ax.db.models import Artist, IndexSnapshot, PositionCache, PriceHistory, Transaction


def latest_price_history_rows(session: Session, artist_ids: list[int]) -> dict[int, PriceHistory]:
    """Each artist's most recent `price_history` row. Its `net_supply` is
    the authoritative current supply for any *already-listed* artist:
    the only events that change supply are trades, and every one writes
    a `price_history` row in the same transaction (under the artist's
    `FOR UPDATE` lock) that updates it -- so this is equivalent to
    `SUM(share_delta)` over `transactions` for that artist, cheaper, and
    (for a caller already holding that lock) exactly as current.

    A listed artist always has at least one row (written at listing), so
    an artist missing here is either unlisted or a caller passed a bad
    id -- never a gap to paper over with a default.
    """
    if not artist_ids:
        return {}
    stmt = (
        select(PriceHistory)
        .distinct(PriceHistory.artist_id)
        .where(PriceHistory.artist_id.in_(artist_ids))
        .order_by(PriceHistory.artist_id, PriceHistory.at.desc(), PriceHistory.id.desc())
    )
    return {row.artist_id: row for row in session.scalars(stmt)}


def net_supplies_from_ledger(session: Session, artist_ids: list[int]) -> dict[int, int]:
    """The same quantity as `latest_price_history_rows(...).net_supply`,
    derived independently from the ledger instead -- used by
    `jobs/reconcile.py` to check the shortcut above against the source
    of truth, never on a request path."""
    if not artist_ids:
        return {}
    stmt = (
        select(Transaction.artist_id, func.sum(Transaction.share_delta))
        .where(Transaction.artist_id.in_(artist_ids))
        .group_by(Transaction.artist_id)
    )
    return {artist_id: int(total) for artist_id, total in session.execute(stmt)}


def effective_anchor_uc_now(artist: Artist, now: datetime) -> int:
    """The artist's current interpolated anchor, in microcents -- the raw
    input the AMM's `buy_quote`/`sell_quote` need. Requires a listed
    artist (`anchor_cents`/glide fields set at listing -- see
    `jobs/recompute.py`)."""
    assert artist.anchor_cents is not None
    assert artist.anchor_target_cents is not None
    assert artist.glide_start_at is not None
    assert artist.glide_end_at is not None

    return effective_anchor_uc(
        cents_to_uc(artist.anchor_cents),
        cents_to_uc(artist.anchor_target_cents),
        artist.glide_start_at,
        artist.glide_end_at,
        now,
    )


def spot_cents(artist: Artist, net_supply: int, now: datetime) -> int:
    """Current marginal spot price for the *next* share, in cents."""
    assert artist.slope_microcents_per_share is not None
    eff_uc = effective_anchor_uc_now(artist, now)
    return uc_to_cents_nearest(spot_price_uc(eff_uc, artist.slope_microcents_per_share, net_supply))


def latest_index_snapshots(session: Session, artist_ids: list[int]) -> dict[int, IndexSnapshot]:
    """Each artist's most recent published `index_snapshots` row --
    listing/artist-detail read path. Unlike
    `jobs/recompute.py._latest_prior_index_snapshots`, there's no
    `as_of_date` cutoff: this always wants the latest one that exists,
    including today's."""
    if not artist_ids:
        return {}
    stmt = (
        select(IndexSnapshot)
        .distinct(IndexSnapshot.artist_id)
        .where(IndexSnapshot.artist_id.in_(artist_ids))
        .order_by(IndexSnapshot.artist_id, IndexSnapshot.as_of_date.desc())
    )
    return {row.artist_id: row for row in session.scalars(stmt)}


def distinct_artist_ids_with_positions(session: Session, user_id: int) -> list[int]:
    stmt = select(distinct(PositionCache.artist_id)).where(
        PositionCache.user_id == user_id, PositionCache.shares > 0
    )
    return list(session.scalars(stmt))
