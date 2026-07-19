"""Provider tests, hermetic via httpx.MockTransport.

The response bodies here were captured from the live API on 2026-07-18,
including the error shapes — which is the point. The behavior most worth
pinning is that Last.fm reports "artist not found" as an HTTP **200**
with an error body; a provider that trusts the status code records
garbage as a real observation.
"""

import httpx
import pytest

from ax.providers.base import (
    ArtistRef,
    ProviderAuthError,
    ProviderNotFound,
    ProviderTransient,
)
from ax.providers.lastfm import LastfmProvider

OK_BODY = {
    "artist": {
        "name": "Wednesday",
        "mbid": "9af01d07-8f6e-4651-bdcb-38efae021af7",
        "stats": {"listeners": "390738", "playcount": "16199012"},
    }
}

NOT_FOUND_BODY = {"error": 6, "message": "The artist you supplied could not be found", "links": []}
BAD_KEY_BODY = {"error": 10, "message": "Invalid API key"}


def provider_returning(
    *responses: httpx.Response, **kwargs: object
) -> tuple[LastfmProvider, list[httpx.Request]]:
    """A provider whose transport replays `responses` in order.

    `min_interval_s=0` because the real 0.25s throttle would make the
    retry tests take seconds for no added coverage — the throttle is
    tested separately.
    """
    seen: list[httpx.Request] = []
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        LastfmProvider("test-key", client=client, min_interval_s=0.0, **kwargs),  # type: ignore[arg-type]
        seen,
    )


def test_fetch_returns_listeners_and_playcount() -> None:
    provider, _ = provider_returning(httpx.Response(200, json=OK_BODY))

    metrics = provider.fetch(ArtistRef("Wednesday"))

    assert {m.metric_key: m.value for m in metrics} == {
        "listeners": 390738,
        "playcount": 16199012,
    }


def test_counts_are_ints_not_strings() -> None:
    """Values land in a BIGINT column; a str here fails at insert time."""
    provider, _ = provider_returning(httpx.Response(200, json=OK_BODY))

    for metric in provider.fetch(ArtistRef("Wednesday")):
        assert isinstance(metric.value, int)


def test_comma_grouped_counts_parse() -> None:
    body = {"artist": {"name": "X", "stats": {"listeners": "1,234", "playcount": "5,678,901"}}}
    provider, _ = provider_returning(httpx.Response(200, json=body))

    assert [m.value for m in provider.fetch(ArtistRef("X"))] == [1234, 5678901]


def test_not_found_is_detected_despite_http_200() -> None:
    """The single most important behavior in this module."""
    provider, _ = provider_returning(httpx.Response(200, json=NOT_FOUND_BODY))

    with pytest.raises(ProviderNotFound):
        provider.fetch(ArtistRef("zzzznotarealartistzzz9"))


def test_not_found_is_not_retried() -> None:
    """A missing artist is permanent. Retrying it burns rate-limit budget
    that the other 199 artists need."""
    provider, seen = provider_returning(httpx.Response(200, json=NOT_FOUND_BODY))

    with pytest.raises(ProviderNotFound):
        provider.fetch(ArtistRef("nobody"))

    assert len(seen) == 1


def test_invalid_key_raises_auth_error() -> None:
    """Fatal, so the job aborts instead of failing 200 times identically."""
    provider, _ = provider_returning(httpx.Response(200, json=BAD_KEY_BODY))

    with pytest.raises(ProviderAuthError):
        provider.fetch(ArtistRef("Wednesday"))


def test_http_403_raises_auth_error() -> None:
    provider, _ = provider_returning(httpx.Response(403, text="Invalid API key"))

    with pytest.raises(ProviderAuthError):
        provider.fetch(ArtistRef("Wednesday"))


def test_server_error_retries_then_succeeds() -> None:
    provider, seen = provider_returning(
        httpx.Response(503, text="upstream down"),
        httpx.Response(200, json=OK_BODY),
    )

    metrics = provider.fetch(ArtistRef("Wednesday"))

    assert len(seen) == 2
    assert metrics[0].value == 390738


def test_retries_are_bounded() -> None:
    provider, seen = provider_returning(httpx.Response(500, text="down"), max_attempts=3)

    with pytest.raises(ProviderTransient):
        provider.fetch(ArtistRef("Wednesday"))

    assert len(seen) == 3


def test_rate_limit_is_transient_not_fatal() -> None:
    provider, _ = provider_returning(httpx.Response(429, text="slow down"), max_attempts=1)

    with pytest.raises(ProviderTransient):
        provider.fetch(ArtistRef("Wednesday"))


def test_mbid_is_preferred_over_name() -> None:
    provider, seen = provider_returning(httpx.Response(200, json=OK_BODY))

    provider.fetch(ArtistRef("Wednesday", external_id="9af01d07-8f6e-4651-bdcb-38efae021af7"))

    assert seen[0].url.params["mbid"] == "9af01d07-8f6e-4651-bdcb-38efae021af7"
    assert "artist" not in seen[0].url.params


def test_stale_mbid_falls_back_to_name() -> None:
    """An artist whose MBID was merged upstream must not lose its series."""
    provider, seen = provider_returning(
        httpx.Response(200, json=NOT_FOUND_BODY),
        httpx.Response(200, json=OK_BODY),
    )

    metrics = provider.fetch(ArtistRef("Wednesday", external_id="stale-mbid"))

    assert seen[0].url.params["mbid"] == "stale-mbid"
    assert seen[1].url.params["artist"] == "Wednesday"
    assert metrics[0].value == 390738


def test_autocorrect_is_off() -> None:
    """Autocorrect lets Last.fm silently substitute a different artist —
    invisible in the data, permanent in the price series."""
    provider, seen = provider_returning(httpx.Response(200, json=OK_BODY))

    provider.fetch(ArtistRef("Wednesday"))

    assert seen[0].url.params["autocorrect"] == "0"


def test_malformed_body_is_transient_not_a_silent_zero() -> None:
    provider, _ = provider_returning(
        httpx.Response(200, json={"artist": {"name": "X"}}), max_attempts=1
    )

    with pytest.raises(ProviderTransient):
        provider.fetch(ArtistRef("X"))


def test_missing_api_key_is_refused_at_construction() -> None:
    with pytest.raises(ProviderAuthError):
        LastfmProvider("")
