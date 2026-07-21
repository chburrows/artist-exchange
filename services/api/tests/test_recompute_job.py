"""Index recompute + reversion job against real Postgres.

Builds small synthetic populations directly in `metric_snapshots` (never
through a provider -- this job never touches the network) and drives
`run_recompute` the same way the production endpoint and `ax recompute`
do. Three things get the most scrutiny:

  - **Listing and reversion**, since they mutate the one genuinely
    mutable table (`artists`) and must be idempotent per `as_of_date`,
    the same way the snapshot job is idempotent per `(artist_id,
    as_of_date)` (I12's sibling for this job).
  - **The oracle-manipulation quarantine** (PLAN.md Phase 3): a flagged
    artist's score held at its previous value, persisting across days
    until a human clears it.
  - **The real, end-to-end I8 check** PLAN.md's Phase 3 verification
    asks for: a laggard's `fair_value_cents` actually falling while its
    own raw `playcount`/`listeners` only ever rise.

`MIN_CROSS_SECTION_SIZE` (10) means every scenario needs a population of
that size or larger; `MIN_SNAPSHOTS_TO_LIST` (8) means every artist needs
8 consecutive days of history before its first score. The steady
population below gives each artist a small, deliberate, non-degenerate
per-artist spread in both level and the playcount/listeners growth
ratio -- enough that the cross-sectional MAD is a real, non-degenerate
number rather than pinned at its floor, so a genuinely extreme
special-case artist stands out by orders of magnitude rather than by a
fragile margin. Deliberately *not* jittered day to day: at this
population size (10-12), `PERCENTILE_MOVE_THRESHOLD`'s nearest-rank
percentile always flags whichever artist moved the most that day, so any
added jitter would make some unrelated steady artist an incidental
percentile-move outlier in tests that aren't testing that mechanism.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ax.core.amm import reversion_move_cents
from ax.core.index import ArtistDayResult
from ax.db.models import (
    Artist,
    FlaggedArtist,
    IndexSnapshot,
    MetricSnapshot,
    PriceHistory,
    Transaction,
    User,
)
from ax.jobs.recompute import (
    _net_supplies,
    _percentile_move_flags,
    _ratio_divergence_flags,
    clear_flag,
    run_recompute,
)
from tests.conftest import ArtistFactory

BASE_DATE = date(2026, 1, 1)


def _day(offset: int) -> date:
    return BASE_DATE + timedelta(days=offset)


def _now_for(as_of: date) -> datetime:
    return datetime.combine(as_of, time(7, 5), tzinfo=UTC)


def _add_metrics(
    session: Session, artist_id: int, as_of: date, listeners: int, playcount: int
) -> None:
    session.add(
        MetricSnapshot(
            artist_id=artist_id,
            as_of_date=as_of,
            source="lastfm",
            metric_key="listeners",
            value=listeners,
        )
    )
    session.add(
        MetricSnapshot(
            artist_id=artist_id,
            as_of_date=as_of,
            source="lastfm",
            metric_key="playcount",
            value=playcount,
        )
    )


@dataclass
class SeriesState:
    artist: Artist
    listeners: float
    playcount: float
    listeners_growth: float
    playcount_growth: float


def _seed_steady(
    session: Session,
    make_artist: ArtistFactory,
    *,
    count: int,
    days: int,
    start: date = BASE_DATE,
) -> list[SeriesState]:
    """`count` artists, each with `days` consecutive days of smoothly (but
    not identically) growing listeners/playcount. Every artist gets its
    own constant per-artist growth rate and its own constant
    playcount/listeners ratio (deliberate per-artist spread, see module
    docstring) -- but each individual artist's *own* rate never changes
    day to day, so once its EWMA converges (day 8, one day after the
    cold start) its own score goes flat. That flatness is deliberate:
    `PERCENTILE_MOVE_THRESHOLD`'s nearest-rank percentile over a
    population this small (10-12) always flags whichever artist moved
    the *most* that day, so any real day-to-day jitter here would make
    an unrelated steady artist an incidental percentile-move outlier in
    tests that aren't testing that mechanism. Tests that need genuine
    movement inject it deliberately via `_advance_day`'s overrides."""
    states = []
    for i in range(count):
        artist = make_artist(f"Steady {i}")
        listeners = 50_000.0 + i * 1_500.0
        playcount = listeners * 4.0
        listeners_growth = 1.015 + i * 0.0006
        playcount_growth = listeners_growth * (1.004 + i * 0.0003)

        for day in range(days):
            as_of = start + timedelta(days=day)
            _add_metrics(session, artist.id, as_of, round(listeners), round(playcount))
            listeners *= listeners_growth
            playcount *= playcount_growth

        states.append(SeriesState(artist, listeners, playcount, listeners_growth, playcount_growth))
    session.flush()
    return states


