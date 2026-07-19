"""Snapshot job against real Postgres.

The centerpiece is **I12 — snapshot idempotency**. It is the invariant the
entire nightly operation rests on: GitHub Actions retries on failure,
`workflow_dispatch` lets a human re-run by hand, and cron can double-fire.
If a second run for the same date duplicated or corrupted rows, every one
of those ordinary events would silently poison the index.
"""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ax.db.models import MetricSnapshot
from ax.jobs.snapshot import active_artists, run_snapshot
from ax.providers.base import MetricValue, ProviderAuthError, ProviderError, ProviderTransient
from tests.conftest import ArtistFactory, FakeProvider

AS_OF = date(2026, 7, 18)


def snapshot_rows(session: Session, as_of: date = AS_OF) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(MetricSnapshot)
            .where(MetricSnapshot.as_of_date == as_of)
        )
        or 0
    )


def stored_values(session: Session, artist_id: int) -> dict[str, int]:
    rows = session.scalars(
        select(MetricSnapshot).where(
            MetricSnapshot.artist_id == artist_id, MetricSnapshot.as_of_date == AS_OF
        )
    )
    return {row.metric_key: row.value for row in rows}


def test_snapshot_writes_one_row_per_metric(session: Session, make_artist: ArtistFactory) -> None:
    artist = make_artist("Wednesday")
    provider = FakeProvider({"Wednesday": {"listeners": 390738, "playcount": 16199012}})

    result = run_snapshot(session, provider, AS_OF)

    assert result.succeeded == 1
    assert stored_values(session, artist.id) == {"listeners": 390738, "playcount": 16199012}


# --- I12: idempotency -------------------------------------------------


def test_i12_rerun_adds_no_rows(session: Session, make_artist: ArtistFactory) -> None:
    """The invariant, stated directly: running twice for the same date
    leaves the row count unchanged."""
    for name in ("A", "B", "C"):
        make_artist(name)
    provider = FakeProvider()

    run_snapshot(session, provider, AS_OF)
    after_first = snapshot_rows(session)

    run_snapshot(session, provider, AS_OF)
    after_second = snapshot_rows(session)

    assert after_first == 6  # 3 artists x 2 metrics
    assert after_second == after_first


def test_i12_rerun_with_same_data_leaves_values_identical(
    session: Session, make_artist: ArtistFactory
) -> None:
    artist = make_artist("Wednesday")
    provider = FakeProvider({"Wednesday": {"listeners": 100, "playcount": 500}})

    run_snapshot(session, provider, AS_OF)
    before = stored_values(session, artist.id)

    run_snapshot(session, provider, AS_OF)

    assert stored_values(session, artist.id) == before


def test_rerun_corrects_a_stale_value(session: Session, make_artist: ArtistFactory) -> None:
    """`DO UPDATE`, not `DO NOTHING`. A re-run after a partial failure must
    fix the stored number rather than preserve the bad one."""
    artist = make_artist("Wednesday")

    run_snapshot(
        session, provider=FakeProvider({"Wednesday": {"listeners": 100}}), as_of_date=AS_OF
    )
    run_snapshot(
        session, provider=FakeProvider({"Wednesday": {"listeners": 250}}), as_of_date=AS_OF
    )

    assert stored_values(session, artist.id) == {"listeners": 250}
    assert snapshot_rows(session) == 1


def test_distinct_dates_accumulate(session: Session, make_artist: ArtistFactory) -> None:
    """Idempotency is per date. Different dates must still build a series —
    without which there is no growth rate and no index."""
    make_artist("Wednesday")
    provider = FakeProvider()

    run_snapshot(session, provider, date(2026, 7, 18))
    run_snapshot(session, provider, date(2026, 7, 19))

    assert snapshot_rows(session, date(2026, 7, 18)) == 2
    assert snapshot_rows(session, date(2026, 7, 19)) == 2


# --- failure isolation ------------------------------------------------


def test_missing_artist_does_not_stop_the_run(session: Session, make_artist: ArtistFactory) -> None:
    """A gap in a series is permanent — Last.fm exposes no history to
    backfill from — so one bad artist must never cost the others."""
    make_artist("Good One")
    make_artist("Gone")
    make_artist("Also Good")
    provider = FakeProvider(not_found={"Gone"})

    result = run_snapshot(session, provider, AS_OF)

    assert result.succeeded == 2
    assert result.not_found == [a.slug for a in active_artists(session) if a.name == "Gone"]
    assert snapshot_rows(session) == 4


def test_transient_failure_is_isolated(session: Session, make_artist: ArtistFactory) -> None:
    make_artist("Good One")
    make_artist("Flaky")
    provider = FakeProvider(raises={"Flaky": ProviderTransient("upstream blip")})

    result = run_snapshot(session, provider, AS_OF)

    assert result.succeeded == 1
    assert len(result.failed) == 1
    assert result.ok  # a single flaky artist is not a failed run


