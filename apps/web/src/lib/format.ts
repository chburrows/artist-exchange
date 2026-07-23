// Money is integer cents everywhere (CLAUDE.md) -- this is the only
// place a cents value becomes a display string.
const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatCents(cents: number): string {
  return currencyFormatter.format(cents / 100);
}

/** `daily_change_pct` (ArtistOut) is already a percentage, not a
 * fraction -- format directly, no `* 100`. */
export function formatPct(pct: number, { signed = true } = {}): string {
  const sign = signed && pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

/** `return_bps` (leaderboard rows) is basis points, i.e. 1/100th of a
 * percent -- divide by 100 to get the percentage `formatPct` expects. */
export function formatBps(bps: number): string {
  return formatPct(bps / 100);
}