def _advance_day(
    session: Session,
    state: SeriesState,
    as_of: date,
    *,
    listeners_override: float | None = None,
    playcount_override: float | None = None,
) -> SeriesState:
    """Seed one more day for this artist's series, applying its normal
    growth unless overridden -- how tests inject a manipulated day."""
    listeners = (
        listeners_override
        if listeners_override is not None
        else state.listeners * state.listeners_growth
    )
    playcount = (
        playcount_override
        if playcount_override is not None
        else state.playcount * state.playcount_growth
    )
    _add_metrics(session, state.artist.id, as_of, round(listeners), round(playcount))
    session.flush()
    return SeriesState(
        state.artist, listeners, playcount, state.listeners_growth, state.playcount_growth
    )


def _advance_all(session: Session, states: list[SeriesState], as_of: date) -> list[SeriesState]:
    return [_advance_day(session, s, as_of) for s in states]


def _snapshot(session: Session, artist_id: int, as_of: date) -> IndexSnapshot | None:
    return session.scalar(
        select(IndexSnapshot).where(
            IndexSnapshot.artist_id == artist_id, IndexSnapshot.as_of_date == as_of
        )
    )


def _effective_fair_value(snapshot: IndexSnapshot) -> int:
    """The fair value a quarantine-aware reader would treat as "what the
    data actually says" -- the audited would-have-computed value if this
    row was held, otherwise the published value itself."""
    quarantine = snapshot.components.get("quarantine")
    if isinstance(quarantine, dict):
        would_have = quarantine["would_have_computed"]
        assert isinstance(would_have, dict)
        value = would_have["fair_value_cents"]
        assert isinstance(value, int)
        return value
    return snapshot.fair_value_cents


# --- warming_up / cross-section gating ---------------------------------


def test_artist_below_min_snapshots_stays_warming_up(
    session: Session, make_artist: ArtistFactory
) -> None:
    _seed_steady(session, make_artist, count=10, days=8)
    short = make_artist("Too New")
    for day in range(5):
        _add_metrics(session, short.id, _day(day), 10_000, 40_000)
    session.flush()

    result = run_recompute(session, _day(7), now=_now_for(_day(7)))

    assert result.eligible == 10
    assert result.published == 10
    assert _snapshot(session, short.id, _day(7)) is None
    session.refresh(short)
    assert short.listed_at is None


def test_below_min_cross_section_size_is_skipped_entirely(
    session: Session, make_artist: ArtistFactory
) -> None:
    states = _seed_steady(session, make_artist, count=5, days=8)

    result = run_recompute(session, _day(7), now=_now_for(_day(7)))

    assert result.skipped_small_cross_section is True
    assert result.published == 0
    assert session.scalar(select(func.count()).select_from(IndexSnapshot)) == 0
    session.refresh(states[0].artist)
    assert states[0].artist.listed_at is None


# --- listing -------------------------------------------------------------


