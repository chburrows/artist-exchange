"""The protected job endpoint, end to end through the real app.

This endpoint is reachable from the public internet and its only
protection is a bearer token, so the auth tests here are load-bearing
rather than box-ticking.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ax.api.deps import require_job_token
from ax.db.models import MetricSnapshot
from ax.providers.base import ProviderAuthError
from ax.settings import Settings
from tests.conftest import ArtistFactory, FakeProvider


def total_rows(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(MetricSnapshot)) or 0


def test_health_needs_no_auth(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_snapshot_requires_a_token(client: TestClient, make_artist: ArtistFactory) -> None:
    make_artist("Wednesday")

    response = client.post("/internal/jobs/snapshot")

    assert response.status_code == 401


def test_snapshot_rejects_a_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/internal/jobs/snapshot", headers={"Authorization": "Bearer not-the-token"}
    )

    assert response.status_code == 401


def test_snapshot_rejects_a_non_bearer_scheme(client: TestClient) -> None:
    response = client.post(
        "/internal/jobs/snapshot", headers={"Authorization": "Basic test-job-token"}
    )

    assert response.status_code == 401


def test_rejected_request_writes_nothing(
    client: TestClient, session: Session, make_artist: ArtistFactory
) -> None:
    """The guard must run before the job, not alongside it."""
    make_artist("Wednesday")

    client.post("/internal/jobs/snapshot", headers={"Authorization": "Bearer wrong"})

    assert total_rows(session) == 0


def test_snapshot_succeeds_with_a_valid_token(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    make_artist("Wednesday")

    response = client.post("/internal/jobs/snapshot", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 1
    assert body["rows_upserted"] == 2
    assert total_rows(session) == 2


def values_on(session: Session, as_of: str) -> list[int]:
    stmt = select(MetricSnapshot.value).where(
        MetricSnapshot.as_of_date == date.fromisoformat(as_of)
    )
    return list(session.scalars(stmt))


def test_defaults_to_today_utc(
    client: TestClient, make_artist: ArtistFactory, auth_headers: dict[str, str]
) -> None:
    make_artist("Wednesday")

    response = client.post("/internal/jobs/snapshot", headers=auth_headers)

    assert response.json()["as_of_date"] == datetime.now(UTC).date().isoformat()


def test_endpoint_is_idempotent(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    """I12 through the HTTP layer — the path a retried Action actually
    takes."""
    make_artist("Wednesday")

    client.post("/internal/jobs/snapshot", headers=auth_headers)
    # Keyed on the response's date, not a second clock read, so a run that
    # straddles UTC midnight cannot flake this.
    as_of = client.post("/internal/jobs/snapshot", headers=auth_headers).json()["as_of_date"]

    assert len(values_on(session, as_of)) == 2


def test_todays_rerun_corrects_a_stale_value(
    client: TestClient,
    session: Session,
    provider: FakeProvider,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    """The retried nightly run re-snapshots today and relies on DO UPDATE to
    fix a partial first attempt. The as_of guard must not break that."""
    make_artist("Wednesday")
    provider.metrics["Wednesday"] = {"listeners": 100}
    client.post("/internal/jobs/snapshot", headers=auth_headers)

    provider.metrics["Wednesday"] = {"listeners": 250}
    as_of = client.post("/internal/jobs/snapshot", headers=auth_headers).json()["as_of_date"]

    assert values_on(session, as_of) == [250]


@pytest.mark.parametrize("as_of", ["2026-01-15", "2999-01-01"], ids=["past", "future"])
def test_as_of_other_than_today_is_rejected(
    client: TestClient,
    session: Session,
    provider: FakeProvider,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
    as_of: str,
) -> None:
    """The stolen-token path. Last.fm reports only current counts, so any
    other date would plant today's numbers in the series — overwriting real
    history, or filling a gap the growth window then reads as the past."""
    make_artist("Wednesday")

    response = client.post("/internal/jobs/snapshot", params={"as_of": as_of}, headers=auth_headers)

    assert response.status_code == 422
    assert total_rows(session) == 0
    assert provider.calls == []


def test_aborted_run_returns_non_2xx(
    client: TestClient,
    provider: FakeProvider,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    """`curl -f` in the Action must fail. A run that aborted on bad
    credentials must not look green in the Actions log."""
    make_artist("Wednesday")
    provider.raises["Wednesday"] = ProviderAuthError("Invalid API key")

    response = client.post("/internal/jobs/snapshot", headers=auth_headers)

    assert response.status_code == 502


def test_internal_routes_are_absent_from_the_openapi_schema(client: TestClient) -> None:
    """apps/web/lib/api.ts is generated from this schema. The job endpoints
    must not leak into the public client."""
    schema = client.get("/openapi.json").json()

    assert not any(path.startswith("/internal") for path in schema["paths"])


def test_non_ascii_token_is_rejected_not_a_crash(test_settings: Settings) -> None:
    """`secrets.compare_digest` raises TypeError on non-ASCII strings, and
    Starlette decodes headers as latin-1 — so a single high byte in the
    Authorization header turned a 401 into an unhandled 500 on a public
    endpoint.

    Exercised against the dependency directly because httpx refuses to
    *send* a non-ASCII header, while a raw socket sends one happily. The
    guard has to survive input the test client cannot produce.
    """
    with pytest.raises(HTTPException) as caught:
        require_job_token(test_settings, authorization="Bearer \xf1")

    assert caught.value.status_code == 401
