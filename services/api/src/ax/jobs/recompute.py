"""Nightly index recompute + reversion.

Reads `metric_snapshots`, runs the cross-sectional index through the real
`ax.core.index.compute_index`, writes `index_snapshots`, lists any artist
crossing `MIN_SNAPSHOTS_TO_LIST` for the first time, and runs the nightly
reversion (`ax.core.amm.plan_reversion`) for every already-listed artist,
appending `price_history` rows. Appended to the nightly Action after the
snapshot step (PLAN.md Phase 3).

**Oracle manipulation is the attack the AMM's own guardrails do not
cover** (PLAN.md): fees/slippage/position-caps defend the *gap* between
market price and fair value, not fair value itself. Two independent,
cross-sectional statistical checks run here every night:

  - **Ratio divergence.** Bot scrobbles inflate `playcount` while barely
    moving unique `listeners`. `playcount_growth - listeners_growth`,
    more than `RATIO_DIVERGENCE_MAD_THRESHOLD` robust MADs *above* the
    universe median, is that signature -- one-sided by design, since a
    large negative divergence isn't the bot-scrobble attack this check
    exists for.
  - **Percentile move.** A day-over-day index-score move landing beyond
    `PERCENTILE_MOVE_THRESHOLD` of the same day's cross-sectional move
    distribution.

Either one **quarantines** the artist: its published `index_score` /
`fair_value_cents` are held at the previous value -- and, so a held day
can never partially leak into the score via EWMA decay, the artist's
entire `components` (including the per-signal EWMA carry state) are
copied forward unchanged, with a `quarantine` audit key recording what
was actually observed and why it was suppressed. The artist keeps
trading; only its fair value stops responding. A quarantine persists
across days -- even past days where the trigger stops re-firing -- until
a human clears it (`flagged_artists.cleared_at`); there is no
auto-clear and, as of Phase 3, no clearing UI, only direct DB access.
**PLAN.md follow-up: surface `flagged_artists` in an admin view in a
later phase rather than relying on direct DB access indefinitely.**

**`SELECT ... FOR UPDATE` on the artist row, retrofitted in Phase 4.**
`POST /trades` (`api/routers/trades.py`) is now a concurrent writer of
`anchor_cents`/`anchor_target_cents`/`glide_start_at`/`glide_end_at`/
`net_supply`-derived state on the same `artists` row this job mutates in
`_apply_market_state` -- without a lock, a nightly reversion and an
in-flight trade could race on those columns. `_apply_market_state` takes
the lock (via `session.refresh(artist, with_for_update=True)`) itself,
right before its first write, rather than up front for every artist in
the cross-section: only the subset actually being listed or reverted
needs it, and holding ~200 row locks for the full duration of the
cross-sectional computation would serialize trades against this job for
no reason. `POST /trades` locks its own artist row first, so the two
writers always contend on the same single row-level lock, never a
larger set -- no additional lock-ordering rule is needed between them.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ax.core.amm import ReversionPlan, listing_slope_uc, plan_reversion
from ax.core.config import (
    GROWTH_BASE_WINDOW_DAYS,
    GROWTH_LOOKBACK_DAYS,
    MIN_SNAPSHOTS_TO_LIST,
    PERCENTILE_MOVE_THRESHOLD,
    RATIO_DIVERGENCE_MAD_THRESHOLD,
    SIGNAL_WEIGHTS,
)
from ax.core.index import (
    ArtistDayInput,
    ArtistDayResult,
    SignalInput,
    compute_index,
    pick_base_snapshot,
    robust_z,
)
from ax.db.models import (
    Artist,
    FlaggedArtist,
    IndexSnapshot,
    MetricSnapshot,
    PriceHistory,
    Transaction,
)
from ax.jobs.snapshot import active_artists
from ax.providers.lastfm import METRIC_LISTENERS, METRIC_PLAYCOUNT
from ax.providers.lastfm import SOURCE as _LASTFM_SOURCE

log = logging.getLogger(__name__)

_PLAYCOUNT_KEY = f"{_LASTFM_SOURCE}.{METRIC_PLAYCOUNT}"
_LISTENERS_KEY = f"{_LASTFM_SOURCE}.{METRIC_LISTENERS}"

_LOOKBACK_WINDOW_DAYS = GROWTH_LOOKBACK_DAYS + GROWTH_BASE_WINDOW_DAYS


@dataclass
class RecomputeResult:
    as_of_date: date
    eligible: int = 0
    published: int = 0
    held: int = 0
    newly_listed: list[str] = field(default_factory=list)
    newly_flagged: list[dict[str, object]] = field(default_factory=list)
    skipped_first_day_flagged: list[str] = field(default_factory=list)
    skipped_small_cross_section: bool = False

    def summary(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "eligible": self.eligible,
            "published": self.published,
            "held": self.held,
            "newly_listed": self.newly_listed,
            "newly_flagged": self.newly_flagged,
            "skipped_first_day_flagged": self.skipped_first_day_flagged,
            "skipped_small_cross_section": self.skipped_small_cross_section,
        }


def _snapshot_day_counts(
    session: Session, artist_ids: list[int], as_of_date: date
) -> dict[int, int]:
    """Distinct historical days on record per artist, through `as_of_date`
    inclusive -- the `MIN_SNAPSHOTS_TO_LIST` gate. A separate, stricter
    check than `compute_index`'s own eligibility (which only needs a base
    snapshot somewhere in the window and would let a 5-day-old artist in):
    this is the buffer that keeps a brand-new artist's first published
    score off a bare minimum of noisy data."""
    if not artist_ids:
        return {}
    stmt = (
        select(MetricSnapshot.artist_id, func.count(func.distinct(MetricSnapshot.as_of_date)))
        .where(
            MetricSnapshot.artist_id.in_(artist_ids),
            MetricSnapshot.as_of_date <= as_of_date,
        )
        .group_by(MetricSnapshot.artist_id)
    )
    return dict(session.execute(stmt).all())  # type: ignore[arg-type]


def _load_metric_window(
    session: Session, artist_ids: list[int], as_of_date: date
) -> dict[int, dict[str, dict[date, int]]]:
    """`{artist_id: {"source.metric_key": {as_of_date: value}}}` for every
    row in `[as_of_date - _LOOKBACK_WINDOW_DAYS, as_of_date]` -- one bulk
    query rather than one per artist per signal."""
    if not artist_ids:
        return {}
    window_start = as_of_date - timedelta(days=_LOOKBACK_WINDOW_DAYS)
    stmt = select(MetricSnapshot).where(
        MetricSnapshot.artist_id.in_(artist_ids),
        MetricSnapshot.as_of_date >= window_start,
        MetricSnapshot.as_of_date <= as_of_date,
    )
    series: dict[int, dict[str, dict[date, int]]] = {}
    for row in session.scalars(stmt):
        signal_key = f"{row.source}.{row.metric_key}"
        series.setdefault(row.artist_id, {}).setdefault(signal_key, {})[row.as_of_date] = row.value
    return series


def _latest_prior_index_snapshots(
    session: Session, artist_ids: list[int], as_of_date: date
) -> dict[int, IndexSnapshot]:
    """Each artist's most recent `index_snapshots` row strictly before
    `as_of_date` -- not necessarily `as_of_date - 1`, since a day the
    whole cross-section was skipped (too few eligible artists) leaves a
    gap. Supplies both `prev_ewma` (per-signal EWMA carry) and the
    fallback value a quarantine holds.

    `DISTINCT ON` (Postgres-only, already established precedent in this
    codebase) keeps this to one row per artist at the database level
    rather than fetching every historical snapshot -- full `components`
    JSONB included -- and discarding all but the latest in Python."""
    if not artist_ids:
        return {}
    stmt = (
        select(IndexSnapshot)
        .distinct(IndexSnapshot.artist_id)
        .where(IndexSnapshot.artist_id.in_(artist_ids), IndexSnapshot.as_of_date < as_of_date)
        .order_by(IndexSnapshot.artist_id, IndexSnapshot.as_of_date.desc())
    )
    return {row.artist_id: row for row in session.scalars(stmt)}


def _unresolved_flagged_artist_ids(
    session: Session, artist_ids: list[int], as_of_date: date
) -> set[int]:
    """Artists still under an *earlier* quarantine that a human has not
    yet cleared (`cleared_at IS NULL`) -- the "until cleared" half of the
    mitigation. Deliberately excludes `as_of_date` itself: today's own
    flag (if any) is applied via the fresh detection below, not this
    carry-forward check."""
    if not artist_ids:
        return set()
    stmt = (
        select(FlaggedArtist.artist_id)
        .where(
            FlaggedArtist.artist_id.in_(artist_ids),
            FlaggedArtist.as_of_date < as_of_date,
            FlaggedArtist.cleared_at.is_(None),
        )
        .distinct()
    )
    return set(session.scalars(stmt))


def _already_published_today(session: Session, artist_ids: list[int], as_of_date: date) -> set[int]:
    """Artists that already have an `index_snapshots` row for exactly
    `as_of_date` -- captured once, before the per-artist loop starts
    writing this run's own rows (this run's own `_upsert_index_snapshot`
    calls are visible to later reads in the same uncommitted transaction,
    which would otherwise make every artist look "already published"
    from the second loop iteration onward). This is the real identity
    key `run_recompute` is idempotent on (CLAUDE.md rule 7) -- unlike
    `Artist.glide_start_at`, it's independent of `now`."""
    if not artist_ids:
        return set()
    stmt = select(IndexSnapshot.artist_id).where(
        IndexSnapshot.artist_id.in_(artist_ids), IndexSnapshot.as_of_date == as_of_date
    )
    return set(session.scalars(stmt))


