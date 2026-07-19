"""Last.fm provider — `artist.getInfo` -> listeners + playcount.

Three things about this API that the implementation is shaped around:

1. **Errors come back as HTTP 200.** "The artist you supplied could not be
   found" is a 200 response with `{"error": 6}` in the body. Checking
   `response.status_code` alone would record garbage as a real
   observation, so the body is always parsed for `error` first.

2. **Names are ambiguous, MBIDs are not.** We look up by MBID when the
   seed resolved one, and only fall back to the name. `autocorrect` is
   explicitly off: the seed already stored the canonical name the API
   answers to, and letting Last.fm silently re-point "Wednesday" at a
   different artist would corrupt a price series with no visible failure.

3. **`playcount` is monotonic.** It only ever rises. That is why the index
   is built on cross-sectional z-scores of *growth*, never levels — see
   CLAUDE.md rule 5 and invariant I8. Nothing in this module may "fix"
   that; it reports what the API says.
"""

import logging
import time
from typing import Any

import httpx

from ax.providers.base import (
    ArtistRef,
    MetricValue,
    ProviderAuthError,
    ProviderNotFound,
    ProviderTransient,
)

log = logging.getLogger(__name__)

API_ROOT = "https://ws.audioscrobbler.com/2.0/"

SOURCE = "lastfm"
METRIC_LISTENERS = "listeners"
METRIC_PLAYCOUNT = "playcount"

# Last.fm's documented ceiling is ~5 requests/second per key. We pace at 4
# to leave headroom, which puts a 200-artist run at ~50s — comfortably
# inside any job timeout, so there is no reason to add concurrency and
# risk the rate limit.
DEFAULT_MIN_INTERVAL_S = 0.25

# Error codes worth distinguishing. Everything else is treated as
# transient, which is the safe default: a retry costs one request, while
# misclassifying a real outage as permanent loses a night of data.
ERR_INVALID_KEY = 10
ERR_SUSPENDED_KEY = 26
ERR_ARTIST_NOT_FOUND = 6
ERR_INVALID_PARAMS = 7
ERR_RATE_LIMIT = 29

_FATAL_ERRORS = {ERR_INVALID_KEY, ERR_SUSPENDED_KEY}
_NOT_FOUND_ERRORS = {ERR_ARTIST_NOT_FOUND, ERR_INVALID_PARAMS}


def _parse_count(raw: object) -> int:
    """Counts arrive as strings, occasionally comma-grouped."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        cleaned = raw.replace(",", "").strip()
        if cleaned.isdigit():
            return int(cleaned)
    raise ProviderTransient(f"unparseable count from Last.fm: {raw!r}")


class LastfmProvider:
    """Sequential, rate-limited, retrying client for `artist.getInfo`."""

    source = SOURCE

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_attempts: int = 3,
        timeout_s: float = 15.0,
    ) -> None:
        if not api_key:
            raise ProviderAuthError("LASTFM_API_KEY is not set")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)
        self._min_interval_s = min_interval_s
        self._max_attempts = max_attempts
        self._last_request_at: float | None = None

    def __enter__(self) -> "LastfmProvider":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, ref: ArtistRef) -> list[MetricValue]:
        """Fetch listeners + playcount for one artist.

        Tries the MBID first, then the name. The fallback matters because
        Last.fm's MBID coverage is patchy and an artist whose MBID has
        been merged upstream still resolves fine by name — losing that
        artist's whole series to a stale identifier would be a silent,
        permanent data gap.
        """
        attempts: list[dict[str, str]] = []
        if ref.external_id:
            attempts.append({"mbid": ref.external_id})
        attempts.append({"artist": ref.name})

        last_error: ProviderNotFound | None = None
        for params in attempts:
            try:
                payload = self._get({"method": "artist.getinfo", **params})
            except ProviderNotFound as exc:
                last_error = exc
                continue
            return self._extract(payload, ref)

        raise last_error or ProviderNotFound(f"no lookup succeeded for {ref.name!r}")

    def _extract(self, payload: dict[str, Any], ref: ArtistRef) -> list[MetricValue]:
        artist = payload.get("artist")
        if not isinstance(artist, dict):
            raise ProviderTransient(f"missing 'artist' in response for {ref.name!r}")

        stats = artist.get("stats")
        if not isinstance(stats, dict):
            raise ProviderTransient(f"missing 'stats' in response for {ref.name!r}")

        # Surfaced rather than raised: a rename upstream is legitimate and
        # the metrics are still the right artist's (we matched by MBID).
        # Worth a log line so a drifting seed is noticeable.
        returned = artist.get("name")
        if isinstance(returned, str) and returned.casefold() != ref.name.casefold():
            log.info("lastfm returned %r for seeded name %r", returned, ref.name)

        return [
            MetricValue(METRIC_LISTENERS, _parse_count(stats.get("listeners"))),
            MetricValue(METRIC_PLAYCOUNT, _parse_count(stats.get("playcount"))),
        ]

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        """One rate-limited, retried request. Returns the parsed body."""
        full = {
            **params,
            "api_key": self._api_key,
            "format": "json",
            # Off deliberately — see the module docstring. Last.fm
            # substituting a different artist would be invisible in the
            # data and permanent in the price series.
            "autocorrect": "0",
        }

        last_transient: Exception | None = None
        for attempt in range(self._max_attempts):
            if attempt:
                # 0.5s, 1s, 2s ... Cheap, and the failures we retry
                # (429, 5xx, reset connections) are exactly the ones that
                # clear on their own within seconds.
                time.sleep(0.5 * 2 ** (attempt - 1))
            self._throttle()
            try:
                response = self._client.get(API_ROOT, params=full)
            except httpx.HTTPError as exc:
                last_transient = ProviderTransient(f"request failed: {exc}")
                continue

            try:
                return self._check(response)
            except ProviderTransient as exc:
                last_transient = exc
                continue

        raise last_transient or ProviderTransient("exhausted retries")

    def _check(self, response: httpx.Response) -> dict[str, Any]:
        """Classify one response. Body before status — see docstring note 1."""
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"Last.fm rejected the API key (HTTP {response.status_code})")
        if response.status_code == 429:
            raise ProviderTransient("rate limited by Last.fm")
        if response.status_code >= 500:
            raise ProviderTransient(f"Last.fm returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderTransient(f"non-JSON response from Last.fm: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderTransient("unexpected JSON shape from Last.fm")

        if "error" in payload:
            code = payload.get("error")
            message = payload.get("message", "")
            if code in _FATAL_ERRORS:
                raise ProviderAuthError(f"Last.fm error {code}: {message}")
            if code in _NOT_FOUND_ERRORS:
                raise ProviderNotFound(f"Last.fm error {code}: {message}")
            raise ProviderTransient(f"Last.fm error {code}: {message}")

        if response.status_code >= 400:
            raise ProviderTransient(f"Last.fm returned HTTP {response.status_code}")

        return payload

    def _throttle(self) -> None:
        """Space requests to stay under the rate limit."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._min_interval_s - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()
