/** Money and percent display helpers. Every amount from the API is
 * integer cents (CLAUDE.md rule 1) -- formatting is the only place a
 * float is allowed to exist, and only for display. */

export function formatCents(cents: number): string {
  return (cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatSignedCents(cents: number): string {
  const sign = cents > 0 ? "+" : cents < 0 ? "-" : "";
  return `${sign}${formatCents(Math.abs(cents))}`;
}

export function formatPct(pct: number, digits = 1): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(digits)}%`;
}

/** Magnitude only, no sign -- for callers that already convey direction
 * with a word ("Up"/"Down") and would otherwise double up ("Down +9.5%"). */
export function formatPctAbs(pct: number, digits = 1): string {
  return `${Math.abs(pct).toFixed(digits)}%`;
}

export function pctChange(fromCents: number, toCents: number): number {
  if (fromCents === 0) return 0;
  return ((toCents - fromCents) / fromCents) * 100;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatCompact(n: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(n);
}

export interface ChangeSince {
  pct: number;
  fromCents: number;
  fromIso: string;
  /** True if the series doesn't actually reach back `hours` -- the
   * change shown is "since inception," not a genuine window match. */
  sinceInception: boolean;
}

/** Real day-over-day (or any window) change, computed from actual
 * `price_history.at` timestamps -- not mocked. In a freshly seeded dev
 * DB every row lands within the same few minutes of wall-clock time (see
 * `ax fake-history`'s docstring), so this naturally falls back to
 * "since inception" there; in production, where history really does
 * span real days, the same logic finds a genuine ~`hours`-old point. */
export function changeSince(
  points: { at: string; market_price_cents: number }[],
  hours: number,
): ChangeSince | null {
  if (points.length < 2) return null;
  const latest = points[points.length - 1];
  const cutoff = Date.now() - hours * 3_600_000;

  let base = points[0];
  let sinceInception = true;
  for (const p of points) {
    if (new Date(p.at).getTime() <= cutoff) {
      base = p;
      sinceInception = false;
    } else break;
  }

  return {
    pct: pctChange(base.market_price_cents, latest.market_price_cents),
    fromCents: base.market_price_cents,
    fromIso: base.at,
    sinceInception,
  };
}