def test_listing_event_sets_market_state(session: Session, make_artist: ArtistFactory) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    as_of = _day(7)

    result = run_recompute(session, as_of, now=_now_for(as_of))

    assert result.published == 10
    assert len(result.newly_listed) == 10

    artist = states[0].artist
    session.refresh(artist)
    snap = _snapshot(session, artist.id, as_of)
    assert snap is not None
    assert artist.listed_at is not None
    assert artist.anchor_cents == snap.fair_value_cents
    assert artist.anchor_target_cents == snap.fair_value_cents
    assert artist.glide_start_at == artist.glide_end_at

    history = session.scalars(select(PriceHistory).where(PriceHistory.artist_id == artist.id)).all()
    assert len(history) == 1
    assert history[0].source == "listing"
    assert history[0].market_price_cents == snap.fair_value_cents
    assert history[0].net_supply == 0


# --- reversion -------------------------------------------------------------


def test_reversion_moves_anchor_on_subsequent_day(
    session: Session, make_artist: ArtistFactory
) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    states = _advance_all(session, states, day8)
    result = run_recompute(session, day8, now=_now_for(day8))

    # Not asserting `result.published == 10`: at n=10, nearest-rank
    # PERCENTILE_MOVE_THRESHOLD always flags whichever artist moved most
    # that day, even when the only "movement" is integer-rounding noise
    # on an otherwise perfectly constant growth rate. That artist isn't
    # the one under test here -- see `test_percentile_move_flag_holds_score`
    # for that mechanism specifically.
    artist = states[0].artist
    assert artist.slug not in [f["slug"] for f in result.newly_flagged]
    session.refresh(artist)

    day7_snap = _snapshot(session, artist.id, day7)
    day8_snap = _snapshot(session, artist.id, day8)
    assert day7_snap is not None
    assert day8_snap is not None

    assert artist.glide_start_at == _now_for(day8)
    assert artist.glide_end_at == _now_for(day8) + timedelta(hours=24)
    # The glide from listing had already fully converged, so the new
    # glide starts from exactly day7's fair value.
    assert artist.anchor_cents == day7_snap.fair_value_cents

    gap = day8_snap.fair_value_cents - day7_snap.fair_value_cents
    expected_move = reversion_move_cents(gap, day7_snap.fair_value_cents)
    assert artist.anchor_target_cents == day7_snap.fair_value_cents + expected_move

    history = session.scalars(
        select(PriceHistory).where(PriceHistory.artist_id == artist.id).order_by(PriceHistory.id)
    ).all()
    assert [h.source for h in history] == ["listing", "reversion"]
    assert history[-1].fair_value_cents == day8_snap.fair_value_cents
    assert history[-1].market_price_cents == day7_snap.fair_value_cents


# --- idempotency ---------------------------------------------------------


def test_rerun_same_day_is_idempotent_for_listing(
    session: Session, make_artist: ArtistFactory
) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    now = _now_for(day7)

    run_recompute(session, day7, now=now)
    artist = states[0].artist
    session.refresh(artist)
    first_listed_at, first_anchor, first_target = (
        artist.listed_at,
        artist.anchor_cents,
        artist.anchor_target_cents,
    )

    run_recompute(session, day7, now=now + timedelta(minutes=5))
    session.refresh(artist)

    assert artist.listed_at == first_listed_at
    assert artist.anchor_cents == first_anchor
    assert artist.anchor_target_cents == first_target

    history_count = session.scalar(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.artist_id == artist.id)
    )
    assert history_count == 1
    snapshot_count = session.scalar(
        select(func.count()).select_from(IndexSnapshot).where(IndexSnapshot.artist_id == artist.id)
    )
    assert snapshot_count == 1


def test_rerun_same_day_is_idempotent_for_reversion(
    session: Session, make_artist: ArtistFactory
) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    states = _advance_all(session, states, day8)
    now8 = _now_for(day8)
    run_recompute(session, day8, now=now8)

    artist = states[0].artist
    session.refresh(artist)
    first_anchor, first_target, first_glide_start = (
        artist.anchor_cents,
        artist.anchor_target_cents,
        artist.glide_start_at,
    )

    # A retry later the same day must not re-derive a second glide or
    # double-write price_history.
    run_recompute(session, day8, now=now8 + timedelta(minutes=10))
    session.refresh(artist)

    assert artist.anchor_cents == first_anchor
    assert artist.anchor_target_cents == first_target
    assert artist.glide_start_at == first_glide_start

    history_count = session.scalar(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.artist_id == artist.id)
    )
    assert history_count == 2  # listing + one reversion, not two


