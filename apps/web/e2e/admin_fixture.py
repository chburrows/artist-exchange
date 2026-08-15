"""Test fixture for the admin review-queue spec (`admin-review-queue.spec.ts`).

Seeds the one state the spec needs that neither an HTTP endpoint nor a
CLI command can produce: an **open** `flagged_artists` row.
`flagged_artists` is written by the nightly recompute when it detects an
anomaly, and `ax fake-history` auto-clears every flag its synthetic data
raises -- so a freshly reset database has cleared history but an empty
open queue, and the clear-flow has nothing to act on.

(The spec's other precondition, an admin account, needs no fixture:
`ax promote-admin` is already the real, only grant path.)

Runs against the same `DATABASE_URL` the servers use, through the real
models -- never raw SQL, so a schema change breaks this loudly instead
of silently seeding a shape the app can't read.
"""

import sys
from datetime import date

from sqlalchemy import select

from ax.db.models import Artist, FlaggedArtist
from ax.db.session import session_scope


def open_flag(slug: str, as_of: date) -> None:
    """Idempotent on `(artist_id, as_of_date)` so a retried spec doesn't
    hit the table's primary key."""
    with session_scope() as session:
        artist = session.scalar(select(Artist).where(Artist.slug == slug))
        if artist is None:
            raise SystemExit(f"no such artist: {slug}")
        existing = session.get(FlaggedArtist, (artist.id, as_of))
        if existing is not None:
            existing.cleared_at = None
            existing.cleared_by = None
            return
        session.add(
            FlaggedArtist(
                artist_id=artist.id,
                as_of_date=as_of,
                reason="ratio_divergence,percentile_move",
                detail={
                    "ratio_divergence": {"divergence": 1.75, "z": 4.2},
                    "percentile_move": {"delta": 0.91, "threshold": 0.44},
                },
            )
        )


if __name__ == "__main__":
    slug, as_of = sys.argv[1:]
    open_flag(slug, date.fromisoformat(as_of))
