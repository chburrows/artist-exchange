"""`GET /leaderboard/portfolio` and `GET /leaderboard/scout` -- both read
`jobs/leaderboard.py`'s nightly output, never compute live.
"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ax.jobs.leaderboard import run_leaderboard_snapshot
from tests.conftest import ArtistFactory, FakeEmailProvider, ListArtist, complete_signup


def test_portfolio_leaderboard_is_public(client: TestClient) -> None:
    response = client.get("/leaderboard/portfolio")
    assert response.status_code == 200


def test_portfolio_leaderboard_empty_before_any_snapshot_has_run(client: TestClient) -> None:
    response = client.get("/leaderboard/portfolio")
    body = response.json()
    assert body["as_of_date"] is None
    assert body["rows"] == []
    assert body["you"] is None


def test_portfolio_leaderboard_ranks_by_equity_and_flags_you(
    client: TestClient, session: Session, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "trader-a")
    client.post("/auth/logout")
    complete_signup(client, email_provider, "trader-b")
    # trader-b is the current session below.

    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    response = client.get("/leaderboard/portfolio")
    body = response.json()

    assert body["as_of_date"] == "2026-01-01"
    assert [row["username"] for row in body["rows"]] == ["trader-a", "trader-b"] or [
        row["username"] for row in body["rows"]
    ] == ["trader-b", "trader-a"]
    assert body["you"] is not None
    assert body["you"]["username"] == "trader-b"
    assert body["you"]["is_you"] is True
    for row in body["rows"]:
        assert row["is_you"] == (row["username"] == "trader-b")


def test_scout_leaderboard_includes_artist_and_entry_price(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
    email_provider: FakeEmailProvider,
) -> None:
    complete_signup(client, email_provider, "scout")
    artist = make_artist("Undervalued")
    list_artist(artist, fair_value_cents=200, index_score=30.0)
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 10})

    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))

    response = client.get("/leaderboard/scout")
    body = response.json()

    assert body["as_of_date"] == "2026-01-01"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["username"] == "scout"
    assert row["artist_slug"] == artist.slug
    assert row["return_bps"] > 0
    assert body["you"]["username"] == "scout"


def test_scout_leaderboard_empty_before_any_snapshot_has_run(client: TestClient) -> None:
    response = client.get("/leaderboard/scout")
    body = response.json()
    assert body["as_of_date"] is None
    assert body["rows"] == []
    assert body["you"] is None


def test_portfolio_history_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio/history").status_code == 401


def test_portfolio_history_empty_before_any_snapshot_has_run(
    client: TestClient, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "no-history-yet")
    response = client.get("/portfolio/history")
    assert response.status_code == 200
    assert response.json()["points"] == []


def test_portfolio_history_returns_real_snapshots_oldest_first(
    client: TestClient, session: Session, email_provider: FakeEmailProvider
) -> None:
    complete_signup(client, email_provider, "historied")

    run_leaderboard_snapshot(session, date(2026, 1, 1), now=datetime.now(UTC))
    run_leaderboard_snapshot(session, date(2026, 1, 2), now=datetime.now(UTC))

    response = client.get("/portfolio/history")
    points = response.json()["points"]

    assert [p["as_of_date"] for p in points] == ["2026-01-01", "2026-01-02"]
