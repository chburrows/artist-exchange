"use client";

import Link from "next/link";
import { useId, useSyncExternalStore } from "react";

const WIDTH = 100;
const HEIGHT = 40;

const DEMO_PAD_Y = 4;

const DEMO_POINTS = 20;

function demoClamp(v: number) {
  return Math.min(0.97, Math.max(0.04, v));
}

/** A steep trend from `start` to `end` (fractions of chart height) with a
 * jagged sine-driven zigzag riding on top of it, amplitude `amplitude`. */
function buildTrendShape(start: number, end: number, amplitude: number, bumps: number) {
  const vals: number[] = [];
  for (let i = 0; i < DEMO_POINTS; i++) {
    const t = i / (DEMO_POINTS - 1);
    const trend = start + (end - start) * t;
    const noise = Math.sin(t * Math.PI * bumps) * amplitude;
    vals.push(demoClamp(trend + noise));
  }
  return vals;
}

/** Two trend legs, `start`->`mid` then `mid`->`end`, for a crash-and-recover
 * or spike-and-pullback shape, with the same zigzag noise as `buildTrendShape`. */
function buildReversalShape(start: number, mid: number, end: number, amplitude: number, bumps: number) {
  const vals: number[] = [];
  for (let i = 0; i < DEMO_POINTS; i++) {
    const t = i / (DEMO_POINTS - 1);
    const trend = t < 0.5 ? start + (mid - start) * (t / 0.5) : mid + (end - mid) * ((t - 0.5) / 0.5);
    const noise = Math.sin(t * Math.PI * bumps) * amplitude;
    vals.push(demoClamp(trend + noise));
  }
  return vals;
}

// Deterministic (not random -- this renders on the server, and
// Math.random() at module scope would make static export non-reproducible
// and risk a hydration mismatch) stand-ins for a real equity curve: a mix
// of trending and reversal shapes, each with a wide range and a sharp
// zigzag, so the loop reads as a real, volatile chart rather than a
// gentle wiggle. Values are fractions of chart height (0 = bottom, 1 =
// top); each array is the same length so SMIL can interpolate
// point-for-point between shapes. Trend shapes use a bigger amplitude
// (0.1) since a straight run has nothing else to read as "volatile";
// reversal shapes use a smaller one (0.07) so the crash/spike leg itself
// stays the dominant feature instead of being buried in noise. Bump
// counts (3.5 / 3) just keep the zigzag period roughly proportional to
// each shape's length.
const DEMO_SHAPES: { values: number[]; positive: boolean }[] = [
  { values: buildTrendShape(0.12, 0.9, 0.1, 3.5), positive: true },
  { values: buildTrendShape(0.85, 0.1, 0.1, 3.5), positive: false },
  { values: buildReversalShape(0.75, 0.06, 0.93, 0.07, 3), positive: true },
  { values: buildReversalShape(0.16, 0.92, 0.28, 0.07, 3), positive: false },
];

function demoXFor(i: number, n: number) {
  return (i / (n - 1)) * WIDTH;
}
function demoYFor(v: number) {
  return HEIGHT - DEMO_PAD_Y - v * (HEIGHT - DEMO_PAD_Y * 2);
}

function demoLinePath(values: number[]) {
  return values
    .map((v, i) => `${i === 0 ? "M" : "L"}${demoXFor(i, values.length).toFixed(2)},${demoYFor(v).toFixed(2)}`)
    .join(" ");
}

const DEMO_LINE_PATHS = DEMO_SHAPES.map((s) => demoLinePath(s.values));
const DEMO_AREA_PATHS = DEMO_LINE_PATHS.map((line) => `${line} L${WIDTH},${HEIGHT} L0,${HEIGHT} Z`);
// Literal hex, not `var(--positive)`/`var(--destructive)`: SMIL <animate>
// needs a resolvable color to interpolate between keyframes, and browsers
// don't resolve CSS custom properties inside a `values` list -- it just
// freezes on the first color instead of animating. These are the light-
// theme values from globals.css; close enough on dark too at this
// element's low opacity, and simpler than threading theme state into a
// server-renderable component just for a decorative placeholder.
const DEMO_COLORS = DEMO_SHAPES.map((s) => (s.positive ? "#1e9e62" : "#d8483a"));

const DEMO_HOLD_SECONDS = 1.4;
const DEMO_MORPH_SECONDS = 0.9;

/** Builds a SMIL `values`/`keyTimes` pair that holds each item for
 * `holdSeconds`, then morphs linearly to the next over `morphSeconds`,
 * looping back to the first item at the end. Repeating an item's value at
 * both the start and end of its hold window is what makes SMIL stay put
 * instead of interpolating during that span. */
function buildHoldMorphSchedule(items: string[], holdSeconds: number, morphSeconds: number) {
  const cycle = holdSeconds + morphSeconds;
  const total = items.length * cycle;
  const keyTimes: number[] = [];
  const values: string[] = [];
  items.forEach((item, i) => {
    const holdStart = i * cycle;
    keyTimes.push(holdStart / total, (holdStart + holdSeconds) / total);
    values.push(item, item);
  });
  keyTimes.push(1);
  values.push(items[0]);
  return {
    keyTimes: keyTimes.map((t) => t.toFixed(5)).join(";"),
    values: values.join(";"),
    dur: `${total}s`,
  };
}

