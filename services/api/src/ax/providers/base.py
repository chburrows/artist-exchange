"""The provider seam.

Every external data source implements `MetricProvider` and returns
long-format `MetricValue` rows. Adding YouTube later is a class here plus
one `SIGNAL_WEIGHTS` entry in `core/config.py` — no migration, because
`metric_snapshots` stores (source, metric_key, value) rather than a column
per signal.

The error taxonomy exists so the nightly job can tell apart the three
things that go wrong, which need three different responses:

  `ProviderNotFound`   — this artist is bad, the run is fine. Skip it.
  `ProviderTransient`  — the network or the upstream blipped. Retry it.
  `ProviderAuthError`  — our credentials are wrong. Abort the whole run;
                         doing 200 more requests to learn the same thing
                         wastes the rate-limit budget and buries the real
                         cause under 200 identical failures.
"""

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Base for anything a provider can fail with."""


class ProviderNotFound(ProviderError):
    """The upstream has no record of this artist. Skip, don't retry."""


class ProviderTransient(ProviderError):
    """Timeout, connection reset, 5xx, or 429. Retry with backoff."""


class ProviderAuthError(ProviderError):
    """Bad or missing credentials. Fatal for the whole run."""


@dataclass(frozen=True, slots=True)
class ArtistRef:
    """What a provider needs to identify one artist.

    `external_id` is the provider's own stable identifier — MusicBrainz ID
    for Last.fm, channel ID for YouTube. Preferred over `name` when
    present because names are ambiguous and get silently re-pointed
    upstream.
    """

    name: str
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One observation. `value` is an integer because every metric we track
    is a count — and because Last.fm playcounts exceed 2^31.
    """

    metric_key: str
    value: int


class MetricProvider(Protocol):
    source: str
    """Stable identifier written to `metric_snapshots.source`. Changing it
    orphans existing history, so it is part of the data contract."""

    def fetch(self, ref: ArtistRef) -> list[MetricValue]:
        """Fetch current metrics for one artist.

        Raises `ProviderNotFound`, `ProviderTransient`, or
        `ProviderAuthError`. Must not return an empty list — a provider
        with nothing to report raises `ProviderNotFound` instead, so the
        job never records a silent zero.
        """
        ...
