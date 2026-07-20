"""`ax` — local development and operations CLI.

Phase 1 shipped `seed-artists` and `snapshot`; Phase 2 added `backtest`;
Phase 3 added `recompute`; Phase 4 adds `reconcile`. The remaining
commands CLAUDE.md documents (`fake-history`, `simulate-trades`, `reset`)
arrive with the phases that give them something to do — a stub that
prints "not implemented" is worse than an honest absence, because it
looks like a working command in `--help`.
"""

import csv
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ax.core.index import (
    ArtistDayInput,
    ArtistDayResult,
    SignalInput,
    compute_index,
    pick_base_snapshot,
)
from ax.db.models import Artist, MetricSnapshot
from ax.db.session import session_scope
from ax.jobs.recompute import run_recompute
from ax.jobs.reconcile import run_reconcile
from ax.jobs.snapshot import run_snapshot
from ax.logging_config import configure_third_party_logging
from ax.providers.lastfm import LastfmProvider
from ax.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)

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

    typer.echo(f"Seeded {len(records)} artists from {path.name}; {total} total in universe.")


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
