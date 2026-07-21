"""Admin-only oracle-manipulation review queue (PLAN.md Phase 3 follow-up:
"surface `flagged_artists` in an admin view instead of relying on direct
DB access indefinitely").

`flagged_artists` quarantines an artist's fair value at its previous
value until a human clears it (`jobs/recompute.py`) -- until this router
existed, "a human clears it" meant hand-editing the row over `psql`. These
two endpoints are that admin view's backend: list the open queue, clear
one entry. `jobs/recompute.clear_flag` does the actual write, shared with
`cli.py`'s `fake-history` auto-clear so the update logic exists once.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from ax.api.deps import CurrentAdminDep, DbDep
from ax.db.models import Artist, FlaggedArtist
from ax.jobs.recompute import clear_flag

router = APIRouter(prefix="/admin", tags=["admin"])


class FlaggedArtistOut(BaseModel):
    artist_id: int
    artist_slug: str
    as_of_date: date
    reason: str
    detail: dict[str, object]
    cleared_at: str | None
    cleared_by: str | None


@router.get("/flagged-artists")
def list_flagged_artists(
    db: DbDep,
    _admin: CurrentAdminDep,
    include_cleared: bool = False,
) -> list[FlaggedArtistOut]:
    stmt = (
        select(FlaggedArtist, Artist.slug)
        .join(Artist, Artist.id == FlaggedArtist.artist_id)
        .order_by(FlaggedArtist.as_of_date.desc())
    )
    if not include_cleared:
        stmt = stmt.where(FlaggedArtist.cleared_at.is_(None))

    return [
        FlaggedArtistOut(
            artist_id=flag.artist_id,
            artist_slug=slug,
            as_of_date=flag.as_of_date,
            reason=flag.reason,
            detail=flag.detail,
            cleared_at=flag.cleared_at.isoformat() if flag.cleared_at else None,
            cleared_by=flag.cleared_by,
        )
        for flag, slug in db.execute(stmt)
    ]


@router.post("/flagged-artists/{artist_id}/{as_of_date}/clear")
def clear_flagged_artist(
    artist_id: int,
    as_of_date: date,
    db: DbDep,
    admin: CurrentAdminDep,
) -> dict[str, str]:
    cleared = clear_flag(db, artist_id, as_of_date, cleared_by=admin.username)
    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no open flag for this artist/date",
        )
    db.commit()
    return {"status": "cleared"}
