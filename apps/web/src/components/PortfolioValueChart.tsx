"use client";

import type { EquityPoint } from "@/lib/queries";
import { formatCents } from "@/lib/format";

const WIDTH = 600;
const HEIGHT = 180;
const PADDING = 16;

function buildPath(values: number[]): string {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? (WIDTH - PADDING * 2) / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = PADDING + i * step;
      const y = HEIGHT - PADDING - ((v - min) / span) * (HEIGHT - PADDING * 2);
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
}

// A flat sample series, deliberately labeled as a demo rather than
// interpolated from real data -- `jobs/leaderboard.py` writes real
// points nightly, and a brand-new account legitimately has zero of them
// (ARCHITECTURE.md: "there is nothing to backfill or fake here").
const DEMO_SHAPE = [1, 1.02, 0.98, 1.05, 1.03, 1.08, 1.06, 1.12];

/** Daily equity, oldest first. Fewer than two real points renders a
 * clearly-labeled stand-in instead of a misleading single-point chart. */
export function PortfolioValueChart({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-border p-4">
        <p className="text-xs font-bold text-muted-foreground">Demo — not your real history</p>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-40 w-full opacity-40" preserveAspectRatio="none">
          <path d={buildPath(DEMO_SHAPE)} fill="none" stroke="var(--muted-foreground)" strokeWidth={2} />
        </svg>
        <p className="text-xs text-muted-foreground">
          Your real equity history appears here after your first trade or tonight&apos;s snapshot.
        </p>
      </div>
    );
  }

  const values = points.map((p) => p.equity_cents);
  const latest = points[points.length - 1];

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border p-4">
      <div>
        <p className="text-2xl font-bold">{formatCents(latest.equity_cents)}</p>
        <p className="text-xs text-muted-foreground">Equity as of {latest.as_of_date}</p>
      </div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-40 w-full" preserveAspectRatio="none">
        <path d={buildPath(values)} fill="none" stroke="var(--primary)" strokeWidth={2} />
      </svg>
    </div>
  );
}
