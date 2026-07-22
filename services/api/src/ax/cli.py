"""`ax` — local development and operations CLI.

Phase 1 shipped `seed-artists` and `snapshot`; Phase 2 added `backtest`;
Phase 3 added `recompute`; Phase 4 added `reconcile`; Phase 5 adds
`fake-history`, `simulate-trades`, and `reset` — the dev-speed unlocks
PLAN.md's "Local dev and faking history" section describes, needed so
Phase 5 UI work never waits on real (weeks-long) Last.fm history. All
three are dev-only: never point them at production (CLAUDE.md).

`promote-admin` is a real production operator command (not dev-only): the
only way to grant `is_admin`, which gates `/admin/*` (the oracle-
manipulation review queue's clearing UI).
"""

import csv
import json
import logging
import math
import random
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from ax.api.routers.trades import TradeRequest, TradeSide, execute_trade
from ax.core.config import STARTING_BALANCE_CENTS
from ax.core.index import (
    ArtistDayInput,
    ArtistDayResult,
    SignalInput,
    compute_index,
    pick_base_snapshot,
)
from ax.core.ledger import grant_entries
from ax.db.ledger import lock_balance_cache, write_entries
from ax.db.models import TIER_BLUE_CHIP, Artist, FlaggedArtist, MetricSnapshot, User
from ax.db.session import get_engine, session_scope
from ax.jobs.leaderboard import run_leaderboard_snapshot
from ax.jobs.recompute import clear_flag, run_recompute
from ax.jobs.reconcile import run_reconcile
from ax.jobs.snapshot import active_artists, run_snapshot
from ax.logging_config import configure_third_party_logging
from ax.providers.lastfm import METRIC_LISTENERS, METRIC_PLAYCOUNT, LastfmProvider
from ax.providers.lastfm import SOURCE as LASTFM_SOURCE
from ax.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)

# services/api/src/ax/cli.py -> services/api/src/ax -> ... -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "artists_seed.json"
DEFAULT_BACKTEST_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "core"
    / "fixtures"
    / "backtest_metrics.csv"
)

# {artist_slug: {"source.metric_key": {as_of_date: value}}}
_MetricSeries = dict[str, dict[str, dict[date, int]]]


@app.callback()
def _configure(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    configure_third_party_logging()


@app.command("seed-artists")
def seed_artists(
    path: Annotated[Path, typer.Option(help="Seed JSON to load")] = DEFAULT_SEED_PATH,
) -> None:
    """Load the curated artist universe.

    Idempotent, and safe to re-run after regenerating the seed: matches on
    `slug` and updates the identity fields only. Market state
    (`anchor_cents`, the glide window, `listed_at`) is deliberately never
    touched — re-seeding must not reset a live market or relist a
    delisted artist.
    """
    total = _seed_artists(path)
    typer.echo(f"Seeded artists from {path.name}; {total} total in universe.")


def _seed_artists(path: Path) -> int:
    """Shared by the `seed-artists` command and `reset` (CLAUDE.md rule:
    `core/` stays pure, but this module-level split just avoids `reset`
    having to shell out to itself for a step it can call directly)."""
    records: list[dict[str, Any]] = json.loads(path.read_text())

    with session_scope() as session:
        for record in records:
            stmt = insert(Artist).values(
                slug=record["slug"],
                name=record["name"],
                lastfm_name=record["lastfm_name"],
                lastfm_mbid=record.get("lastfm_mbid"),
                tier=record["tier"],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={
                    "name": stmt.excluded.name,
                    "lastfm_name": stmt.excluded.lastfm_name,
                    "lastfm_mbid": stmt.excluded.lastfm_mbid,
                    "tier": stmt.excluded.tier,
                },
            )
            session.execute(stmt)

        total = session.scalar(select(func.count()).select_from(Artist))

    return total or 0


@app.command("snapshot")
def snapshot(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Date to record (default: today UTC)"),
    ] = None,
    limit: Annotated[int, typer.Option(help="Only snapshot the first N artists")] = 0,
) -> None:
    """Run the metric snapshot locally, without going through HTTP.

    Same code path the nightly endpoint uses, so a green run here means
    the deployed job works. `--limit` exists to smoke-test against the
    live API without spending a full 200-request budget.
    """
    settings = get_settings()
    as_of_date: date = as_of.date() if as_of else datetime.now(UTC).date()

    with session_scope() as session:
        artists = None
        if limit:
            # Same `delisted_at IS NULL` filter the job's own
            # `active_artists` applies. Without it the smoke-test path
            # snapshots artists the nightly run would skip — which is the
            # opposite of what a smoke test is for.
            artists = list(
                session.scalars(
                    select(Artist)
                    .where(Artist.delisted_at.is_(None))
                    .order_by(Artist.id)
                    .limit(limit)
                )
            )

        with LastfmProvider(settings.lastfm_api_key) as provider:
            result = run_snapshot(session, provider, as_of_date, artists=artists)

        stored = session.scalar(
            select(func.count())
            .select_from(MetricSnapshot)
            .where(MetricSnapshot.as_of_date == as_of_date)
        )

    typer.echo(json.dumps(result.summary(), indent=2))
    typer.echo(f"metric_snapshots rows for {as_of_date}: {stored}")

    if not result.ok:
        raise typer.Exit(code=1)


