"""`ax.core.auth` -- keyed token hashing and TTL expiry. No invariant
series here (nothing to converge or clamp); these are direct checks that
the hash is actually keyed and that expiry is computed from the
injected `now`, not wall-clock time.
"""

from datetime import UTC, datetime, timedelta

from ax.core.auth import hash_token, magic_link_expiry, session_expiry
from ax.core.config import MAGIC_LINK_TTL_MINUTES, SESSION_TTL_DAYS


def test_hash_token_is_deterministic() -> None:
    assert hash_token(b"secret", "token") == hash_token(b"secret", "token")


def test_hash_token_depends_on_the_key() -> None:
    assert hash_token(b"secret-a", "token") != hash_token(b"secret-b", "token")


def test_hash_token_depends_on_the_token() -> None:
    assert hash_token(b"secret", "token-a") != hash_token(b"secret", "token-b")


def test_hash_token_is_32_bytes() -> None:
    # SHA-256 digest size -- a fixed-width column (`token_hash bytea`)
    # depends on this not changing silently.
    assert len(hash_token(b"secret", "token")) == 32


def test_session_expiry_uses_the_configured_ttl() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert session_expiry(now) == now + timedelta(days=SESSION_TTL_DAYS)


def test_magic_link_expiry_uses_the_configured_ttl() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert magic_link_expiry(now) == now + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