def _net_supplies(session: Session, artist_ids: list[int]) -> dict[int, int]:
    """Current net supply per already-listed artist, derived from the
    ledger (`Transaction` is append-only and the sole source of truth --
    CLAUDE.md rule 8). Always empty until Phase 4 lands a trade route
    that writes `share_delta` rows. Batched like every other per-artist
    lookup in this module rather than one query per artist inside the
    loop.

    Postgres infers `sum(bigint) -> numeric` at the SQL level, and
    psycopg decodes NUMERIC as `decimal.Decimal` regardless of what
    SQLAlchemy's own compile-time type inference reports for the
    expression (BIGINT) -- the `int(...)` cast below is deliberate and
    explicit (CLAUDE.md rule 1: never float, never NUMERIC on
    money-adjacent math), not a reliance on SQLAlchemy or the driver to
    launder the type back on its own.

    An artist with zero `Transaction` rows is simply absent from the
    result (a GROUP BY omits it -- no `coalesce` needed here, unlike a
    single-artist scalar query); callers use `.get(artist_id, 0)`.
    """
    if not artist_ids:
        return {}
    stmt = (
        select(Transaction.artist_id, func.sum(Transaction.share_delta))
        .where(Transaction.artist_id.in_(artist_ids))
        .group_by(Transaction.artist_id)
    )
    return {artist_id: int(total) for artist_id, total in session.execute(stmt)}


