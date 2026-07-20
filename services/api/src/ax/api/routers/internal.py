"""Protected job endpoints, driven by GitHub Actions cron.

Jobs live behind HTTP rather than in a worker process because the schedule
is one run a night: an always-on worker would be a second deployable to
operate, monitor, and pay for, in exchange for nothing. GitHub Actions
already has cron, retries, `workflow_dispatch`, and a failure-notification
path.

Safe to call by hand at any time — the underlying job is idempotent on
`(artist_id, as_of_date)`.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ax.api.deps import MetricProviderDep, require_job_token
from ax.db.session import get_db
from ax.jobs.recompute import run_recompute
from ax.jobs.reconcile import run_reconcile
from ax.jobs.snapshot import run_snapshot

router = APIRouter(
    prefix="/internal/jobs",
    tags=["internal"],
    dependencies=[Depends(require_job_token)],
    # These endpoints are operational, not part of the product API. Keeping
    # them out of the schema keeps them out of the generated TypeScript
    # client in apps/web, which should have no idea they exist.
    include_in_schema=False,
)

DbDep = Annotated[Session, Depends(get_db)]


@router.post("/snapshot", status_code=status.HTTP_200_OK)
def snapshot(
    session: DbDep,
    provider: MetricProviderDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Fetch and store today's metrics for every active artist.

    `as_of` is an explicit override for backfills and for re-running a
    night that failed. It defaults to the current UTC date — computed
    here, at the I/O boundary, and passed down, so the job itself stays
    time-injectable and testable.
    """
    as_of_date = as_of or datetime.now(UTC).date()
    result = run_snapshot(session, provider, as_of_date)

    if not result.ok:
        # A non-2xx makes `curl -f` in the Action fail loudly. A run that
        # aborted on bad credentials must not look like a success in the
        # Actions log.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.summary(),
        )

    return result.summary()


@router.post("/recompute", status_code=status.HTTP_200_OK)
def recompute(
    session: DbDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Recompute the index, apply the oracle-manipulation quarantine
    checks, list newly-eligible artists, and run the nightly reversion.

    Meant to run immediately after `/snapshot` in the same nightly
    Action, against the date that step just wrote. `as_of` is the same
    backfill/re-run override `/snapshot` takes; `now` (the glide/listing
    clock) is always the real current time -- unlike `as_of_date`, there
    is no legitimate reason to backdate it.
    """
    as_of_date = as_of or datetime.now(UTC).date()
    result = run_recompute(session, as_of_date, now=datetime.now(UTC))
    return result.summary()


@router.post("/reconcile", status_code=status.HTTP_200_OK)
def reconcile(session: DbDep) -> dict[str, Any]:
    """Rebuild `balance_cache`/`position_cache` from `transactions` for
    every user and overwrite any row that has drifted. Meant to run last
    in the nightly Action, after `snapshot` and `recompute` -- there is
    no `as_of_date` here because reconciliation isn't about one day's
    data, it checks the whole ledger against the whole cache, as of now.
    """
    result = run_reconcile(session, now=datetime.now(UTC))
    return result.summary()