def test_auth_error_aborts_the_whole_run(session: Session, make_artist: ArtistFactory) -> None:
    """Bad credentials fail identically for every artist. Burning 200
    requests to learn that once buries the cause and wastes the budget."""
    make_artist("First")
    make_artist("Second")
    make_artist("Third")
    provider = FakeProvider(raises={"First": ProviderAuthError("Invalid API key")})

    result = run_snapshot(session, provider, AS_OF)

    assert not result.ok
    assert result.aborted_reason is not None
    assert provider.calls == ["First"]  # stopped immediately


def test_successful_work_survives_a_later_abort(
    session: Session, make_artist: ArtistFactory
) -> None:
    """Per-artist commits: an abort partway through keeps what was already
    fetched, which cost real rate-limit budget to obtain."""
    make_artist("First")
    make_artist("Second")
    provider = FakeProvider(raises={"Second": ProviderAuthError("key revoked mid-run")})

    result = run_snapshot(session, provider, AS_OF)

    assert not result.ok
    assert snapshot_rows(session) == 2  # First's rows are still there


# --- universe selection -----------------------------------------------


def test_delisted_artists_are_skipped(session: Session, make_artist: ArtistFactory) -> None:
    make_artist("Active")
    make_artist("Delisted", delisted=True)
    provider = FakeProvider()

    result = run_snapshot(session, provider, AS_OF)

    assert result.attempted == 1
    assert provider.calls == ["Active"]


def test_unlisted_artists_are_included(session: Session, make_artist: ArtistFactory) -> None:
    """Warming-up artists need snapshots precisely because they lack them.
    Excluding them would mean they never accumulate enough to list."""
    make_artist("Warming Up")  # listed_at is NULL by default

    result = run_snapshot(session, FakeProvider(), AS_OF)

    assert result.attempted == 1


def test_mbid_is_passed_through_to_the_provider(
    session: Session, make_artist: ArtistFactory
) -> None:
    make_artist("Wednesday", mbid="9af01d07-8f6e-4651-bdcb-38efae021af7")

    captured: list[str | None] = []

    class CapturingProvider(FakeProvider):
        def fetch(self, ref):  # type: ignore[no-untyped-def]
            captured.append(ref.external_id)
            return super().fetch(ref)

    run_snapshot(session, CapturingProvider(), AS_OF)

    assert captured == ["9af01d07-8f6e-4651-bdcb-38efae021af7"]


@pytest.mark.parametrize("metric_value", [0, 2**31 + 1, 9_999_999_999])
def test_large_and_zero_counts_round_trip(
    session: Session, make_artist: ArtistFactory, metric_value: int
) -> None:
    """Playcounts exceed 2^31 for large artists; the column is BIGINT and
    must actually hold them."""
    artist = make_artist("Big")
    provider = FakeProvider({"Big": {"playcount": metric_value}})

    run_snapshot(session, provider, AS_OF)

    assert stored_values(session, artist.id) == {"playcount": metric_value}


# --- regressions ------------------------------------------------------


def test_duplicate_metric_keys_do_not_abort_the_run(
    session: Session, make_artist: ArtistFactory
) -> None:
    """Postgres rejects an ON CONFLICT DO UPDATE that touches one key
    twice. Unhandled, that error escapes per-artist isolation and kills the
    whole run — so it is deduplicated before the insert."""

    class DuplicateKeyProvider(FakeProvider):
        def fetch(self, ref):  # type: ignore[no-untyped-def]
            self.calls.append(ref.name)
            return [MetricValue("listeners", 1), MetricValue("listeners", 2)]

    artist = make_artist("Dupe")
    make_artist("After")

    result = run_snapshot(session, DuplicateKeyProvider(), AS_OF)

    assert result.succeeded == 2  # the run continued past the bad artist
    assert stored_values(session, artist.id) == {"listeners": 2}  # last wins


def test_empty_metrics_is_not_counted_as_success(
    session: Session, make_artist: ArtistFactory
) -> None:
    """A silent empty response must not report a clean run while the
    artist accumulates a permanent gap in its series."""

    class EmptyProvider(FakeProvider):
        def fetch(self, ref):  # type: ignore[no-untyped-def]
            self.calls.append(ref.name)
            return []

    make_artist("Silent")

    result = run_snapshot(session, EmptyProvider(), AS_OF)

    assert result.succeeded == 0
    assert len(result.failed) == 1


def test_base_provider_error_is_isolated(session: Session, make_artist: ArtistFactory) -> None:
    """A provider raising the base class must not escape the loop."""
    make_artist("Broken")
    make_artist("Fine")
    provider = FakeProvider(raises={"Broken": ProviderError("unexpected shape")})

    result = run_snapshot(session, provider, AS_OF)

    assert result.ok
    assert result.succeeded == 1
    assert len(result.failed) == 1