def test_rerun_backdated_as_of_is_idempotent_for_reversion(
    session: Session, make_artist: ArtistFactory
) -> None:
    """A backfill's `now` is wall-clock time when the backfill actually
    runs, unrelated to the backdated `as_of_date` -- unlike every other
    test here, whose `_now_for` helper makes `now.date() == as_of_date`
    true by construction. Two retries of the SAME as_of_date, each with
    a `now` on a different, much-later, mutually different wall-clock
    day, must still converge to exactly one reversion."""
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    states = _advance_all(session, states, day8)

    backfill_now_1 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    backfill_now_2 = datetime(2026, 6, 3, 9, 30, tzinfo=UTC)
    run_recompute(session, day8, now=backfill_now_1)

    artist = states[0].artist
    session.refresh(artist)
    first_anchor, first_target, first_glide_start = (
        artist.anchor_cents,
        artist.anchor_target_cents,
        artist.glide_start_at,
    )

    run_recompute(session, day8, now=backfill_now_2)
    session.refresh(artist)

    assert artist.anchor_cents == first_anchor
    assert artist.anchor_target_cents == first_target
    assert artist.glide_start_at == first_glide_start  # NOT backfill_now_2

    history_count = session.scalar(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.artist_id == artist.id)
    )
    assert history_count == 2  # listing + exactly one reversion, not two


# --- oracle-manipulation quarantine ---------------------------------------


def test_ratio_divergence_flag_holds_score(session: Session, make_artist: ArtistFactory) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    target = states[0]
    spiked_playcount = target.playcount * target.playcount_growth * 10  # bot-scrobble spike
    states[0] = _advance_day(session, target, day8, playcount_override=spiked_playcount)
    states[1:] = _advance_all(session, states[1:], day8)

    result = run_recompute(session, day8, now=_now_for(day8))

    artist = states[0].artist
    assert any(f["slug"] == artist.slug for f in result.newly_flagged)

    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist.id, FlaggedArtist.as_of_date == day8
        )
    )
    assert flag is not None
    assert "ratio_divergence" in flag.reason

    day7_snap = _snapshot(session, artist.id, day7)
    day8_snap = _snapshot(session, artist.id, day8)
    assert day7_snap is not None and day8_snap is not None
    assert day8_snap.index_score == day7_snap.index_score
    assert day8_snap.fair_value_cents == day7_snap.fair_value_cents

    quarantine = day8_snap.components["quarantine"]
    assert isinstance(quarantine, dict)
    # A 10x playcount spike is also, incidentally, the single biggest
    # score mover in the cross-section that day -- percentile_move can
    # legitimately co-fire. ratio_divergence is the trigger under test.
    assert "ratio_divergence" in quarantine["triggers"]


def test_percentile_move_flag_holds_score(session: Session, make_artist: ArtistFactory) -> None:
    states = _seed_steady(session, make_artist, count=12, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    target = states[0]
    # Both signals jump by the same large factor -- a big, matched move
    # that should NOT read as ratio-divergence (the playcount/listeners
    # ratio is unchanged), only as an outsized day-over-day score swing.
    jumped_listeners = target.listeners * target.listeners_growth * 3
    jumped_playcount = target.playcount * target.playcount_growth * 3
    states[0] = _advance_day(
        session,
        target,
        day8,
        listeners_override=jumped_listeners,
        playcount_override=jumped_playcount,
    )
    states[1:] = _advance_all(session, states[1:], day8)

    run_recompute(session, day8, now=_now_for(day8))

    artist = states[0].artist
    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist.id, FlaggedArtist.as_of_date == day8
        )
    )
    assert flag is not None
    assert "percentile_move" in flag.reason
    assert "ratio_divergence" not in flag.reason

    day7_snap = _snapshot(session, artist.id, day7)
    day8_snap = _snapshot(session, artist.id, day8)
    assert day7_snap is not None and day8_snap is not None
    assert day8_snap.index_score == day7_snap.index_score
    assert day8_snap.fair_value_cents == day7_snap.fair_value_cents


