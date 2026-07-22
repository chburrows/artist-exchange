"""Pure session/magic-link math: keyed token hashing and TTL expiry.

Token *generation* (`secrets.token_urlsafe`) deliberately does not live
here -- it pulls from OS entropy, which is exactly the kind of hidden
nondeterminism `core/` exists to keep out (CLAUDE.md rule 3, "time is
always a parameter" generalizes to "randomness is always injected").
Generation lives at the API layer; this module only hashes what it's
given and computes expiry from an explicit `now`.

Hashing is HMAC-SHA256 keyed on `SESSION_SECRET`, not a bare SHA256. A
raw hash of a high-entropy token is already infeasible to reverse, but
keying it means a leaked `token_hash` column alone (e.g. a DB dump
without the app's environment) is still useless -- the attacker also
needs the server secret to produce a token that hashes to any given row.
"""

import hashlib
import hmac
from datetime import datetime, timedelta

from ax.core.config import MAGIC_LINK_TTL_MINUTES, PENDING_SIGNUP_TTL_MINUTES, SESSION_TTL_DAYS


def hash_token(secret: bytes, raw_token: str) -> bytes:
    return hmac.new(secret, raw_token.encode("utf-8"), hashlib.sha256).digest()


def session_expiry(now: datetime) -> datetime:
    return now + timedelta(days=SESSION_TTL_DAYS)


def magic_link_expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)


def pending_signup_expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=PENDING_SIGNUP_TTL_MINUTES)