@app.command("recompute")
def recompute(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Date to recompute (default: today UTC)"),
    ] = None,
) -> None:
    """Run the index recompute + reversion job locally, without HTTP.

    Same code path `/internal/jobs/recompute` uses. Run after `snapshot`
    for the same date has landed real `metric_snapshots` rows -- this
    command reads them, it does not fetch anything itself.
    """
    as_of_date: date = as_of.date() if as_of else datetime.now(UTC).date()

    with session_scope() as session:
        result = run_recompute(session, as_of_date, now=datetime.now(UTC))

    typer.echo(json.dumps(result.summary(), indent=2))


@app.command("reconcile")
def reconcile() -> None:
    """Run the cache reconciliation job locally, without HTTP.

    Same code path `/internal/jobs/reconcile` uses: rebuilds
    `balance_cache`/`position_cache` from `transactions` for every user
    and overwrites any row that has drifted.
    """
    with session_scope() as session:
        result = run_reconcile(session, now=datetime.now(UTC))

    typer.echo(json.dumps(result.summary(), indent=2))


@app.command("leaderboard")
def leaderboard(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Date to snapshot (default: today UTC)"),
    ] = None,
) -> None:
    """Run the nightly leaderboard snapshot locally, without HTTP.

    Same code path `/internal/jobs/leaderboard` uses: writes tonight's
    `equity_snapshots` row for every user and rebuilds `leaderboard_scout`
    from current `position_cache` state. Run after `reconcile`.
    """
    as_of_date: date = as_of.date() if as_of else datetime.now(UTC).date()

    with session_scope() as session:
        result = run_leaderboard_snapshot(session, as_of_date, now=datetime.now(UTC))

    typer.echo(json.dumps(result.summary(), indent=2))


@app.command("promote-admin")
def promote_admin(
    username: Annotated[str, typer.Option(help="Existing user to grant admin access")],
) -> None:
    """Grants `is_admin` to an existing user -- the only way to create an
    admin, since the `/admin/*` endpoints have no self-service path to
    that flag. Meant to be run by whoever already has database/deploy
    access, the same trust tier as applying a migration; safe to run
    against production."""
    with session_scope() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            typer.echo(f"no such user: {username}", err=True)
            raise typer.Exit(code=1)
        user.is_admin = True

    typer.echo(f"{username} is now an admin.")


# --- Fake history + simulated trading (Phase 5 dev-speed unlocks) --------
#
# PLAN.md: "generate synthetic metric_snapshots via a GBM walk on
# listeners with a monotonic playcount derived from it, so the fake data
# carries the same pathology as the real data" -- the whole point is that
# `fake-history` must feed the *real* `compute_index`/`run_recompute`
# pipeline, never a shortcut that writes `index_snapshots` directly.

_BLUE_CHIP_LISTENERS_RANGE = (20_000.0, 200_000.0)
_GROWTH_LISTENERS_RANGE = (300.0, 3_000.0)
# Daily drift/vol tuned only to "looks like a plausible artist trajectory
# over 120 days," not calibrated against real Last.fm data the way
# core/config.py's economics constants are -- this is fake data by
# definition, so it lives here, not in core/config.py.
_BLUE_CHIP_DRIFT_VOL = (0.0008, 0.012)
_GROWTH_DRIFT_VOL = (0.006, 0.05)


