"""`ax` — local development and operations CLI.

Phase 1 ships `seed-artists` and `snapshot`. The rest of the commands
CLAUDE.md documents (`fake-history`, `simulate-trades`, `reset`,
`backtest`) arrive with the phases that give them something to do — a stub
that prints "not implemented" is worse than an honest absence, because it
looks like a working command in `--help`.
"""

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ax.db.models import Artist, MetricSnapshot
from ax.db.session import session_scope
from ax.jobs.snapshot import run_snapshot
from ax.logging_config import configure_third_party_logging
from ax.providers.lastfm import LastfmProvider
from ax.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)

DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "artists_seed.json"


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


if __name__ == "__main__":
    app()