const DEMO_PATH_SCHEDULE = buildHoldMorphSchedule(DEMO_AREA_PATHS, DEMO_HOLD_SECONDS, DEMO_MORPH_SECONDS);
const DEMO_LINE_SCHEDULE = buildHoldMorphSchedule(DEMO_LINE_PATHS, DEMO_HOLD_SECONDS, DEMO_MORPH_SECONDS);
const DEMO_COLOR_SCHEDULE = buildHoldMorphSchedule(DEMO_COLORS, DEMO_HOLD_SECONDS, DEMO_MORPH_SECONDS);

function subscribeReducedMotion(onChange: () => void) {
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

/** `DEMO_COLOR_SCHEDULE`-driven `<animate>`, shared by the gradient stop
 * and the line stroke so the two color schedules can't drift out of sync. */
function ColorMorph({ attributeName }: { attributeName: string }) {
  return (
    <animate
      attributeName={attributeName}
      values={DEMO_COLOR_SCHEDULE.values}
      keyTimes={DEMO_COLOR_SCHEDULE.keyTimes}
      dur={DEMO_COLOR_SCHEDULE.dur}
      repeatCount="indefinite"
    />
  );
}

/** Idle-state filler for `PortfolioValueChart`: a demo equity curve that
 * holds a realistic-looking shape for a few seconds, then morphs into
 * another, standing in for real history until there's enough of it to
 * plot. Uses SMIL (`<animate>`) rather than CSS keyframes because it can
 * interpolate the `d` attribute itself -- CSS can't tween between two
 * arbitrary path shapes. Explicitly labeled "Example" (not just captioned)
 * since it's styled identically to the real chart and shouldn't read as
 * the user's own data. Animation is skipped for `prefers-reduced-motion`,
 * leaving a static first frame. */
function EmptyValueChart({
  height,
  title,
  ctaLabel,
}: {
  height: number;
  title: string;
  ctaLabel?: string;
}) {
  const gradientId = useId();
  const reducedMotion = usePrefersReducedMotion();

  return (
    <div className="relative overflow-hidden rounded-xl" style={{ height }}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        style={{ height }}
        className="w-full opacity-50"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={DEMO_COLORS[0]} stopOpacity={0.35}>
              {!reducedMotion && <ColorMorph attributeName="stop-color" />}
            </stop>
            <stop offset="100%" stopColor={DEMO_COLORS[0]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path fill={`url(#${gradientId})`} stroke="none" d={DEMO_AREA_PATHS[0]}>
          {!reducedMotion && (
            <animate
              attributeName="d"
              values={DEMO_PATH_SCHEDULE.values}
              keyTimes={DEMO_PATH_SCHEDULE.keyTimes}
              dur={DEMO_PATH_SCHEDULE.dur}
              repeatCount="indefinite"
            />
          )}
        </path>
        <path
          fill="none"
          stroke={DEMO_COLORS[0]}
          strokeWidth={1.6}
          vectorEffect="non-scaling-stroke"
          d={DEMO_LINE_PATHS[0]}
        >
          {!reducedMotion && (
            <>
              <animate
                attributeName="d"
                values={DEMO_LINE_SCHEDULE.values}
                keyTimes={DEMO_LINE_SCHEDULE.keyTimes}
                dur={DEMO_LINE_SCHEDULE.dur}
                repeatCount="indefinite"
              />
              <ColorMorph attributeName="stroke" />
            </>
          )}
        </path>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 px-4 text-center">
        <p className="text-[9px] font-bold tracking-wide text-muted-foreground/70 uppercase">Example</p>
        <p className="text-xs font-bold text-muted-foreground">{title}</p>
        {ctaLabel && (
          <Link href="/discover" className="text-[11px] font-bold text-primary">
            {ctaLabel}
          </Link>
        )}
      </div>
    </div>
  );
}

/** Area + line chart of portfolio value over time -- the Home/Portfolio
 * counterpart to `PriceChart`'s dual-line market-vs-fair-value chart.
 * Scale-independent viewBox like `PriceChart`, styled after the same
 * gradient-fill technique used across the wireframes this was built from. */
export function PortfolioValueChart({
  points,
  positive,
  height = 150,
  hasTraded = false,
  emptyTitle,
  emptyCta,
}: {
  points: { valueCents: number }[];
  positive: boolean;
  height?: number;
  /** Whether the user has already traded -- picks the empty-state copy so
   * it doesn't tell someone who's already bought in to "make a trade". */
  hasTraded?: boolean;
  emptyTitle?: string;
  emptyCta?: string;
}) {
  const gradientId = useId();

  if (points.length < 2) {
    const title =
      emptyTitle ??
      (hasTraded
        ? "Your performance history builds up after tonight's snapshot"
        : "Make a trade to start tracking your portfolio");
    const ctaLabel = emptyCta ?? (hasTraded ? undefined : "Start scouting →");
    return <EmptyValueChart height={height} title={title} ctaLabel={ctaLabel} />;
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
