"""Nightly metric snapshot.

Walks the artist universe, fetches each artist's current metrics from a
provider, and upserts them into `metric_snapshots`.

**Idempotency (CLAUDE.md rule 7) is structural, not defensive.** The
composite primary key `(artist_id, as_of_date, source, metric_key)` plus
`ON CONFLICT DO UPDATE` means a retried GitHub Action, a manual
`workflow_dispatch`, and a double-fired cron all converge to the same
rows. Nothing here counts, checks-then-writes, or appends — so there is no
race to lose.

`as_of_date` is always a parameter. The job never asks what day it is:
that would make backfills impossible and tests dependent on wall-clock
time.

Failure isolation is per artist. One artist Last.fm has forgotten must not
cost the other 199 their nightly data point — a gap in a series is
permanent, since Last.fm exposes no history to backfill from.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ax.db.models import Artist, MetricSnapshot
from ax.providers.base import (
    ArtistRef,
    MetricProvider,
    MetricValue,
    ProviderAuthError,
    ProviderError,
    ProviderNotFound,
    ProviderTransient,
)

log = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    as_of_date: date
    source: str
    attempted: int = 0
    succeeded: int = 0
    rows_upserted: int = 0
    not_found: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    aborted_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.aborted_reason is None

    def summary(self) -> dict[str, object]:
        """Shape returned by the internal endpoint and logged by the Action."""
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "source": self.source,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "rows_upserted": self.rows_upserted,
            "not_found": self.not_found,
            "failed": self.failed,
            "aborted_reason": self.aborted_reason,
        }


def active_artists(session: Session) -> list[Artist]:
    """Every artist still in the universe.

    Includes artists that are not yet listed: they are `warming_up`
    precisely because they need snapshots, so excluding them would mean
    they never accumulate enough to list.
    """
    stmt = select(Artist).where(Artist.delisted_at.is_(None)).order_by(Artist.id)
    return list(session.scalars(stmt))


def run_snapshot(
    session: Session,
    provider: MetricProvider,
    as_of_date: date,
    *,
    artists: list[Artist] | None = None,
) -> SnapshotResult:
    """Snapshot every active artist for `as_of_date`.

    Commits per artist rather than once at the end. A 200-artist run takes
    ~50s against a rate-limited API; holding one transaction open across
    all of it would mean a failure at artist 190 discards 189 good
    fetches that cost real rate-limit budget to obtain.
    """
    targets = active_artists(session) if artists is None else artists
    result = SnapshotResult(as_of_date=as_of_date, source=provider.source)

    for artist in targets:
        result.attempted += 1
        ref = ArtistRef(name=artist.lastfm_name, external_id=artist.lastfm_mbid)

        try:
            metrics = provider.fetch(ref)
        except ProviderAuthError as exc:
            # Fatal: our credentials are wrong, and every remaining artist
            # would fail identically. Stop, and report why, rather than
            # burying the cause under 200 duplicate errors.
            log.error("aborting snapshot run: %s", exc)
            result.aborted_reason = str(exc)
            break
        except ProviderNotFound:
            log.warning("artist not found upstream: %s (id=%s)", artist.name, artist.id)
            result.not_found.append(artist.slug)
            continue
        except ProviderTransient as exc:
            # The provider already retried with backoff. One more artist
            # missing today is recoverable; failing the run is not.
            log.warning("transient failure for %s: %s", artist.name, exc)
            result.failed.append(artist.slug)
            continue
        except ProviderError as exc:
            # Catch-all for the base class, last. A provider raising bare
            # `ProviderError` would otherwise escape the loop entirely and
            # abort the run — defeating the per-artist isolation above for
            # the one case nobody thought to subclass.
            log.warning("provider error for %s: %s", artist.name, exc)
            result.failed.append(artist.slug)
            continue

        if not metrics:
            # The provider protocol forbids this (`base.py`: raise
            # ProviderNotFound instead). Counting it as a success would
            # report a clean run while the artist silently accumulates a
            # permanent gap in its series.
            log.warning("provider returned no metrics for %s", artist.name)
            result.failed.append(artist.slug)
            continue

        try:
            written = upsert_metrics(session, artist.id, as_of_date, provider.source, metrics)
            session.commit()
        except SQLAlchemyError as exc:
            # A lock timeout or connection blip on one artist must not
            # discard the summary for the other 199. Roll back to a usable
            # session and keep going, so the caller still learns which
            # artists succeeded.
            log.warning("database error storing %s: %s", artist.name, exc)
            session.rollback()
            result.failed.append(artist.slug)
            continue

        result.rows_upserted += written
        result.succeeded += 1

    return result


def upsert_metrics(
    session: Session,
    artist_id: int,
    as_of_date: date,
    source: str,
    metrics: list[MetricValue],
) -> int:
    """Write one artist's metrics idempotently.

    `DO UPDATE` rather than `DO NOTHING` on purpose: a same-day re-run
    after a partial failure should *correct* the stored value, not
    preserve whatever the failed attempt left behind. The primary key
    guarantees the re-run overwrites rather than duplicates.
    """
    if not metrics:
        return 0

    # Deduplicate on metric_key, last value winning. Postgres rejects an
    # ON CONFLICT DO UPDATE whose own INSERT touches the same key twice
    # ("cannot affect row a second time"), and that error escapes the
    # per-artist try/except in `run_snapshot` — so one malformed provider
    # response would abort the entire nightly run rather than skipping one
    # artist. Last.fm cannot currently produce a duplicate, but the
    # YouTube provider PLAN.md schedules next is exactly where one would
    # first appear.
    deduplicated = {metric.metric_key: metric.value for metric in metrics}

    stmt = insert(MetricSnapshot).values(
        [
            {
                "artist_id": artist_id,
                "as_of_date": as_of_date,
                "source": source,
                "metric_key": metric_key,
                "value": value,
            }
            for metric_key, value in deduplicated.items()
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["artist_id", "as_of_date", "source", "metric_key"],
        # `now()` explicitly rather than `excluded.fetched_at`: EXCLUDED
        # does carry the column default, but relying on that is a subtle
        # read, and provenance should say when the value was actually
        # written.
        set_={"value": stmt.excluded.value, "fetched_at": func.now()},
    )
    session.execute(stmt)
    return len(deduplicated)