def _build_day_input(
    history_ok_ids: list[int],
    series: dict[int, dict[str, dict[date, int]]],
    prev_snapshots: dict[int, IndexSnapshot],
    as_of_date: date,
) -> dict[int, ArtistDayInput]:
    """One artist enters the cross-section only if every configured
    signal has both today's value and a base value inside the window
    (C6) -- same rule `ax backtest` applies against a CSV, here against
    real `metric_snapshots`."""
    day_input: dict[int, ArtistDayInput] = {}
    for artist_id in history_ok_ids:
        metrics = series.get(artist_id, {})
        signals: dict[str, SignalInput] = {}
        prev = prev_snapshots.get(artist_id)
        prev_signals = prev.components.get("signals", {}) if prev is not None else {}

        for signal_key in SIGNAL_WEIGHTS:
            dates_to_values = metrics.get(signal_key, {})
            if as_of_date not in dates_to_values:
                break
            base = pick_base_snapshot(dates_to_values, as_of_date)
            if base is None:
                break
            base_value, gap_days = base

            prev_ewma = None
            info = prev_signals.get(signal_key) if isinstance(prev_signals, dict) else None
            if isinstance(info, dict):
                prev_ewma = info.get("ewma")

            signals[signal_key] = SignalInput(
                current=dates_to_values[as_of_date],
                base=base_value,
                gap_days=gap_days,
                prev_ewma=prev_ewma,
            )
        else:
            day_input[artist_id] = ArtistDayInput(
                signals=signals, listeners=metrics[_LISTENERS_KEY][as_of_date]
            )

    return day_input


