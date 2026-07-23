import { STARTING_BALANCE_CENTS } from "@/lib/constants";

export type ChartPoint = { valueCents: number };

/** Cash only drifts from the starting balance via a trade (fees make even a
 * fully round-tripped buy/sell leave a mark), so this plus an open position
 * both catch "has traded" without a dedicated API field. */
export function computeHasTraded(positionCount: number, cashCents: number): boolean {
  return positionCount > 0 || cashCents !== STARTING_BALANCE_CENTS;
}

/** Real history first; once there are at least two nightly snapshots this is
 * the genuine equity curve -- returned as-is, never truncated, so a caller
 * can't accidentally collapse real multi-point history into the two-point
 * fallback below. Below two snapshots, don't wait for tonight's job to show
 * *something* real: a trade already gives two true data points -- the last
 * snapshot (or, before any snapshot exists, the known starting balance) and
 * live equity right now. */
export function buildLiveChartPoints(
  realPoints: ChartPoint[],
  liveEquityCents: number,
  hasTraded: boolean,
): ChartPoint[] {
  if (realPoints.length >= 2) return realPoints;
  if (realPoints.length === 1) {
    return [realPoints[0], { valueCents: liveEquityCents }];
  }
  if (hasTraded) {
    return [{ valueCents: STARTING_BALANCE_CENTS }, { valueCents: liveEquityCents }];
  }
  return [];
}

/** Whether a chart's line should render in the positive or negative color.
 * Fewer than two points never actually reaches a caller that reads this --
 * `PortfolioValueChart` shows its empty state instead -- so `true` here is
 * just a harmless, consistent default rather than a meaningful signal. */
export function isChartTrendPositive(points: ChartPoint[]): boolean {
  if (points.length < 2) return true;
  return points[points.length - 1].valueCents >= points[0].valueCents;
}
