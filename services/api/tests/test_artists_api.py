"""`GET /artists`, `GET /artists/{slug}`, `GET /artists/{slug}/history` --
public, read-only, the data behind Phase 5's listing page, artist page,
and signature dual-line chart.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as OrmSession

from ax.db.models import TIER_BLUE_CHIP, TIER_GROWTH
from tests.conftest import ArtistFactory, ListArtist


def test_list_excludes_warming_up_artists(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    make_artist("Still Warming Up")
    listed = make_artist("Listed One")
    list_artist(listed, fair_value_cents=1_000)

    response = client.get("/artists")

    assert response.status_code == 200
    slugs = [a["slug"] for a in response.json()]
    assert listed.slug in slugs
    assert len(response.json()) == 1


def test_list_excludes_delisted_artists(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    artist = make_artist("Delisted", delisted=True)
    list_artist(artist, fair_value_cents=1_000)

    response = client.get("/artists")

    assert response.json() == []


def test_list_filters_by_tier(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    growth = make_artist("Growth Artist", tier=TIER_GROWTH)
    blue_chip = make_artist("Blue Chip Artist", tier=TIER_BLUE_CHIP)
    list_artist(growth, fair_value_cents=1_000)
    list_artist(blue_chip, fair_value_cents=5_000)

    response = client.get("/artists", params={"tier": "growth"})

    slugs = [a["slug"] for a in response.json()]
    assert growth.slug in slugs
    assert blue_chip.slug not in slugs


def test_list_rejects_an_invalid_tier(client: TestClient) -> None:
    response = client.get("/artists", params={"tier": "not-a-tier"})
    assert response.status_code == 422


def test_get_artist_includes_index_score_and_price(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    artist = make_artist("Detailed")
    list_artist(artist, fair_value_cents=1_000, index_score=62.5)

    response = client.get(f"/artists/{artist.slug}")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == artist.slug
    assert body["index_score"] == 62.5
    assert body["fair_value_cents"] == 1_000
    assert body["spot_price_cents"] == 1_000
    assert body["net_supply"] == 0


def test_get_artist_404_for_warming_up(client: TestClient, make_artist: ArtistFactory) -> None:
    artist = make_artist("Not Listed Yet")
    response = client.get(f"/artists/{artist.slug}")
    assert response.status_code == 404


def test_get_artist_404_for_unknown_slug(client: TestClient) -> None:
    response = client.get("/artists/does-not-exist")
    assert response.status_code == 404


def test_history_includes_the_listing_row(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    artist = make_artist("Chartable")
    list_artist(artist, fair_value_cents=1_000)

    response = client.get(f"/artists/{artist.slug}/history")

    assert response.status_code == 200
    body = response.json()
    assert body["artist"]["slug"] == artist.slug
    assert len(body["points"]) == 1
    assert body["points"][0]["source"] == "listing"
    assert body["points"][0]["market_price_cents"] == 1_000


def test_history_reflects_a_trade(
    client: TestClient,
    session: OrmSession,
    make_artist: ArtistFactory,
    list_artist: ListArtist,
) -> None:
    artist = make_artist("Traded")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/auth/signup", json={"username": "chart-trader"})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 2})

    response = client.get(f"/artists/{artist.slug}/history")

    sources = [p["source"] for p in response.json()["points"]]
    assert sources == ["listing", "trade"]
    assert response.json()["points"][-1]["net_supply"] == 2
