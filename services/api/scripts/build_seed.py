"""One-off generator for `data/artists_seed.json`.

Run by hand, not by the app, and not in CI. Its output is committed, so
the seed is a reviewable artifact rather than something that silently
changes shape every time someone runs it.

The universe is built *from the Last.fm API* rather than from a list typed
out by hand, for one reason: every entry is then guaranteed to resolve.
A hand-written name that Last.fm spells differently ("Tyler, The Creator"
vs "Tyler, the Creator") becomes an artist that silently collects zero
snapshots forever, and a gap in a series cannot be backfilled because
Last.fm exposes no history.

Two tiers, by listener count:

  blue_chip — pulled from the global chart. Liquid, familiar, slow-moving.
              These anchor the market and give new users something they
              recognize on the first screen.
  growth    — pulled from genre tags skewed toward current and emerging
              scenes, then filtered to a listener band. This is where the
              talent-scout game actually happens.

The growth band's lower bound is not cosmetic. Below roughly 20k listeners
the weekly listener delta is small enough that ordinary noise dominates
the growth signal, so the index would be measuring randomness and the
"scouting" would be a coin flip.

Selection is interactive by default: the script resolves a candidate pool
well past each tier's target, then asks yes/no/quit for every candidate in
descending listener order, so rejecting freely never risks running out of
replacements. Pass --auto to skip the prompts and take the pool in order
(useful for a quick smoke run) or --blue-chip-target / --growth-target to
change how many approvals each tier stops at.

Usage:
    set -a && . ./secrets.env && set +a
    uv run python services/api/scripts/build_seed.py
    uv run python services/api/scripts/build_seed.py --auto
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "artists_seed.json"

MIN_INTERVAL_S = 0.25

BLUE_CHIP_TARGET = 70
GROWTH_TARGET = 130

# Pools are fetched well past target so rejecting candidates during
# interactive review never runs the tier dry.
BLUE_CHIP_POOL = 150
GROWTH_POOL = 350

# Chart pages to pull while filling the blue chip pool, at 200/page. Capped
# so a stubborn pool size can't turn into an unbounded crawl.
MAX_CHART_PAGES = 10

# Chart artists at or above this are unambiguously household names.
BLUE_CHIP_MIN_LISTENERS = 1_500_000

# Below the floor, weekly deltas are mostly noise. Above the ceiling, an
# artist is too established to plausibly "break out", which is the whole
# premise of the growth tier.
GROWTH_MIN_LISTENERS = 20_000
GROWTH_MAX_LISTENERS = 900_000

# Tags chosen to spread the growth tier across scenes and geographies
# rather than concentrating it in one sound. Last.fm skews Western,
# older, and indie/rock (see CLAUDE.md gotchas), so the non-Western and
# internet-native tags here are partly an attempt to counterweight that
# bias in the one place we control it: which artists exist at all.
GROWTH_TAGS = [
    "hyperpop",
    "bedroom pop",
    "shoegaze",
    "midwest emo",
    "afrobeats",
    "amapiano",
    "k-pop",
    "j-pop",
    "uk drill",
    "jersey club",
    "phonk",
    "breakcore",
    "indie pop",
    "dream pop",
    "post-punk",
    "neo-soul",
    "alternative r&b",
    "reggaeton",
    "latin trap",
    "grime",
    "jungle",
    "ambient",
    "slowcore",
    "art pop",
    "trip-hop",
]

_last_request_at: float | None = None


def throttle() -> None:
    global _last_request_at
    if _last_request_at is not None:
        remaining = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
    _last_request_at = time.monotonic()


def call(client: httpx.Client, method: str, **params: str | int) -> dict[str, Any]:
    throttle()
    response = client.get(
        API_ROOT,
        params={
            "method": method,
            "api_key": API_KEY,
            "format": "json",
            "autocorrect": "0",
            **params,
        },
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if "error" in payload:
        raise RuntimeError(f"Last.fm error {payload['error']}: {payload.get('message')}")
    return payload


def slugify(name: str) -> str:
    """URL-safe, ASCII-only slug.

    Decomposes accents rather than dropping the character, so "Björk"
    becomes "bjork" instead of "bj-rk".

    Names written entirely in a non-Latin script — CJK, Cyrillic, Hangul —
    reduce to the empty string, which would collide with every other such
    name and violate the unique constraint on `artists.slug`. Those fall
    back to a stable hash of the name: not readable, but unique,
    deterministic across regenerations, and URL-safe.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not slug:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        return f"artist-{digest}"
    return slug