def test_flag_persists_until_manually_cleared(session: Session, make_artist: ArtistFactory) -> None:
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    target = states[0]
    spiked_playcount = target.playcount * target.playcount_growth * 10
    states[0] = _advance_day(session, target, day8, playcount_override=spiked_playcount)
    states[1:] = _advance_all(session, states[1:], day8)
    run_recompute(session, day8, now=_now_for(day8))

    artist_id = states[0].artist.id
    day7_snap = _snapshot(session, artist_id, day7)
    assert day7_snap is not None

    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist_id, FlaggedArtist.as_of_date == day8
        )
    )
    assert flag is not None and flag.cleared_at is None

    # Day 9: the base window ([day1, day5]) never touches day8's spike,
    # so the fresh detection would not fire again -- but the quarantine
    # is human-cleared, not auto-cleared, so it must still hold.
    day9 = _day(9)
    states = _advance_all(session, states, day9)
    run_recompute(session, day9, now=_now_for(day9))
    day9_snap = _snapshot(session, artist_id, day9)
    assert day9_snap is not None
    assert day9_snap.index_score == day7_snap.index_score
    assert day9_snap.fair_value_cents == day7_snap.fair_value_cents

    # A human clears the day-8 flag.
    flag.cleared_at = datetime.now(UTC)
    flag.cleared_by = "reviewer@example.com"
    session.flush()

    day10 = _day(10)
    states = _advance_all(session, states, day10)
    run_recompute(session, day10, now=_now_for(day10))
    day10_snap = _snapshot(session, artist_id, day10)
    assert day10_snap is not None
    # Fresh computation resumed -- proven by the score actually moving
    # off the value it had been frozen at for two days. (A big first
    # catch-up move can legitimately trip percentile_move as a *new*
    # flag in its own right; that's a separate, correctly-functioning
    # check, not evidence the old quarantine failed to clear.)
    assert _effective_fair_value(day10_snap) != day7_snap.fair_value_cents


def test_clear_flag_resumes_fresh_computation(session: Session, make_artist: ArtistFactory) -> None:
    """`clear_flag` (the helper `api/routers/admin.py` and `cli.py`'s
    `fake-history` auto-clear both share) is the programmatic equivalent
    of the manual `flag.cleared_at = ...` in the test above -- same
    end-to-end effect, exercised through the real function instead of a
    direct attribute assignment."""
    states = _seed_steady(session, make_artist, count=10, days=8)
    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))

    day8 = _day(8)
    target = states[0]
    spiked_playcount = target.playcount * target.playcount_growth * 10
    states[0] = _advance_day(session, target, day8, playcount_override=spiked_playcount)
    states[1:] = _advance_all(session, states[1:], day8)
    run_recompute(session, day8, now=_now_for(day8))

    artist_id = states[0].artist.id
    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist_id, FlaggedArtist.as_of_date == day8
        )
    )
    assert flag is not None and flag.cleared_at is None

    cleared = clear_flag(session, artist_id, day8, cleared_by="ax fake-history")
    session.flush()

    assert cleared is True
    session.refresh(flag)
    assert flag.cleared_at is not None
    assert flag.cleared_by == "ax fake-history"

    day9 = _day(9)
    states = _advance_all(session, states, day9)
    run_recompute(session, day9, now=_now_for(day9))
    day7_snap = _snapshot(session, artist_id, day7)
    day9_snap = _snapshot(session, artist_id, day9)
    assert day7_snap is not None and day9_snap is not None
    # Cleared immediately after day 8, so day 9's computation is already
    # fresh -- no lingering hold, unlike the manual-clear test above where
    # the flag stayed open across day 9.
    assert _effective_fair_value(day9_snap) != day7_snap.fair_value_cents


