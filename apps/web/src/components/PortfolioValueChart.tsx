"use client";

import { useId } from "react";

import { ChangeBadge } from "@/components/ChangeBadge";
import { buildLinePath } from "@/lib/chart";
import { formatCents } from "@/lib/format";
import type { EquityPoint } from "@/lib/queries";

const W = 400;
const H = 130;
const PAD = 8;
const DIMS = { width: W, height: H, pad: PAD };

// A flat sample series, deliberately labeled as a demo rather than
// interpolated from real data -- `jobs/leaderboard.py` writes real
// points nightly, and a brand-new account legitimately has zero of them.
const DEMO_SHAPE = [1, 1.02, 0.98, 1.05, 1.03, 1.08, 1.06, 1.12];

/** Daily equity, oldest first. Fewer than two real points renders a
 * clearly-labeled stand-in instead of a misleading single-point chart. */
export function PortfolioValueChart({ points }: { points: EquityPoint[] }) {
  const gradId = useId().replace(/[:]/g, "");

  if (points.length < 2) {
    const demoMin = Math.min(...DEMO_SHAPE);
    const demoMax = Math.max(...DEMO_SHAPE);
    return (
      <div className="border-border bg-card flex flex-col gap-2 rounded-2xl border p-4">
        <p className="text-faint text-xs font-bold tracking-wide uppercase">Demo — not your real history</p>
        <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full opacity-40" preserveAspectRatio="none">
          <path
            d={buildLinePath(DEMO_SHAPE, demoMin, demoMax, DIMS)}
            fill="none"
            stroke="var(--muted-foreground)"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <p className="text-muted-foreground text-xs">
          Your real equity curve appears here after your first trade or tonight&apos;s snapshot.
        </p>
      </div>
    );
  }

  const values = points.map((p) => p.equity_cents);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = values[0];
  const latest = points[points.length - 1];
  const up = latest.equity_cents >= first;
  const lineColor = up ? "var(--positive)" : "var(--destructive)";
  const changePct = first === 0 ? 0 : ((latest.equity_cents - first) / first) * 100;

  const linePath = buildLinePath(values, min, max, DIMS);
  const areaPath = `${linePath} L${W - PAD},${H} L${PAD},${H} Z`;

  return (
    <div className="border-border bg-card flex flex-col gap-3 rounded-2xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-heading text-2xl font-bold tabular-nums">{formatCents(latest.equity_cents)}</p>
          <p className="text-faint mt-0.5 text-xs">Equity · as of {latest.as_of_date}</p>
        </div>
        <ChangeBadge pct={changePct} size="md" />
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full md:h-32" preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity={0.24} />
            <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${gradId})`} stroke="none" />
        <path
          d={linePath}
          fill="none"
          stroke={lineColor}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}
