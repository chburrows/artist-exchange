"use client";

import { useEffect, useState } from "react";

import type { HistoryPoint } from "@/lib/queries";
import { formatCents } from "@/lib/format";

const STORAGE_KEY = "ax-show-fair-value";

/** Off by default, persisted like the dark-mode preference once a user
 * opts in (ARCHITECTURE.md: "the fair-value series is user-toggleable
 * and off by default"). */
function readStoredPreference(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

const WIDTH = 600;
const HEIGHT = 240;
const PADDING = 24;

function buildPath(values: (number | null)[], min: number, max: number): string {
  const span = max - min || 1;
  const step = values.length > 1 ? (WIDTH - PADDING * 2) / (values.length - 1) : 0;
  let path = "";
  values.forEach((v, i) => {
    if (v === null) return;
    const x = PADDING + i * step;
    const y = HEIGHT - PADDING - ((v - min) / span) * (HEIGHT - PADDING * 2);
    path += path === "" ? `M ${x} ${y}` : ` L ${x} ${y}`;
  });
  return path;
}

/** The product's signature UI: market price vs. index fair value.
 * Points are spaced by index, not elapsed time -- backfilled/dev history
 * is unevenly spaced, and a time-based x-axis would misrepresent it
 * (ARCHITECTURE.md). Placeholder styling only; visual design lands in
 * build step 4. */
export function PriceChart({ points }: { points: HistoryPoint[] }) {
  const [showFairValue, setShowFairValue] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShowFairValue(readStoredPreference());
  }, []);

  const toggle = () => {
    setShowFairValue((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // Private-browsing / storage-disabled: the toggle just won't persist.
      }
      return next;
    });
  };

  if (points.length === 0) {
    return (
      <div className="flex h-60 items-center justify-center rounded-xl border border-border text-sm text-muted-foreground">
        No price history yet.
      </div>
    );
  }

  const marketValues = points.map((p) => p.market_price_cents);
  const fairValues = points.map((p) => p.fair_value_cents);
  const allValues = [...marketValues, ...(showFairValue ? fairValues.filter((v): v is number => v !== null) : [])];
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);

  const marketPath = buildPath(marketValues, min, max);
  const fairPath = showFairValue ? buildPath(fairValues, min, max) : null;

  const latest = points[points.length - 1];

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-2xl font-bold">{formatCents(latest.market_price_cents)}</p>
          <p className="text-xs text-muted-foreground">Market price</p>
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-pressed={showFairValue}
          className={`min-h-9 rounded-full border border-border px-3 text-xs font-bold ${
            showFairValue ? "bg-primary text-primary-foreground" : "text-muted-foreground"
          }`}
        >
          {showFairValue ? "Hide" : "Show"} index fair value
        </button>
      </div>

      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-60 w-full" preserveAspectRatio="none">
        <path d={marketPath} fill="none" stroke="var(--primary)" strokeWidth={2} />
        {fairPath && (
          <path
            d={fairPath}
            fill="none"
            stroke="var(--muted-foreground)"
            strokeWidth={2}
            strokeDasharray="6 4"
          />
        )}
      </svg>

      {showFairValue && (
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-3 bg-primary" /> Market price
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-3 border-t-2 border-dashed border-muted-foreground" /> Index
            fair value
          </span>
        </div>
      )}
    </div>
  );
}