def test_clear_flag_returns_false_for_no_open_flag(
    session: Session, make_artist: ArtistFactory
) -> None:
    artist = make_artist("Never Flagged")
    assert clear_flag(session, artist.id, BASE_DATE, cleared_by="someone") is False


def test_clear_flag_is_a_noop_on_an_already_cleared_flag(
    session: Session, make_artist: ArtistFactory
) -> None:
    artist = make_artist("Already Cleared")
    session.add(
        FlaggedArtist(
            artist_id=artist.id,
            as_of_date=BASE_DATE,
            reason="percentile_move",
            cleared_at=datetime.now(UTC),
            cleared_by="reviewer@example.com",
        )
    )
    session.flush()

    assert clear_flag(session, artist.id, BASE_DATE, cleared_by="someone-else") is False

    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == artist.id, FlaggedArtist.as_of_date == BASE_DATE
        )
    )
    assert flag is not None
    # The original clearer's attribution is untouched by the no-op call.
    assert flag.cleared_by == "reviewer@example.com"


def test_first_day_flag_stays_warming_up(session: Session, make_artist: ArtistFactory) -> None:
    _seed_steady(session, make_artist, count=9, days=8)

    target = make_artist("Bot Boosted")
    listeners = 60_000.0
    listeners_growth = 1.016
    playcount = listeners * 4.0
    playcount_growth = listeners_growth * 1.005
    for day in range(7):
        _add_metrics(session, target.id, _day(day), round(listeners), round(playcount))
        listeners *= listeners_growth
        playcount *= playcount_growth
    day7 = _day(7)
    _add_metrics(session, target.id, day7, round(listeners), round(playcount * 10))
    session.flush()

    result = run_recompute(session, day7, now=_now_for(day7))

    assert target.slug in result.skipped_first_day_flagged
    assert any(f["slug"] == target.slug for f in result.newly_flagged)
    assert _snapshot(session, target.id, day7) is None
    session.refresh(target)
    assert target.listed_at is None

    flag = session.scalar(
        select(FlaggedArtist).where(
            FlaggedArtist.artist_id == target.id, FlaggedArtist.as_of_date == day7
        )
    )
    assert flag is not None


# --- real, end-to-end I8: fair value falls on monotonically rising data --


def test_i8_laggard_fair_value_falls_while_raw_counts_keep_rising(
    session: Session, make_artist: ArtistFactory
) -> None:
    """The product claim, exercised through the real job and a real
    database rather than `compute_index` in isolation (Phase 2 already
    covers that): a consistently below-median grower's fair value falls
    from one published day to the next, even though its own raw
    `listeners`/`playcount` rise every single day -- rule 5's whole
    reason for existing, and PLAN.md's Phase 3 "confirm some artists'
    fair values went DOWN" check, automated.

    `_effective_fair_value` reads through a quarantine if the percentile-
    move check happens to also flag this artist's day-over-day change
    (a large, real move is exactly the kind of thing that check is
    designed to catch) -- the audited `would_have_computed` value is
    what the real computation produced either way, which is the claim
    under test.
    """
    states = _seed_steady(session, make_artist, count=9, days=8)

    laggard = make_artist("Laggard")
    listeners = 55_000.0
    playcount = listeners * 4.0
    # A playcount/listeners ratio in the same range `_seed_steady` gives
    # its population (~1.004-1.007/day), so the laggard's divergence sits
    # inside the population's own baseline spread rather than reading as
    # its own (unrelated) ratio-divergence outlier -- only the *level* of
    # growth is what's under test here.
    playcount_ratio = 1.0045
    # Days 0-6 grow at a normal rate; day 7 onward decelerates sharply.
    # The day-8 growth window (day1..day8) then contains mostly slow days
    # where day-7's window (day0..day7) contained mostly normal ones, so
    # the rolling 7-day rate genuinely worsens from day7 to day8.
    listeners_schedule = [1.010] * 7 + [1.0004, 1.0002]
    for day, g in enumerate(listeners_schedule):
        _add_metrics(session, laggard.id, _day(day), round(listeners), round(playcount))
        listeners *= g
        playcount *= g * playcount_ratio

    session.flush()

    day7 = _day(7)
    run_recompute(session, day7, now=_now_for(day7))
    day7_snap = _snapshot(session, laggard.id, day7)
    assert day7_snap is not None

    day8 = _day(8)
    states = _advance_all(session, states, day8)
    run_recompute(session, day8, now=_now_for(day8))
    day8_snap = _snapshot(session, laggard.id, day8)
    assert day8_snap is not None

    assert _effective_fair_value(day8_snap) < _effective_fair_value(day7_snap)

    # The raw claim, unconditionally true regardless of quarantine: every
    # one of the laggard's own counts still went up.
    last_listeners = session.scalar(
        select(MetricSnapshot.value).where(
            MetricSnapshot.artist_id == laggard.id,
            MetricSnapshot.as_of_date == day8,
            MetricSnapshot.metric_key == "listeners",
        )
    )
    first_listeners = session.scalar(
        select(MetricSnapshot.value).where(
            MetricSnapshot.artist_id == laggard.id,
            MetricSnapshot.as_of_date == _day(0),
            MetricSnapshot.metric_key == "listeners",
        )
    )
    assert last_listeners is not None and first_listeners is not None
    assert last_listeners > first_listeners