def _ratio_divergence_flags(computed: dict[int, ArtistDayResult]) -> dict[int, dict[str, object]]:
    """C15 (Phase 3): `playcount_growth - listeners_growth`, more than
    `RATIO_DIVERGENCE_MAD_THRESHOLD` robust MADs *above* the cross-sectional
    median -- the signature of scrobble bots (playcount explodes, unique
    listeners barely move). One-sided by design: a large *negative*
    divergence (listeners outpacing playcount) is not the bot-scrobble
    attack this check exists for, and flagging it would risk quarantining
    a genuinely breaking-out artist. Unclamped z (`clamp=math.inf`): the
    score's own +-3 clamp would make "beyond 3 MAD" indistinguishable from
    "clamped at the boundary"."""
    if _PLAYCOUNT_KEY not in SIGNAL_WEIGHTS or _LISTENERS_KEY not in SIGNAL_WEIGHTS:
        return {}

    divergences: dict[int, float] = {}
    for artist_id, result in computed.items():
        signals = result.components["signals"]
        assert isinstance(signals, dict)
        divergences[artist_id] = signals[_PLAYCOUNT_KEY]["g"] - signals[_LISTENERS_KEY]["g"]

    keys = list(divergences)
    z_scores = robust_z([divergences[k] for k in keys], clamp=math.inf)

    return {
        artist_id: {"divergence": divergences[artist_id], "z": z}
        for artist_id, z in zip(keys, z_scores, strict=True)
        if z >= RATIO_DIVERGENCE_MAD_THRESHOLD
    }


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; `pct` in (0, 1)."""
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(pct * len(ordered)) - 1))
    return ordered[idx]


def _percentile_move_flags(
    computed: dict[int, ArtistDayResult],
    prev_snapshots: dict[int, IndexSnapshot],
    as_of_date: date,
) -> dict[int, dict[str, object]]:
    """Any artist whose day-over-day |index_score delta| lands at or
    beyond the `PERCENTILE_MOVE_THRESHOLD` percentile of today's own
    cross-sectional move distribution (PLAN.md's percentile review
    queue). Artists with no prior score (about to be newly listed) have
    no delta to measure and are naturally exempt. Also exempt: an artist
    whose only prior `index_snapshots` row is more than one day old (a
    data gap) -- comparing its multi-day delta against everyone else's
    true single-day deltas in the same percentile pool would be apples
    to oranges."""
    deltas: dict[int, float] = {
        artist_id: abs(result.index_score - prev_snapshots[artist_id].index_score)
        for artist_id, result in computed.items()
        if artist_id in prev_snapshots
        and prev_snapshots[artist_id].as_of_date == as_of_date - timedelta(days=1)
    }
    if len(deltas) < 2:
        return {}

    threshold = _percentile(list(deltas.values()), PERCENTILE_MOVE_THRESHOLD)
    return {
        artist_id: {"delta": delta, "threshold": threshold}
        for artist_id, delta in deltas.items()
        if delta >= threshold
    }


def _upsert_index_snapshot(
    session: Session,
    artist_id: int,
    as_of_date: date,
    index_score: float,
    fair_value_cents: int,
    components: dict[str, object],
) -> None:
    """Sibling of `ax.jobs.snapshot.upsert_metrics` (multi-row, with an
    intentional `func.now()` override) and `ax.cli.seed_artists`'
    single-row upsert -- not unified with either, since none of the three
    are shaped alike enough to share one helper without adding a layer of
    indirection none of the four call sites actually need."""
    stmt = insert(IndexSnapshot).values(
        artist_id=artist_id,
        as_of_date=as_of_date,
        index_score=index_score,
        fair_value_cents=fair_value_cents,
        components=components,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["artist_id", "as_of_date"],
        set_={
            "index_score": stmt.excluded.index_score,
            "fair_value_cents": stmt.excluded.fair_value_cents,
            "components": stmt.excluded.components,
        },
    )
    session.execute(stmt)


def _upsert_flag(
    session: Session,
    artist_id: int,
    as_of_date: date,
    triggers: list[str],
    detail: dict[str, object],
) -> None:
    stmt = insert(FlaggedArtist).values(
        artist_id=artist_id,
        as_of_date=as_of_date,
        reason=",".join(triggers),
        detail=detail,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["artist_id", "as_of_date"],
        set_={"reason": stmt.excluded.reason, "detail": stmt.excluded.detail},
    )
    session.execute(stmt)


def _apply_market_state(
    session: Session,
    artist: Artist,
    fair_value_cents: int,
    as_of_date: date,
    now: datetime,
    already_processed_today: bool,
    net_supplies: dict[int, int],
    result: RecomputeResult,
) -> None:
    """Listing (first-ever score) or nightly reversion (already listed),
    for one artist whose `index_snapshots` row for `as_of_date` has just
    been written -- held (quarantined) or fresh, the reversion step
    doesn't care which; a held fair value simply produces gap = 0 once
    price has already converged to it, which *is* "fair value stops
    responding"."""
    if artist.listed_at is None:
        # Idempotent by construction: a same-`as_of_date` retry finds
        # `listed_at` already set and takes the reversion branch instead
        # (itself idempotent -- see below), never re-listing.
        #
        # Locked here, not at the top of the function: an artist about to
        # be listed for the first time cannot already be `POST /trades`'s
        # target (it isn't tradable until `listed_at` is set), so this
        # acquisition can't contend with a real trade -- it exists purely
        # so a concurrent reader elsewhere taking the same lock convention
        # sees a consistent row, not because a race is actually possible
        # on a first listing.
        session.refresh(artist, with_for_update=True)
        slope_uc = listing_slope_uc()
        artist.slope_microcents_per_share = slope_uc
        artist.anchor_cents = fair_value_cents
        artist.anchor_target_cents = fair_value_cents
        artist.glide_start_at = now
        artist.glide_end_at = now
        artist.listed_at = now
        # `at` deliberately omitted: the column default is
        # `clock_timestamp()`, not the job's injected `now` -- CLAUDE.md's
        # rule against ever writing a transaction-time value into
        # `price_history.at`.
        session.add(
            PriceHistory(
                artist_id=artist.id,
                market_price_cents=fair_value_cents,
                fair_value_cents=fair_value_cents,
                net_supply=0,
                source="listing",
            )
        )
        result.newly_listed.append(artist.slug)
        return

    # Idempotent per (artist, as_of_date): a retry that already has an
    # `index_snapshots` row for `as_of_date` -- the real identity key,
    # independent of `now` -- skips, rather than re-deriving a second
    # glide and double-writing `price_history`. (Not keyed off
    # `glide_start_at`: that field is always stamped from `now`, which a
    # backfilled `as_of_date` can differ from arbitrarily, so comparing
    # its date to `as_of_date` only worked by coincidence on an ordinary
    # same-day run.)
    if already_processed_today:
        return

    # Locked here, right before the read this job's own write depends
    # on -- the same row `POST /trades` locks before mutating supply and
    # reading these same anchor/glide columns for pricing. Either writer
    # reaching the row first makes the other block until it commits, so
    # this job never reverts an artist using an anchor/glide state a
    # concurrent trade is mid-write on. `net_supply` below still comes
    # from the batched pre-loop read (`_net_supplies`), not a fresh
    # per-artist query under this lock -- a trade committing in the
    # narrow window between that batch read and this lock can leave the
    # reversion's gap measurement using a supply figure that's already
    # one trade stale. Bounded and self-correcting (the next night's
    # reversion measures the true current gap), not a ledger-correctness
    # issue -- the same category of accepted staleness as the Phase 3
    # quarantine-baseline note above.
    session.refresh(artist, with_for_update=True)

    assert artist.anchor_cents is not None
    assert artist.anchor_target_cents is not None
    assert artist.glide_start_at is not None
    assert artist.glide_end_at is not None
    assert artist.slope_microcents_per_share is not None

    net_supply = net_supplies.get(artist.id, 0)
    plan: ReversionPlan = plan_reversion(
        anchor_cents=artist.anchor_cents,
        anchor_target_cents=artist.anchor_target_cents,
        glide_start=artist.glide_start_at,
        glide_end=artist.glide_end_at,
        slope_uc=artist.slope_microcents_per_share,
        net_supply=net_supply,
        fair_value_cents=fair_value_cents,
        now=now,
    )
    artist.anchor_cents = plan.anchor_cents
    artist.anchor_target_cents = plan.anchor_target_cents
    artist.glide_start_at = plan.glide_start_at
    artist.glide_end_at = plan.glide_end_at

    session.add(
        PriceHistory(
            artist_id=artist.id,
            market_price_cents=plan.anchor_cents,
            fair_value_cents=fair_value_cents,
            net_supply=net_supply,
            source="reversion",
        )
    )


