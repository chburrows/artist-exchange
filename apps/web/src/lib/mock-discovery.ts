/**
 * Phase 6 placeholders. Leaderboards and some Discovery/Home stats have
 * no real backend yet (PLAN.md: leaderboards are a nightly materialized
 * view, not built until Phase 6) -- per the Phase 5 scope decision, this
 * file isolates every fabricated number in one place, deterministic per
 * id (not `Math.random()`) so a given artist/user always shows the same
 * illustrative figure across renders instead of jittering.
 *
 * Replace piecemeal as Phase 6 lands real endpoints:
 *   - mockDailyChangePct   -> a real day-over-day price diff, or the MV
 *   - mockTalentScoutScore -> the real Talent Scout formula/leaderboard
 *   - mockDayChangeCents   -> a stored daily equity snapshot
 *   - MOCK_*_LEADERBOARD   -> GET /leaderboard/portfolio, /leaderboard/scout
 */

function seededFraction(seed: number): number {
  const x = Math.sin(seed * 999_331 + 12.9898) * 43_758.5453;
  return x - Math.floor(x);
}

function stringSeed(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/** Keyed by slug, not a numeric id -- `ArtistOut` (the public artist
 * payload) doesn't expose the internal integer id, only `slug`. */
export function mockDailyChangePct(artistSlug: string): number {
  const f = seededFraction(stringSeed(artistSlug));
  return Math.round((f - 0.35) * 600) / 10; // ~ -21% .. +39%, one decimal
}

export function mockTalentScoutScore(userId: number): { score: number; percentile: number } {
  const f = seededFraction(userId * 7 + 3);
  return { score: Math.round(40 + f * 55), percentile: Math.round(5 + f * 40) };
}

export function mockDayChangeCents(userId: number, equityCents: number): number {
  const f = seededFraction(userId * 13 + 1) - 0.5;
  return Math.round(equityCents * f * 0.06);
}

export interface MockLeaderboardRow {
  rank: number;
  user: string;
  stat: string;
  /** Same value `stat` renders, kept numeric so real rows can be sorted
   * against mock rows instead of string-parsing the formatted display. */
  pctValue: number;
  note?: string;
  isYou?: boolean;
  /** Every row here is a Phase 6 placeholder (see file docstring) except
   * the one real "you" row spliced in by leaderboard/page.tsx -- rendered
   * as a "sample" tag so it's never mistaken for a real trader. */
  isMock?: boolean;
}

export const MOCK_PORTFOLIO_LEADERBOARD: MockLeaderboardRow[] = [
  { rank: 1, user: "wavecatcher", stat: "+412%", pctValue: 412, isMock: true },
  { rank: 2, user: "lowkeydiscog", stat: "+298%", pctValue: 298, isMock: true },
  { rank: 3, user: "frstlisten", stat: "+240%", pctValue: 240, isMock: true },
  { rank: 4, user: "b_sides", stat: "+201%", pctValue: 201, isMock: true },
  { rank: 5, user: "crate_diver", stat: "+188%", pctValue: 188, isMock: true },
];

export const MOCK_SCOUT_LEADERBOARD: MockLeaderboardRow[] = [
  { rank: 1, user: "crate_diver", stat: "+1,140%", pctValue: 1140, note: "Found an artist at $0.31", isMock: true },
  { rank: 2, user: "earlyplay", stat: "+780%", pctValue: 780, note: "Found an artist at $0.55", isMock: true },
  { rank: 3, user: "nightowlfm", stat: "+640%", pctValue: 640, note: "Found an artist at $2.10", isMock: true },
  { rank: 4, user: "demo_diggers", stat: "+590%", pctValue: 590, note: "Found an artist at $0.60", isMock: true },
  { rank: 5, user: "wavecatcher", stat: "+540%", pctValue: 540, note: "Found an artist at $1.05", isMock: true },
];
