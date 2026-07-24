"use client";

import { type PointerEvent as ReactPointerEvent, useEffect, useId, useRef, useState } from "react";

import { buildLinePath } from "@/lib/chart";
import { formatCents, formatPct } from "@/lib/format";
import type { HistoryPoint } from "@/lib/queries";
import { cn } from "@/lib/utils";

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

const W = 400;
const H = 160;
const PAD = 10;

const DIMS = { width: W, height: H, pad: PAD };

/** The product's signature UI: market price vs. index fair value. */
export function PriceChart({ points }: { points: HistoryPoint[] }) {
  const [showFairValue, setShowFairValue] = useState(false);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const gradId = useId().replace(/[:]/g, "");

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
      <div className="border-border text-muted-foreground flex h-56 items-center justify-center rounded-2xl border text-sm">
        No price history yet.
      </div>
    );
  }

  const marketValues = points.map((p) => p.market_price_cents);
  const fairValues = points.map((p) => p.fair_value_cents);
  const hasFair = fairValues.some((v) => v !== null);
  const showFair = showFairValue && hasFair;
  const domainValues = [
    ...marketValues,
    ...(showFair ? fairValues.filter((v): v is number => v !== null) : []),
  ];
  const min = Math.min(...domainValues);
  const max = Math.max(...domainValues);

  const marketPath = buildLinePath(marketValues, min, max, DIMS);
  const fairPath = showFair ? buildLinePath(fairValues, min, max, DIMS) : null;
  const areaPath = `${marketPath} L${W - PAD},${H} L${PAD},${H} Z`;

  const first = points[0];
  const latest = points[points.length - 1];
  const changePct =
    first.market_price_cents === 0
      ? 0
      : ((latest.market_price_cents - first.market_price_cents) / first.market_price_cents) * 100;
  const up = latest.market_price_cents >= first.market_price_cents;
  const lineColor = up ? "var(--positive)" : "var(--destructive)";

  const step = points.length > 1 ? (W - PAD * 2) / (points.length - 1) : 0;
  const xAt = (i: number) => PAD + i * step;
  const yAt = (v: number) => H - PAD - ((v - min) / (max - min || 1)) * (H - PAD * 2);

  const onMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    const idx = Math.max(0, Math.min(points.length - 1, Math.round(frac * (points.length - 1))));
    setHoverIdx(idx);
  };

  const hover = hoverIdx !== null ? points[hoverIdx] : null;
  const hoverFx = hoverIdx !== null ? (xAt(hoverIdx) / W) * 100 : 0;
  const hoverFy = hover ? (yAt(hover.market_price_cents) / H) * 100 : 0;
  const tooltipTransform =
    hoverFx < 18 ? "translateX(-4px)" : hoverFx > 82 ? "translateX(-100%) translateX(4px)" : "translateX(-50%)";

  return (
    <div className="border-border bg-card flex flex-col gap-3 rounded-2xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-heading text-2xl font-bold tabular-nums">
            {formatCents(latest.market_price_cents)}
          </p>
          <p className="mt-0.5 flex items-center gap-2 text-xs">
            <span className={cn("font-mono font-bold tabular-nums", up ? "text-positive" : "text-destructive")}>
              {formatPct(changePct)}
            </span>
            <span className="text-faint">market price</span>
          </p>
        </div>
        {hasFair && (
          <button
            type="button"
            onClick={toggle}
            aria-pressed={showFairValue}
            className={cn(
              "press rounded-full border px-3 py-1.5 text-xs font-bold transition-colors",
              showFairValue
                ? "border-violet bg-violet-soft text-violet"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {showFairValue ? "Hide" : "Show"} fair value
          </button>
        )}
      </div>

      <div className="relative w-full">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="h-48 w-full touch-none select-none md:h-56"
          onPointerMove={onMove}
          onPointerDown={onMove}
          onPointerLeave={() => setHoverIdx(null)}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity={0.26} />
              <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${gradId})`} stroke="none" />
          {fairPath && (
            <path
              d={fairPath}
              fill="none"
              stroke="var(--violet)"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
              opacity={0.85}
            />
          )}
          <path
            d={marketPath}
            fill="none"
            stroke={lineColor}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
          {hoverIdx !== null && (
            <line
              x1={xAt(hoverIdx)}
              y1={0}
              x2={xAt(hoverIdx)}
              y2={H}
              stroke="var(--border-strong)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {hover && (
          <>
            <span
              className="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
              style={{
                left: `${hoverFx}%`,
                top: `${hoverFy}%`,
                background: lineColor,
                borderColor: "var(--card)",
              }}
            />
            <div
              className="border-border bg-popover pointer-events-none absolute top-1 rounded-lg border px-2.5 py-1.5 shadow-sm"
              style={{ left: `${hoverFx}%`, transform: tooltipTransform }}
            >
              <div className="font-mono text-xs font-bold tabular-nums">
                {formatCents(hover.market_price_cents)}
              </div>
              {showFair && hover.fair_value_cents !== null && (
                <div className="text-violet font-mono text-[0.65rem] font-semibold tabular-nums">
                  fair {formatCents(hover.fair_value_cents)}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <div className="text-faint flex items-center gap-4 text-[0.65rem] font-mono">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 rounded-full" style={{ background: lineColor }} /> price
        </span>
        {showFair && (
          <span className="flex items-center gap-1.5">
            <span className="border-violet inline-block w-3 border-t-2 border-dashed" /> fair-value index
          </span>
        )}
      </div>
    </div>
  );
}
