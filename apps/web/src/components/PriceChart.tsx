import type { HistoryPoint } from "@/lib/queries";

const WIDTH = 600;
const HEIGHT = 200;
const PAD_X = 4;
const PAD_Y = 10;

/** The signature chart: market price (solid) vs. index fair value
 * (dashed). Points are spaced by index, not by literal elapsed time --
 * local dev history is backfilled well ahead of when trades land (see
 * `ax fake-history`), so most `price_history.at` timestamps cluster near
 * "now" rather than spreading evenly across the series; index-based
 * spacing keeps the shape of the series readable regardless. */
export function PriceChart({ points }: { points: HistoryPoint[] }) {
  if (points.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        No price history yet.
      </div>
    );
  }

  const marketVals = points.map((p) => p.market_price_cents);
  const fairSeries = points
    .map((p, i) => ({ i, v: p.fair_value_cents }))
    .filter((p): p is { i: number; v: number } => p.v !== null && p.v !== undefined);

  const allVals = [...marketVals, ...fairSeries.map((p) => p.v)];
  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const range = max - min || 1;

  const xFor = (i: number) =>
    points.length === 1 ? WIDTH / 2 : PAD_X + (i / (points.length - 1)) * (WIDTH - PAD_X * 2);
  const yFor = (v: number) => HEIGHT - PAD_Y - ((v - min) / range) * (HEIGHT - PAD_Y * 2);

  const marketPath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(p.market_price_cents).toFixed(2)}`)
    .join(" ");

  const fairPath = fairSeries
    .map((p, idx) => `${idx === 0 ? "M" : "L"}${xFor(p.i).toFixed(2)},${yFor(p.v).toFixed(2)}`)
    .join(" ");

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-40 w-full sm:h-48"
      >
        {fairPath && (
          <path
            d={fairPath}
            fill="none"
            stroke="var(--muted-foreground)"
            strokeWidth={2}
            strokeDasharray="5,5"
          />
        )}
        <path d={marketPath} fill="none" stroke="var(--foreground)" strokeWidth={2.5} />
      </svg>
      <div className="mt-2 flex gap-5 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3.5 bg-foreground" /> Market price
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="h-0 w-3.5 border-t-2 border-dashed"
            style={{ borderColor: "var(--muted-foreground)" }}
          />
          Index fair value
        </span>
      </div>
    </div>
  );
}