def _require_not_production() -> None:
    """Refuses to proceed with `ENVIRONMENT=production` (CLAUDE.md: fake
    data must never reach production). Called by every dev-only command
    directly, not just by `reset`, so running `fake-history` or
    `simulate-trades` on its own is guarded the same as going through
    `reset`."""
    settings = get_settings()
    if settings.is_production:
        typer.echo("refusing to run: ENVIRONMENT=production", err=True)
        raise typer.Exit(code=1)


def _fake_history(days: int, seed: int) -> None:
    with session_scope() as session:
        artists = active_artists(session)
        if not artists:
            typer.echo("No artists in the universe -- run `ax seed-artists` first.")
            raise typer.Exit(code=1)

        # `start` below is anchored to wall-clock `today`, so two
        # invocations on different days map the same per-artist RNG walk
        # onto *different* calendar dates. Where the new window overlaps
        # already-published `as_of_date`s, `metric_snapshots` gets
        # overwritten with the new walk's values but `run_recompute`'s own
        # idempotency check silently skips re-scoring those dates --
        # leaving `metric_snapshots` and `index_snapshots`/`price_history`
        # permanently out of sync, with nothing erroring. `fake-history` is
        # reset-and-rebuild tooling (PLAN.md), not incremental, so refusing
        # against a non-fresh universe beats corrupting the alignment.
        already_seeded = session.scalar(
            select(MetricSnapshot.artist_id)
            .where(MetricSnapshot.artist_id.in_([a.id for a in artists]))
            .limit(1)
        )
        if already_seeded is not None:
            typer.echo(
                "metric_snapshots already has data -- fake-history is only "
                "deterministic against a fresh universe. Run `ax reset` first.",
                err=True,
            )
            raise typer.Exit(code=1)

        # One RNG per artist, seeded from (global seed, slug) so a series
        # is deterministic and independent of the universe's iteration
        # order -- adding or removing an unrelated artist never perturbs
        # everyone else's walk.
        listeners: dict[int, float] = {}
        playcount: dict[int, float] = {}
        rngs: dict[int, random.Random] = {}
        for artist in artists:
            artist_rng = random.Random(f"{seed}:{artist.slug}")
            lo, hi = (
                _BLUE_CHIP_LISTENERS_RANGE
                if artist.tier == TIER_BLUE_CHIP
                else _GROWTH_LISTENERS_RANGE
            )
            listeners[artist.id] = artist_rng.uniform(lo, hi)
            playcount[artist.id] = listeners[artist.id] * artist_rng.uniform(8.0, 20.0)
            rngs[artist.id] = artist_rng

        today = datetime.now(UTC).date()
        start = today - timedelta(days=days - 1)

        for offset in range(days):
            as_of_date = start + timedelta(days=offset)
            rows: list[dict[str, Any]] = []
            for artist in artists:
                artist_rng = rngs[artist.id]
                mu, sigma = (
                    _BLUE_CHIP_DRIFT_VOL if artist.tier == TIER_BLUE_CHIP else _GROWTH_DRIFT_VOL
                )
                z = artist_rng.gauss(0.0, 1.0)
                # Last.fm listeners is itself cumulative-ish (a monthly
                # active count that only slowly forgets), modeled here as
                # a GBM walk -- never negative, compounding growth/decay.
                listeners[artist.id] = max(
                    10.0, listeners[artist.id] * math.exp((mu - 0.5 * sigma * sigma) + sigma * z)
                )
                # playcount is monotonic non-decreasing by construction
                # (CLAUDE.md gotcha: real Last.fm playcount only ever goes
                # up) -- this is the property I8 exists to test against.
                plays_today = listeners[artist.id] * artist_rng.uniform(6.0, 14.0)
                playcount[artist.id] += max(0.0, plays_today)

                for metric_key, value in (
                    (METRIC_LISTENERS, round(listeners[artist.id])),
                    (METRIC_PLAYCOUNT, round(playcount[artist.id])),
                ):
                    rows.append(
                        {
                            "artist_id": artist.id,
                            "as_of_date": as_of_date,
                            "source": LASTFM_SOURCE,
                            "metric_key": metric_key,
                            "value": int(value),
                        }
                    )

            # One bulk upsert per day instead of one per artist per metric
            # -- `days * len(artists) * 2` individual round trips was the
            # dominant cost of `fake-history` at the documented 120-day,
            # 200-artist scale.
            stmt = insert(MetricSnapshot).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["artist_id", "as_of_date", "source", "metric_key"],
                set_={"value": stmt.excluded.value},
            )
            session.execute(stmt)
            session.commit()

            # A fixed hour per backfilled day, matching the real nightly
            # cron's hour (`0 7 * * *`) -- so each day's glide window is a
            # full REVERSION_GLIDE_HOURS and the next day's starts right
            # where it ends, same as production.
            recompute_now = datetime.combine(as_of_date, time(7, 0), tzinfo=UTC)
            result = run_recompute(session, as_of_date, now=recompute_now)

            # Synthetic GBM data has no real manipulation to catch -- any
            # flag `run_recompute` just raised for `as_of_date` is by
            # construction noise, since PERCENTILE_MOVE_THRESHOLD flags
            # ~1-2 artists *every* cross-section by design (PLAN.md). A
            # real deployment assumes a human clears the queue daily
            # ("a two-minute daily task"); this models that same-day
            # review for synthetic data so a 120-day backfill doesn't end
            # with most of the universe permanently quarantined. Still
            # exercises the real quarantine-hold for that one day (the
            # score stays frozen for `as_of_date` itself) -- it just stops
            # the backlog compounding across the whole run.
            newly_flagged_ids = session.scalars(
                select(FlaggedArtist.artist_id).where(
                    FlaggedArtist.as_of_date == as_of_date,
                    FlaggedArtist.cleared_at.is_(None),
                )
            ).all()
            for artist_id in newly_flagged_ids:
                clear_flag(session, artist_id, as_of_date, cleared_by="ax fake-history")
            if newly_flagged_ids:
                session.commit()

            typer.echo(
                f"{as_of_date}: eligible={result.eligible} published={result.published} "
                f"held={result.held} newly_listed={len(result.newly_listed)} "
                f"auto_cleared={len(newly_flagged_ids)}"
            )