def tag_artists(client: httpx.Client, tag: str, limit: int = 40) -> list[dict[str, Any]]:
    try:
        payload = call(client, "tag.gettopartists", tag=tag, limit=limit)
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        print(f"  tag {tag!r} failed: {exc}", file=sys.stderr)
        return []
    artists: list[dict[str, Any]] = payload.get("topartists", {}).get("artist", [])
    return artists


def artist_listeners(client: httpx.Client, name: str, mbid: str | None) -> dict[str, Any] | None:
    """Resolve one artist to canonical name + mbid + listener count."""
    params: dict[str, str] = {"mbid": mbid} if mbid else {"artist": name}
    try:
        payload = call(client, "artist.getinfo", **params)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"  getinfo {name!r} failed: {exc}", file=sys.stderr)
        return None
    artist = payload.get("artist")
    if not isinstance(artist, dict):
        return None
    stats = artist.get("stats", {})
    try:
        listeners = int(str(stats.get("listeners", "")).replace(",", ""))
    except ValueError:
        return None
    return {
        "name": artist.get("name", name),
        "mbid": artist.get("mbid") or None,
        "listeners": listeners,
    }


def build_blue_chip_pool(client: httpx.Client, pool_size: int) -> tuple[list[dict[str, Any]], set[str]]:
    """Pull chart pages until `pool_size` candidates clear the listener floor.

    Returns the pool sorted by listeners descending, plus the set of
    casefolded names seen, so the growth pass below doesn't re-propose the
    same artist under a genre tag.
    """
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    while len(pool) < pool_size and page <= MAX_CHART_PAGES:
        payload = call(client, "chart.gettopartists", limit=200, page=page)
        entries = payload["artists"]["artist"]
        if not entries:
            break
        for entry in entries:
            name = entry.get("name", "").strip()
            if not name or name.casefold() in seen:
                continue
            try:
                listeners = int(str(entry.get("listeners", "")).replace(",", ""))
            except ValueError:
                continue
            if listeners < BLUE_CHIP_MIN_LISTENERS:
                continue
            seen.add(name.casefold())
            pool.append(
                {
                    "slug": slugify(name),
                    "name": name,
                    "lastfm_name": name,
                    "lastfm_mbid": entry.get("mbid") or None,
                    "tier": "blue_chip",
                    "listeners_at_seed": listeners,
                }
            )
            if len(pool) >= pool_size:
                break
        print(f"  chart page {page}: {len(pool)} pool so far", file=sys.stderr)
        page += 1
    return pool, seen


def build_growth_pool(
    client: httpx.Client, seen_names: set[str], pool_size: int
) -> list[dict[str, Any]]:
    print("Fetching genre tags (growth candidates)...", file=sys.stderr)
    per_tag: list[list[tuple[str, str | None, str]]] = []
    for tag in GROWTH_TAGS:
        entries = tag_artists(client, tag)
        bucket: list[tuple[str, str | None, str]] = []
        for entry in entries:
            name = entry.get("name", "").strip()
            if name and name.casefold() not in seen_names:
                seen_names.add(name.casefold())
                bucket.append((name, entry.get("mbid") or None, tag))
        print(f"  tag {tag!r}: {len(bucket)} new candidates", file=sys.stderr)
        per_tag.append(bucket)

    # Round-robin across tags rather than concatenating them. Concatenating
    # looks equivalent but is not: resolution stops as soon as the pool is
    # full, so the first few tags fill the entire tier and every scene
    # after them contributes nothing. The first run of this script produced
    # a "growth tier" that was shoegaze, hyperpop and midwest emo, with
    # zero reggaeton, k-pop, grime or jungle.
    candidates: list[tuple[str, str | None, str]] = []
    for rank in range(max((len(bucket) for bucket in per_tag), default=0)):
        for bucket in per_tag:
            if rank < len(bucket):
                candidates.append(bucket[rank])

    print(
        f"Resolving up to {pool_size} candidates for listener counts "
        f"(of {len(candidates)} available)...",
        file=sys.stderr,
    )
    pool: list[dict[str, Any]] = []
    for index, (name, mbid, tag) in enumerate(candidates, start=1):
        if len(pool) >= pool_size:
            break
        if index % 25 == 0:
            print(f"  {index}/{len(candidates)} resolved, {len(pool)} kept", file=sys.stderr)
        info = artist_listeners(client, name, mbid)
        if info is None:
            continue
        if not (GROWTH_MIN_LISTENERS <= info["listeners"] <= GROWTH_MAX_LISTENERS):
            continue
        pool.append(
            {
                "slug": slugify(info["name"]),
                "name": info["name"],
                "lastfm_name": info["name"],
                "lastfm_mbid": info["mbid"],
                "tier": "growth",
                "listeners_at_seed": info["listeners"],
                "tag": tag,  # display-only; stripped before writing the seed
            }
        )
    return pool


