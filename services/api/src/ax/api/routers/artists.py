"""Read-only artist endpoints (PLAN.md Phase 4): `GET /artists`,
`GET /artists/{slug}`, `GET /artists/{slug}/history` -- the data Phase
5's artist list, artist page, and signature dual-line chart (market
price solid, index fair value dashed) are built from.

Public, no auth -- browsing the universe and a chart should not require
an account. `warming_up` artists (not yet listed) are absent from every
endpoint here, same as PLAN.md's listing rule: there is no price to
quote and nothing to chart until `MIN_SNAPSHOTS_TO_LIST` is met.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.api.deps import DbDep
from ax.db.market import latest_index_snapshots, latest_price_history_rows, spot_cents
from ax.db.models import TIER_BLUE_CHIP, TIER_GROWTH, Artist, IndexSnapshot, PriceHistory

router = APIRouter(prefix="/artists", tags=["artists"])

_VALID_TIERS = {TIER_GROWTH, TIER_BLUE_CHIP}


class ArtistOut(BaseModel):
    slug: str
    name: str
    tier: str
    listed_at: datetime
    spot_price_cents: int
    net_supply: int
    index_score: float | None
    fair_value_cents: int | None


class HistoryPoint(BaseModel):
    at: datetime
    market_price_cents: int
    fair_value_cents: int | None
    net_supply: int
    source: str


class HistoryResponse(BaseModel):
    artist: ArtistOut
    points: list[HistoryPoint]


def _listed_artists_query(tier: str | None) -> Any:
    stmt = select(Artist).where(Artist.listed_at.is_not(None), Artist.delisted_at.is_(None))
    if tier is not None:
        stmt = stmt.where(Artist.tier == tier)
    return stmt.order_by(Artist.slug)


def _to_out(
    artist: Artist,
    now: datetime,
    price_rows: dict[int, PriceHistory],
    index_rows: dict[int, IndexSnapshot],
) -> ArtistOut:
    price_row = price_rows.get(artist.id)
    net_supply = price_row.net_supply if price_row is not None else 0
    index_row = index_rows.get(artist.id)
    assert artist.listed_at is not None  # every caller pre-filters on this
    return ArtistOut(
        slug=artist.slug,
        name=artist.name,
        tier=artist.tier,
        listed_at=artist.listed_at,
        spot_price_cents=spot_cents(artist, net_supply, now),
        net_supply=net_supply,
        index_score=index_row.index_score if index_row is not None else None,
        fair_value_cents=index_row.fair_value_cents if index_row is not None else None,
    )


@router.get("")
def list_artists(
    db: DbDep,
    tier: str | None = Query(default=None),
) -> list[ArtistOut]:
    if tier is not None and tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"tier must be one of {sorted(_VALID_TIERS)}",
        )

    now = datetime.now(UTC)
    artists = list(db.scalars(_listed_artists_query(tier)))
    artist_ids = [a.id for a in artists]
    price_rows = latest_price_history_rows(db, artist_ids)
    index_rows = latest_index_snapshots(db, artist_ids)

    return [_to_out(a, now, price_rows, index_rows) for a in artists]


def _get_listed_artist(db: Session, slug: str) -> Artist:
    artist = db.scalars(select(Artist).where(Artist.slug == slug)).one_or_none()
    if artist is None or artist.listed_at is None or artist.delisted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artist not found")
    return artist


@router.get("/{slug}")
def get_artist(slug: str, db: DbDep) -> ArtistOut:
    now = datetime.now(UTC)
    artist = _get_listed_artist(db, slug)
    price_rows = latest_price_history_rows(db, [artist.id])
    index_rows = latest_index_snapshots(db, [artist.id])
    return _to_out(artist, now, price_rows, index_rows)


@router.get("/{slug}/history")
def get_artist_history(slug: str, db: DbDep) -> HistoryResponse:
    now = datetime.now(UTC)
    artist = _get_listed_artist(db, slug)
    price_rows = latest_price_history_rows(db, [artist.id])
    index_rows = latest_index_snapshots(db, [artist.id])

    stmt = (
        select(PriceHistory)
        .where(PriceHistory.artist_id == artist.id)
        .order_by(PriceHistory.at, PriceHistory.id)
    )
    points = [
        HistoryPoint(
            at=row.at,
            market_price_cents=row.market_price_cents,
            fair_value_cents=row.fair_value_cents,
            net_supply=row.net_supply,
            source=row.source,
        )
        for row in db.scalars(stmt)
    ]

    return HistoryResponse(
        artist=_to_out(artist, now, price_rows, index_rows),
        points=points,
    )