@app.command("fake-history")
def fake_history(
    days: Annotated[int, typer.Option(help="Number of historical days to backfill")] = 120,
    seed: Annotated[int, typer.Option(help="Deterministic RNG seed")] = 42,
) -> None:
    """Backfill `days` of synthetic `metric_snapshots` (GBM walk on
    listeners, monotonic playcount) and replay the real recompute job over
    each historical date in order -- the same pipeline the nightly job
    runs, so listing, EWMA carry, quarantine checks, and reversion all
    behave exactly as they would on real data. Any same-day quarantine
    flag is auto-cleared (synthetic data has no real manipulation to
    catch), so a long backfill doesn't end with most of the universe
    permanently frozen. Deterministic under `--seed`, but only against a
    fresh universe -- refuses if `metric_snapshots` already has data; run
    `ax reset` first. Dev-only -- never run against production
    (CLAUDE.md)."""
    _require_not_production()
    _fake_history(days, seed)


def _simulate_trades(users: int, days: int, seed: int) -> None:
    with session_scope() as session:
        rng = random.Random(seed)

        # One bulk lookup for all `users` usernames instead of one SELECT
        # per user, and a single flush + commit for however many are new
        # instead of one of each per user -- `--users 50` was 50 round
        # trips of each before this.
        usernames = [f"sim_{i:04d}" for i in range(users)]
        by_username: dict[str, User] = {
            u.username: u for u in session.scalars(select(User).where(User.username.in_(usernames)))
        }
        new_users = [
            User(username=name, email=f"{name}@sim.local")
            for name in usernames
            if name not in by_username
        ]
        if new_users:
            session.add_all(new_users)
            session.flush()
            for user in new_users:
                balance = lock_balance_cache(session, user.id)
                write_entries(session, balance, user.id, grant_entries(STARTING_BALANCE_CENTS))
                by_username[user.username] = user
            session.commit()
        sim_users: list[User] = [by_username[name] for name in usernames]

        artist_slugs = list(
            session.scalars(
                select(Artist.slug).where(
                    Artist.listed_at.is_not(None), Artist.delisted_at.is_(None)
                )
            )
        )
        if not artist_slugs:
            typer.echo("No listed artists -- run `ax fake-history` first.")
            raise typer.Exit(code=1)

        # Spread over `days` calendar days ending today, same stepping
        # `_fake_history` uses -- so `ax reset`'s equity_snapshots history
        # (and therefore the Portfolio page's chart and both leaderboards)
        # has `days` real-looking points instead of being empty until
        # `days` real nights pass. Trades themselves still execute against
        # the actual current market state (`execute_trade` has no
        # backdating hook) -- only the snapshot's `as_of_date` label is
        # historical, same caveat as everything else `ax reset` fabricates.
        today = datetime.now(UTC).date()
        start = today - timedelta(days=days - 1)

        succeeded = 0
        rejected = 0
        for day_offset in range(days):
            for user in sim_users:
                slug = rng.choice(artist_slugs)
                side = TradeSide.buy if rng.random() < 0.65 else TradeSide.sell
                shares = rng.randint(1, 15)
                body = TradeRequest(artist_slug=slug, side=side, shares=shares)
                try:
                    # The real trade route function, called directly
                    # instead of through HTTP -- same locking, validation,
                    # ledger writes, and price_history append production
                    # uses (PLAN.md: "through the real AMM and real ledger
                    # path"). FastAPI's `Annotated[..., Depends(...)]`
                    # parameter types are only resolved by the ASGI
                    # dependency-injection layer; called as a plain
                    # function they're irrelevant, so passing concrete
                    # `session`/`user` objects here is safe.
                    execute_trade(body, session, user)
                    succeeded += 1
                except HTTPException:
                    # Expected: overdraft, exposure cap, slippage cap,
                    # oversell -- a random agent is supposed to hit these
                    # sometimes. `execute_trade` already rolled back
                    # before raising.
                    rejected += 1

            # A fixed hour per simulated day, same reasoning as
            # `_fake_history`'s `recompute_now`: `compute_portfolio_snapshot`
            # marks positions to spot via the `now`-dependent reversion
            # glide, so passing the real wall-clock time here would mark
            # every one of the `days` fabricated snapshots to the same
            # glide state instead of a price appropriate to that day.
            as_of_date = start + timedelta(days=day_offset)
            snapshot_now = datetime.combine(as_of_date, time(7, 0), tzinfo=UTC)
            run_leaderboard_snapshot(session, as_of_date, now=snapshot_now)

        typer.echo(f"trades: {succeeded} succeeded, {rejected} rejected by guardrails (expected)")


