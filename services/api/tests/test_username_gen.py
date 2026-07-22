"""`random_username()` is the server-side generator `POST
/auth/signup/consume` actually depends on for correctness; `apps/web/src/
lib/username.ts` is a client-side, not-shared-code, "matched approach"
copy that only exists to prefill the signup form (see both modules'
docstrings). Nothing enforces the two staying in sync except this test --
without it, an edit to one word list silently drifts from the other.
"""

import re
from pathlib import Path

from ax.api.username_gen import ADJECTIVES, NOUNS, random_username

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_USERNAME_TS = _REPO_ROOT / "apps/web/src/lib/username.ts"


def _extract_word_list(source: str, name: str) -> tuple[str, ...]:
    match = re.search(rf"const {name} = \[(.*?)\];", source, re.DOTALL)
    assert match, f"couldn't find `const {name} = [...]` in {_FRONTEND_USERNAME_TS}"
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def test_random_username_matches_the_pattern_real_usernames_are_validated_against() -> None:
    for _ in range(200):
        assert re.fullmatch(r"[A-Za-z0-9_-]{3,24}", random_username())


def test_frontend_word_lists_match_the_backend_generator() -> None:
    source = _FRONTEND_USERNAME_TS.read_text()
    assert _extract_word_list(source, "ADJECTIVES") == ADJECTIVES
    assert _extract_word_list(source, "NOUNS") == NOUNS