def run_recompute(session: Session, as_of_date: date, *, now: datetime) -> RecomputeResult:
    """One night's index recompute, quarantine check, listing, and
    reversion. `now` is an explicit parameter (never `datetime.now()`
    inside), same as `as_of_date` -- both are supplied by the caller so
    the job stays deterministic and testable; the production endpoint
    passes `datetime.now(UTC)` and its own `.date()`.

    Commits once, at the end: unlike the snapshot job's 200 independent
    network calls, this is one in-memory cross-section computation
    followed by one batch of writes, so a partial failure should roll
    back the whole day's cross-section rather than leave half of it
    published.
    """
    result = RecomputeResult(as_of_date=as_of_date)

    artists = active_artists(session)
    if not artists:
        return result
    artist_by_id = {artist.id: artist for artist in artists}
    artist_ids = list(artist_by_id)

    history_counts = _snapshot_day_counts(session, artist_ids, as_of_date)
    history_ok_ids = [
        artist_id
        for artist_id in artist_ids
        if history_counts.get(artist_id, 0) >= MIN_SNAPSHOTS_TO_LIST
    ]

    series = _load_metric_window(session, history_ok_ids, as_of_date)
    prev_snapshots = _latest_prior_index_snapshots(session, artist_ids, as_of_date)
    day_input = _build_day_input(history_ok_ids, series, prev_snapshots, as_of_date)
    result.eligible = len(day_input)

    computed = compute_index(day_input)
    if not computed:
        result.skipped_small_cross_section = len(day_input) > 0
        return result

    ratio_flags = _ratio_divergence_flags(computed)
    percentile_flags = _percentile_move_flags(computed, prev_snapshots, as_of_date)
    unresolved_prior = _unresolved_flagged_artist_ids(session, list(computed), as_of_date)
    already_published_today = _already_published_today(session, list(computed), as_of_date)
    already_listed_ids = [
        artist_id for artist_id in computed if artist_by_id[artist_id].listed_at is not None
    ]
    net_supplies = _net_supplies(session, already_listed_ids)

    for artist_id, computed_result in computed.items():
        artist = artist_by_id[artist_id]
        prev = prev_snapshots.get(artist_id)

        triggers: list[str] = []
        detail: dict[str, object] = {}
        if artist_id in ratio_flags:
            triggers.append("ratio_divergence")
            detail["ratio_divergence"] = ratio_flags[artist_id]
        if artist_id in percentile_flags:
            triggers.append("percentile_move")
            detail["percentile_move"] = percentile_flags[artist_id]

        newly_flagged_today = bool(triggers)
        quarantined = newly_flagged_today or artist_id in unresolved_prior

        # Recorded once here, regardless of which branch below a
        # quarantined artist falls into -- `newly_flagged_today` implies
        # `quarantined`, and every quarantined artist takes one of the
        # two branches below, never the "else" published branch.
        if newly_flagged_today:
            log.warning(
                "oracle-manipulation quarantine triggered: %s (id=%s) as_of=%s triggers=%s",
                artist.slug,
                artist_id,
                as_of_date,
                triggers,
            )
            _upsert_flag(session, artist_id, as_of_date, triggers, detail)
            result.newly_flagged.append({"slug": artist.slug, "reasons": triggers})

        if quarantined and prev is None:
            # Nothing to hold to -- a first-eligible-day artist stays
            # warming_up rather than publishing a first price built on
            # data flagged as suspect (fail-safe, matching the existing
            # "no base snapshot -> warming_up" rule).
            result.skipped_first_day_flagged.append(artist.slug)
            continue

        if quarantined:
            assert prev is not None
            held_components = dict(prev.components)
            held_components["quarantine"] = {
                "as_of_date": as_of_date.isoformat(),
                "held_from": prev.as_of_date.isoformat(),
                "newly_flagged": newly_flagged_today,
                "triggers": triggers,
                "detail": detail,
                "would_have_computed": {
                    "index_score": computed_result.index_score,
                    "fair_value_cents": computed_result.fair_value_cents,
                },
            }
            _upsert_index_snapshot(
                session,
                artist_id,
                as_of_date,
                prev.index_score,
                prev.fair_value_cents,
                held_components,
            )
            result.held += 1
            final_fair_value = prev.fair_value_cents
        else:
            _upsert_index_snapshot(
                session,
                artist_id,
                as_of_date,
                computed_result.index_score,
                computed_result.fair_value_cents,
                computed_result.components,
            )
            result.published += 1
            final_fair_value = computed_result.fair_value_cents

        _apply_market_state(
            session,
            artist,
            final_fair_value,
            as_of_date,
            now,
            artist_id in already_published_today,
            net_supplies,
            result,
        )

    session.commit()
    return result