@app.command("simulate-trades")
def simulate_trades(
    users: Annotated[int, typer.Option(help="Number of simulated users")] = 50,
    days: Annotated[int, typer.Option(help="Number of trading rounds")] = 120,
    seed: Annotated[int, typer.Option(help="Deterministic RNG seed")] = 42,
) -> None:
    """Random agents trading through the real AMM and real ledger path
    (`api.routers.trades.execute_trade`, called directly -- no HTTP),
    producing realistic price history and non-empty portfolios. Requires
    listed artists -- run `ax fake-history` first. Dev-only (CLAUDE.md)."""
    _require_not_production()
    _simulate_trades(users, days, seed)


@app.command("reset")
def reset(
    users: Annotated[int, typer.Option(help="Simulated users for simulate-trades")] = 50,
    days: Annotated[int, typer.Option(help="Days for fake-history / simulate-trades rounds")] = 120,
    seed: Annotated[int, typer.Option(help="Deterministic RNG seed")] = 42,
    seed_path: Annotated[Path, typer.Option(help="Seed JSON to load")] = DEFAULT_SEED_PATH,
) -> None:
    """Drop, migrate, seed, fake-history, and simulate-trades in one
    command -- a fully reproducible local dev DB from nothing. Refuses to
    run with `ENVIRONMENT=production` (CLAUDE.md: fake data must never
    reach production); there is no confirmation prompt beyond that, so
    only ever point this at a local or disposable database."""
    _require_not_production()

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    typer.echo("schema dropped and recreated")

    subprocess.run(["alembic", "upgrade", "head"], cwd=REPO_ROOT, check=True)
    typer.echo("migrations applied")

    total = _seed_artists(seed_path)
    typer.echo(f"seeded {total} artists")

    _fake_history(days, seed)
    _simulate_trades(users, days, seed)
    typer.echo("reset complete")


