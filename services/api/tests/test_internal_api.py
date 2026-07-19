"""The protected job endpoint, end to end through the real app.

This endpoint is reachable from the public internet and its only
protection is a bearer token, so the auth tests here are load-bearing
rather than box-ticking.
"""

from datetime import UTC, datetime

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


def test_as_of_override_is_honored(
    client: TestClient,
    session: Session,
    make_artist: ArtistFactory,
    auth_headers: dict[str, str],
) -> None:
    """Backfills and re-running a failed night both depend on this."""
    make_artist("Wednesday")

    response = client.post(
        "/internal/jobs/snapshot", params={"as_of": "2026-01-15"}, headers=auth_headers
    )

    assert response.json()["as_of_date"] == "2026-01-15"
    stored = session.scalars(select(MetricSnapshot)).first()
    assert stored is not None
    assert stored.as_of_date.isoformat() == "2026-01-15"


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

    client.post("/internal/jobs/snapshot", params={"as_of": "2026-07-18"}, headers=auth_headers)
    first = total_rows(session)
    client.post("/internal/jobs/snapshot", params={"as_of": "2026-07-18"}, headers=auth_headers)

    assert total_rows(session) == first


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
