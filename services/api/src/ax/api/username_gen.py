"""Default-username generation for signup.

Deliberately not in `ax.core`: it pulls from OS entropy (`secrets`),
exactly the hidden nondeterminism `core/` exists to keep out (CLAUDE.md
rule 3 -- the same reason token generation lives at the API layer in
`api/routers/auth.py` rather than in `ax.core.auth`).

`apps/web`'s `OnboardingScreen` runs an independent, client-side version
of the same adjective+noun+2-digit-suffix shape so the input is prefilled
before a network round trip -- the two are not shared code (different
languages), just a matched approach. This module is the one that actually
matters for correctness: it's what `POST /auth/signup/consume` falls back
to when a request omitted `username` entirely (PLAN.md Phase 7), so the
API contract never depends on a JS client always supplying a value.
"""

import secrets

ADJECTIVES = (
    "quiet",
    "brave",
    "lucky",
    "electric",
    "velvet",
    "neon",
    "golden",
    "midnight",
    "crimson",
    "silver",
    "amber",
    "restless",
    "solar",
    "hollow",
    "vivid",
    "gilded",
    "wild",
    "faded",
    "arctic",
    "feral",
)

NOUNS = (
    "scout",
    "comet",
    "otter",
    "falcon",
    "harbor",
    "ember",
    "meadow",
    "cipher",
    "atlas",
    "raven",
    "compass",
    "current",
    "signal",
    "orbit",
    "canyon",
    "lantern",
    "echo",
    "tide",
    "prism",
    "drift",
)


def random_username() -> str:
    """`adjective + noun + 2-digit suffix` -- always matches the same
    `^[A-Za-z0-9_-]{3,24}$` pattern real usernames are validated against
    (longest case: `restless` + `compass` + 2 digits = 17 chars), so a
    caller never has to re-validate a generated candidate before trying
    to insert it."""
    adjective = secrets.choice(ADJECTIVES)
    noun = secrets.choice(NOUNS)
    suffix = secrets.randbelow(100)
    return f"{adjective}{noun}{suffix:02d}"
