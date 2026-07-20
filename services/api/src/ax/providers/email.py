"""The transactional-email provider seam — magic links only, in v1.

Mirrors `providers/base.py`'s shape (a `Protocol` plus a concrete
implementation behind a FastAPI dependency), so auth routes and their
tests substitute a fake and exercise the real signup/attach/recovery flow
without a network call or spending Resend's quota.

Only two failure modes matter here, unlike the metric provider's richer
taxonomy: auth is fatal (fix the key), everything else is "this one send
failed" (tell the user to retry — a magic link is re-requestable, there
is nothing to retry automatically on their behalf mid-request).
"""

from dataclasses import dataclass
from typing import Protocol

import httpx


class EmailError(Exception):
    """Base for anything an email provider can fail with."""


class EmailAuthError(EmailError):
    """Bad or missing credentials. Fatal — same 503 treatment as
    `ProviderAuthError` in `api/deps.py`: the service is misconfigured,
    not broken."""


class EmailSendError(EmailError):
    """The provider was reachable but did not send this message (bad
    address, provider-side rejection, transient failure). Recoverable —
    the caller tells the user to try again, rather than crashing the
    request."""


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    html: str


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None:
        """Raises `EmailAuthError` or `EmailSendError`."""
        ...


RESEND_API_ROOT = "https://api.resend.com/emails"


class ResendEmailProvider:
    """Thin client for Resend's `POST /emails`. No SDK dependency — one
    endpoint, one shape, not worth a library."""

    def __init__(
        self,
        api_key: str,
        from_address: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        if not api_key:
            raise EmailAuthError("RESEND_API_KEY is not set")
        self._api_key = api_key
        self._from_address = from_address
        self._client = client or httpx.Client(timeout=timeout_s)

    def __enter__(self) -> "ResendEmailProvider":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def send(self, message: EmailMessage) -> None:
        try:
            response = self._client.post(
                RESEND_API_ROOT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from_address,
                    "to": [message.to],
                    "subject": message.subject,
                    "html": message.html,
                },
            )
        except httpx.HTTPError as exc:
            raise EmailSendError(f"request to Resend failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise EmailAuthError(f"Resend rejected the API key (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise EmailSendError(f"Resend returned HTTP {response.status_code}: {response.text}")
