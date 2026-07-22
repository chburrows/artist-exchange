"use client";

import { useId } from "react";

const WIDTH = 100;
const HEIGHT = 40;

/** Area + line chart of portfolio value over time -- the Home/Portfolio
 * counterpart to `PriceChart`'s dual-line market-vs-fair-value chart.
 * Scale-independent viewBox like `PriceChart`, styled after the same
 * gradient-fill technique used across the wireframes this was built from. */
export function PortfolioValueChart({
  points,
  positive,
  height = 150,
}: {
  points: { valueCents: number }[];
  positive: boolean;
  height?: number;
}) {
  const gradientId = useId();

  if (points.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ height }}
      >
        Not enough history yet.
      </div>
    );
  }

  const values = points.map((p) => p.valueCents);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const xFor = (i: number) => (i / (points.length - 1)) * WIDTH;
  const yFor = (v: number) => HEIGHT - ((v - min) / range) * (HEIGHT - 1) - 1;

  const linePath = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(p.valueCents).toFixed(2)}`,
    )
    .join(" ");
  const areaPath = `${linePath} L${WIDTH},${HEIGHT} L0,${HEIGHT} Z`;
  const color = positive ? "var(--positive)" : "var(--destructive)";

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      style={{ height }}
      className="w-full"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
