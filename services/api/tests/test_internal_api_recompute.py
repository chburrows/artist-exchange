"""`/internal/jobs/recompute`, end to end through the real app.

`test_internal_api.py` already covers the shared router-level concerns
(bearer-token auth, the internal-schema exclusion) generically across
every `/internal/jobs/*` route, since both `/snapshot` and `/recompute`
sit behind the same `require_job_token` dependency and the same
`include_in_schema=False`. What's specific to this route -- the `as_of`
default/override, and that it actually drives the real job against the
database -- gets its own tests here.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ax.db.models import Artist, IndexSnapshot
from tests.conftest import ArtistFactory
from tests.test_recompute_job import _day, _seed_steady


def test_recompute_requires_a_token(client: TestClient) -> None:
    response = client.post("/internal/jobs/recompute")

    assert response.status_code == 401


def test_recompute_rejects_a_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/internal/jobs/recompute", headers={"Authorization": "Bearer not-the-token"}
    )

    assert response.status_code == 401


def test_recompute_defaults_to_today_utc(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/internal/jobs/recompute", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["as_of_date"] == datetime.now(UTC).date().isoformat()


def test_recompute_as_of_override_is_honored(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/internal/jobs/recompute", params={"as_of": "2026-01-15"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["as_of_date"] == "2026-01-15"


def test_recompute_with_no_artists_is_a_harmless_no_op(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post("/internal/jobs/recompute", headers=auth_headers)

    body = response.json()
    assert body["eligible"] == 0
    assert body["published"] == 0
    assert body["newly_listed"] == []


def test_recompute_endpoint_lists_a_real_population(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    """The route wired to the real job, not a stub: seed real
    `metric_snapshots` through the session the app itself reads from,
    hit the HTTP route, and confirm the database actually changed."""
    states = _seed_steady(session, make_artist, count=10, days=8)
    as_of = _day(7)

    response = client.post(
        "/internal/jobs/recompute", params={"as_of": as_of.isoformat()}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["published"] == 10
    assert len(body["newly_listed"]) == 10

    artist_id = states[0].artist.id
    snapshot = session.scalar(
        select(IndexSnapshot).where(
            IndexSnapshot.artist_id == artist_id, IndexSnapshot.as_of_date == as_of
        )
    )
    assert snapshot is not None
    artist = session.get(Artist, artist_id)
    assert artist is not None
    assert artist.listed_at is not None