# --- quarantine-check unit tests (pure functions, no DB needed) -----------


def test_ratio_divergence_is_one_sided_negative_does_not_flag() -> None:
    def _result(playcount_g: float, listeners_g: float) -> ArtistDayResult:
        return ArtistDayResult(
            index_score=50.0,
            fair_value_cents=1000,
            components={
                "signals": {
                    "lastfm.playcount": {"g": playcount_g},
                    "lastfm.listeners": {"g": listeners_g},
                }
            },
        )

    computed = {i: _result(0.05, 0.05) for i in range(1, 10)}
    computed[99] = _result(0.02, 0.20)  # large NEGATIVE divergence

    flags = _ratio_divergence_flags(computed)
    assert 99 not in flags


def test_percentile_move_flags_excludes_multi_day_gap_artist() -> None:
    as_of = _day(10)
    computed = {
        i: ArtistDayResult(index_score=50.0, fair_value_cents=1000, components={})
        for i in range(1, 10)
    }
    computed[99] = ArtistDayResult(index_score=90.0, fair_value_cents=1000, components={})

    prev_snapshots = {
        i: IndexSnapshot(
            artist_id=i,
            as_of_date=as_of - timedelta(days=1),
            index_score=50.0,
            fair_value_cents=1000,
            components={},
        )
        for i in range(1, 10)
    }
    prev_snapshots[99] = IndexSnapshot(
        artist_id=99,
        as_of_date=as_of - timedelta(days=3),
        index_score=10.0,
        fair_value_cents=1000,
        components={},
    )  # stale, 3-day-old prior

    flags = _percentile_move_flags(computed, prev_snapshots, as_of)
    assert 99 not in flags


def test_net_supplies_returns_native_int_not_decimal(
    session: Session, make_artist: ArtistFactory
) -> None:
    artist_a = make_artist("Has Supply")
    artist_b = make_artist("Zero Supply")
    user = User(username="tester")
    session.add(user)
    session.flush()
    session.add(
        Transaction(
            user_id=user.id,
            artist_id=artist_a.id,
            kind="BUY",
            cash_delta_cents=-1000,
            share_delta=7,
            exec_price_cents=100,
        )
    )
    session.flush()

    supplies = _net_supplies(session, [artist_a.id, artist_b.id])

    assert supplies[artist_a.id] == 7
    assert type(supplies[artist_a.id]) is int
    assert not isinstance(supplies[artist_a.id], Decimal)
    assert supplies.get(artist_b.id, 0) == 0
