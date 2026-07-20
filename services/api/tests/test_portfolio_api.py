"""`GET /portfolio` -- cash plus positions marked to market, the read
path `position_cache`/`balance_cache` exist to make cheap.
"""

from fastapi.testclient import TestClient

from ax.core.config import STARTING_BALANCE_CENTS
from tests.conftest import ArtistFactory, ListArtist


def test_portfolio_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio").status_code == 401


def test_fresh_signup_has_starting_balance_and_no_positions(client: TestClient) -> None:
    client.post("/auth/signup", json={"username": "freshling"})

    response = client.get("/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert body["cash_cents"] == STARTING_BALANCE_CENTS
    assert body["equity_cents"] == STARTING_BALANCE_CENTS
    assert body["positions"] == []


def test_portfolio_reflects_a_buy(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    client.post("/auth/signup", json={"username": "holder"})
    artist = make_artist("Held")
    list_artist(artist, fair_value_cents=1_000)

    trade = client.post(
        "/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 4}
    ).json()

    response = client.get("/portfolio")
    body = response.json()

    assert body["cash_cents"] == trade["cash_cents"]
    assert len(body["positions"]) == 1
    position = body["positions"][0]
    assert position["artist_slug"] == artist.slug
    assert position["shares"] == 4
    # index_score 50 >= SCOUT_DISCOVERY_INDEX_MAX (45), so this buy isn't
    # scout-qualified (C12: both thresholds, not just price).
    assert position["scout_shares"] == 0

    # equity == cash + market value of the position, both at current spot
    expected_equity = body["cash_cents"] + position["market_value_cents"]
    assert body["equity_cents"] == expected_equity


def test_selling_to_zero_drops_the_position_from_the_list(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    client.post("/auth/signup", json={"username": "flipper"})
    artist = make_artist("Flipped")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 3})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "sell", "shares": 3})

    response = client.get("/portfolio")

    assert response.json()["positions"] == []


def test_portfolios_are_isolated_per_user(
    client: TestClient, make_artist: ArtistFactory, list_artist: ListArtist
) -> None:
    artist = make_artist("Shared Market")
    list_artist(artist, fair_value_cents=1_000)

    client.post("/auth/signup", json={"username": "trader-a"})
    client.post("/trades", json={"artist_slug": artist.slug, "side": "buy", "shares": 5})
    client.post("/auth/logout")

    client.post("/auth/signup", json={"username": "trader-b"})
    response = client.get("/portfolio")

    assert response.json()["cash_cents"] == STARTING_BALANCE_CENTS
    assert response.json()["positions"] == []