def _load_metrics_csv(path: Path) -> _MetricSeries:
    """Long-format rows (`artist_slug, as_of_date, source, metric_key,
    value`) grouped by artist and signal key."""
    series: _MetricSeries = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            slug = row["artist_slug"]
            signal_key = f"{row['source']}.{row['metric_key']}"
            as_of = date.fromisoformat(row["as_of_date"])
            series.setdefault(slug, {}).setdefault(signal_key, {})[as_of] = int(row["value"])
    return series


def _replay_metrics(series: _MetricSeries) -> dict[date, dict[str, ArtistDayResult]]:
    """Replay every date in `series` through `compute_index` in order,
    carrying each artist's EWMA state from one day's `components` into
    the next day's `prev_ewma` -- the same warm-up/base-window rules
    Phase 3's nightly job will apply against real `metric_snapshots`."""
    all_dates = sorted(
        {d for metrics in series.values() for dates in metrics.values() for d in dates}
    )
    prev_ewma: dict[str, dict[str, float]] = {}
    results_by_date: dict[date, dict[str, ArtistDayResult]] = {}

    for as_of in all_dates:
        day_input: dict[str, ArtistDayInput] = {}
        for slug, metrics in series.items():
            signals: dict[str, SignalInput] = {}
            for signal_key, dates_to_values in metrics.items():
                if as_of not in dates_to_values:
                    break
                base = pick_base_snapshot(dates_to_values, as_of)
                if base is None:
                    break
                base_value, gap_days = base
                signals[signal_key] = SignalInput(
                    current=dates_to_values[as_of],
                    base=base_value,
                    gap_days=gap_days,
                    prev_ewma=prev_ewma.get(slug, {}).get(signal_key),
                )
            else:
                day_input[slug] = ArtistDayInput(
                    signals=signals, listeners=metrics["lastfm.listeners"][as_of]
                )

        day_results = compute_index(day_input)
        results_by_date[as_of] = day_results

        for slug, result in day_results.items():
            signals_component = result.components["signals"]
            assert isinstance(signals_component, dict)
            for signal_key, info in signals_component.items():
                assert isinstance(info, dict)
                prev_ewma.setdefault(slug, {})[signal_key] = info["ewma"]

    return results_by_date


@app.command("backtest")
def backtest(
    csv_path: Annotated[
        Path, typer.Option("--csv", help="Long-format metrics CSV to replay")
    ] = DEFAULT_BACKTEST_CSV,
    artist: Annotated[
        str | None,
        typer.Option("--artist", help="Filter output to one artist slug's full series"),
    ] = None,
) -> None:
    """Replay a long-format metrics CSV through the real index pipeline.

    The same `compute_index` pipeline Phase 3's nightly job will run
    against real `metric_snapshots`, carrying EWMA state from one day to
    the next exactly like production would -- this is `core/` exercised
    end to end against a CSV instead of the database. Reads no database,
    no network; imports only `ax.core`, stdlib `csv`, and `typer`.

    Prints one `date,slug,index_score,fair_value_cents` row per
    artist-day, followed by the top 5 score risers and fallers across
    the run -- turning PLAN.md's "eyeball the series" verification step
    into something to actually look at.
    """
    series = _load_metrics_csv(csv_path)
    results_by_date = _replay_metrics(series)

    first_score: dict[str, float] = {}
    last_score: dict[str, float] = {}

    for as_of in sorted(results_by_date):
        for slug, result in sorted(results_by_date[as_of].items()):
            if artist is not None and slug != artist:
                continue
            typer.echo(
                f"{as_of.isoformat()},{slug},{result.index_score:.4f},{result.fair_value_cents}"
            )
            first_score.setdefault(slug, result.index_score)
            last_score[slug] = result.index_score

    if artist is not None:
        return

    deltas = sorted(
        ((slug, last_score[slug] - first_score[slug]) for slug in last_score),
        key=lambda pair: pair[1],
    )
    typer.echo("")
    typer.echo("Top 5 risers:")
    for slug, delta in reversed(deltas[-5:]):
        typer.echo(f"  {slug}: {delta:+.2f}")
    typer.echo("Top 5 fallers:")
    for slug, delta in deltas[:5]:
        typer.echo(f"  {slug}: {delta:+.2f}")


if __name__ == "__main__":
    app()
