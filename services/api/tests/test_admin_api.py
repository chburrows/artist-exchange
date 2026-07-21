"""`GET /admin/flagged-artists` and `POST /admin/flagged-artists/{...}/clear`
-- the admin view PLAN.md's Phase 3 follow-up asks for ("surface
`flagged_artists` in an admin view instead of relying on direct DB access
indefinitely"). `is_admin` has no self-service path (only `ax
promote-admin`), so tests flip it directly on the session-bound `User` row
after signup, the same trust boundary the real CLI command sits behind.
"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.db.models import FlaggedArtist, User
from tests.conftest import ArtistFactory

FLAG_DATE = date(2026, 1, 1)


def _signup(client: TestClient, username: str) -> dict:
    response = client.post("/auth/signup", json={"username": username})
    assert response.status_code == 201
    return response.json()


def _make_admin(session: Session, username: str) -> None:
    user = session.scalar(select(User).where(User.username == username))
    assert user is not None
    user.is_admin = True
    session.flush()


def test_flagged_artists_requires_auth(client: TestClient) -> None:
    assert client.get("/admin/flagged-artists").status_code == 401


def test_flagged_artists_requires_admin(client: TestClient) -> None:
    _signup(client, "regular-joe")

    response = client.get("/admin/flagged-artists")

    assert response.status_code == 403


def test_clear_requires_admin(client: TestClient) -> None:
    _signup(client, "regular-jane")

    response = client.post("/admin/flagged-artists/1/2026-01-01/clear")

    assert response.status_code == 403


def test_admin_lists_open_flags_only_by_default(
    client: TestClient, session: Session, make_artist: ArtistFactory
) -> None:
    _signup(client, "reviewer")
    _make_admin(session, "reviewer")

    open_artist = make_artist("Open Flag")
    cleared_artist = make_artist("Cleared Flag")
    session.add(
        FlaggedArtist(
            artist_id=open_artist.id,
            as_of_date=FLAG_DATE,
            reason="percentile_move",
            detail={"delta": 1.0},
        )
    )
    session.add(
        FlaggedArtist(
            artist_id=cleared_artist.id,
            as_of_date=FLAG_DATE,
            reason="ratio_divergence",
            cleared_at=datetime.now(UTC),
            cleared_by="someone@example.com",
        )
    )
    session.flush()

    response = client.get("/admin/flagged-artists")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["artist_slug"] == open_artist.slug
    assert body[0]["cleared_at"] is None

    response_all = client.get("/admin/flagged-artists", params={"include_cleared": True})
    assert {row["artist_slug"] for row in response_all.json()} == {
        open_artist.slug,
        cleared_artist.slug,
    }


def test_admin_clears_a_flag(
    client: TestClient, session: Session, make_artist: ArtistFactory
) -> None:
    _signup(client, "reviewer2")
    _make_admin(session, "reviewer2")

    artist = make_artist("To Clear")
    session.add(FlaggedArtist(artist_id=artist.id, as_of_date=FLAG_DATE, reason="percentile_move"))
    session.flush()

    response = client.post(f"/admin/flagged-artists/{artist.id}/{FLAG_DATE.isoformat()}/clear")

    assert response.status_code == 200
    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist.id, FlaggedArtist.as_of_date == FLAG_DATE
        )
    )
    assert flag is not None
    assert flag.cleared_at is not None
    assert flag.cleared_by == "reviewer2"

    # Gone from the open list now.
    assert client.get("/admin/flagged-artists").json() == []


def test_clearing_a_nonexistent_flag_404s(client: TestClient, session: Session) -> None:
    _signup(client, "reviewer3")
    _make_admin(session, "reviewer3")

    response = client.post(f"/admin/flagged-artists/999999/{FLAG_DATE.isoformat()}/clear")

    assert response.status_code == 404