def review_candidates(
    candidates: list[dict[str, Any]], target: int, label: str
) -> list[dict[str, Any]]:
    """Walk the pool in order, asking yes/no/quit for each candidate.

    Enter (or "y") keeps it, "n" rejects it, "q" stops reviewing this tier
    early — whatever's been approved so far is kept. Stopping only when
    `target` approvals are reached (rather than when the pool runs out)
    means rejecting freely never leaves a tier short, as long as the pool
    was sized generously enough.
    """
    approved: list[dict[str, Any]] = []
    total = len(candidates)
    print(f"\nReviewing {total} {label} candidates, aiming to keep {target}.", file=sys.stderr)
    print("Enter/y = keep, n = reject, q = stop reviewing this tier.\n", file=sys.stderr)

    for i, candidate in enumerate(candidates, start=1):
        if len(approved) >= target:
            print(f"  reached target of {target}, stopping {label} review.", file=sys.stderr)
            break

        tag_suffix = f"  [{candidate['tag']}]" if "tag" in candidate else ""
        prompt = (
            f"[{i}/{total}] kept {len(approved)}/{target} - "
            f"{candidate['name']} ({candidate['listeners_at_seed']:,} listeners)"
            f"{tag_suffix} — keep? [Y/n/q] "
        )
        quit_early = False
        while True:
            try:
                response = input(prompt).strip().lower()
            except EOFError:
                response = "q"
            if response in ("", "y", "yes"):
                approved.append(candidate)
                break
            if response in ("n", "no"):
                break
            if response in ("q", "quit"):
                quit_early = True
                break
            print("  please answer y, n, or q", file=sys.stderr)

        if quit_early:
            print(f"  stopped early with {len(approved)}/{target} kept.", file=sys.stderr)
            break

    return approved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="skip interactive review; take each pool in order up to its target",
    )
    parser.add_argument("--blue-chip-target", type=int, default=BLUE_CHIP_TARGET)
    parser.add_argument("--growth-target", type=int, default=GROWTH_TARGET)
    parser.add_argument("--blue-chip-pool", type=int, default=BLUE_CHIP_POOL)
    parser.add_argument("--growth-pool", type=int, default=GROWTH_POOL)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = httpx.Client(timeout=20.0, headers={"User-Agent": "artist-exchange-seed/0.1"})

    print("Fetching global chart (blue chip candidates)...", file=sys.stderr)
    blue_chip_pool, seen_names = build_blue_chip_pool(client, args.blue_chip_pool)
    print(f"  -> {len(blue_chip_pool)} blue chip candidates in pool", file=sys.stderr)

    growth_pool = build_growth_pool(client, seen_names, args.growth_pool)
    print(f"  -> {len(growth_pool)} growth candidates in pool", file=sys.stderr)

    if args.auto:
        blue_chip = blue_chip_pool[: args.blue_chip_target]
        growth = growth_pool[: args.growth_target]
    else:
        blue_chip = review_candidates(blue_chip_pool, args.blue_chip_target, "blue chip")
        growth = review_candidates(growth_pool, args.growth_target, "growth")

    for artist in growth:
        artist.pop("tag", None)

    universe = blue_chip + growth

    # Distinct artists can still collide after transliteration ("Björk" and
    # "Bjork" both slugify to "bjork"). Disambiguate deterministically
    # rather than failing: the collision is legitimate and a human cannot
    # do anything more useful about it than this.
    taken: set[str] = set()
    for artist in universe:
        slug = artist["slug"]
        if slug in taken:
            digest = hashlib.sha1(artist["name"].encode("utf-8")).hexdigest()[:6]
            slug = f"{slug}-{digest}"
            print(f"  slug collision: {artist['name']!r} -> {slug}", file=sys.stderr)
        taken.add(slug)
        artist["slug"] = slug

    universe.sort(key=lambda artist: (artist["tier"], -artist["listeners_at_seed"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(universe, indent=2, ensure_ascii=False) + "\n")

    print(
        f"\nWrote {len(universe)} artists to {OUT_PATH} "
        f"({len(blue_chip)} blue chip, {len(growth)} growth)",
        file=sys.stderr,
    )
    client.close()


API_KEY = os.environ.get("LASTFM_API_KEY", "")

if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("LASTFM_API_KEY is not set (try: set -a && . ./secrets.env && set +a)")
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted; no file was written.", file=sys.stderr)
        raise SystemExit(1)
