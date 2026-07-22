"use client";

import Link from "next/link";
import { useState } from "react";

import { HoldingRow } from "@/components/HoldingRow";
import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { formatCents, formatPct, pctChange } from "@/lib/format";
import { mockPortfolioHistory, mockTalentScoutScore } from "@/lib/mock-discovery";
import { useMe, usePortfolio } from "@/lib/queries";

const RANGES = ["1W", "1M", "3M", "1Y", "ALL"] as const;
type Range = (typeof RANGES)[number];
const RANGE_DAYS: Record<Range, number> = { "1W": 7, "1M": 30, "3M": 90, "1Y": 90, ALL: 90 };

export default function PortfolioPage() {
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);
  const [range, setRange] = useState<Range>("1M");
  const [showAdvanced, setShowAdvanced] = useState(false);

  if (me.isLoading || (me.data && portfolio.isLoading)) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        Loading…
      </p>
    );
  }

  if (!me.data) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-muted-foreground">
          Sign in to see your portfolio.
        </p>
        <Link href="/" className="text-sm font-bold text-primary">
          Get started →
        </Link>
      </div>
    );
  }

  if (portfolio.isError || !portfolio.data) {
    return (
      <p className="py-10 text-center text-sm text-destructive">
        Couldn&apos;t load your portfolio.
      </p>
    );
  }

  const { cash_cents, equity_cents, positions } = portfolio.data;
  // Growth vs. the fixed starting balance, not P&L over currently-held
  // cost basis: `avg_cost_cents` only reflects shares still held, so a
  // partially-sold position's realized gain has no cost basis left to
  // divide by there -- `equity_cents` already nets in every realized gain
  // via `cash_cents`, so comparing it against the known starting balance
  // gives the true all-time return without needing per-sale cost data.
  const totalGainCents = equity_cents - STARTING_BALANCE_CENTS;
  const totalGainPct = pctChange(STARTING_BALANCE_CENTS, equity_cents);
  const scoutShares = positions.reduce((sum, p) => sum + p.scout_shares, 0);
  const scout = mockTalentScoutScore(me.data.id);

  const history = mockPortfolioHistory(me.data.id, equity_cents);
  const rangeDays = Math.min(RANGE_DAYS[range], history.length);
  const rangeSlice = history.slice(history.length - rangeDays);
  const rangeChangePct = pctChange(rangeSlice[0].valueCents, rangeSlice[rangeSlice.length - 1].valueCents);
  const rangePositive = rangeChangePct >= 0;
  const rangeHigh = Math.max(...rangeSlice.map((p) => p.valueCents));
  const rangeLow = Math.min(...rangeSlice.map((p) => p.valueCents));
  const avgDailyPct = rangeChangePct / rangeSlice.length;
  const dailyReturns = rangeSlice.slice(1).map((p, i) => pctChange(rangeSlice[i].valueCents, p.valueCents));
  const volatilityPct = Math.sqrt(
    dailyReturns.reduce((sum, r) => sum + r * r, 0) / Math.max(dailyReturns.length, 1),
  );

  return (
    <div className="flex flex-col gap-6 pb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs text-muted-foreground">Total value</div>
          <div className="text-3xl font-extrabold tracking-tight">
            {formatCents(equity_cents)}
          </div>
          {positions.length > 0 && (
            <div
              className={`text-sm font-bold ${totalGainCents >= 0 ? "text-positive" : "text-destructive"}`}
            >
              {formatPct(totalGainPct)} all-time
            </div>
          )}
          <div className="mt-1 text-xs text-muted-foreground">
            {formatCents(cash_cents)} cash available
          </div>
        </div>
        <div className="rounded-2xl border border-border bg-card px-4 py-3.5 text-right">
          <div className="text-[11px] whitespace-nowrap text-muted-foreground">
            Talent Scout score
          </div>
          <div className="text-xl font-extrabold text-primary">
            {scout.score}{" "}
            <span className="text-xs font-medium text-muted-foreground">
              · top {scout.percentile}%
            </span>
          </div>
          <div className="text-[11px] text-muted-foreground">
            {scoutShares} scout shares
          </div>
        </div>
      </div>

      {positions.length > 0 && (
        <div className="rounded-2xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <span
              className={`text-sm font-bold ${rangePositive ? "text-positive" : "text-destructive"}`}
            >
              {formatPct(rangeChangePct)} over {range}
            </span>
            <div className="flex gap-1 rounded-lg bg-secondary p-1">
              {RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={`cursor-pointer rounded-md px-2.5 py-1.5 text-xs font-bold ${
                    range === r ? "bg-primary text-primary-foreground" : "text-muted-foreground"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
          <PortfolioValueChart points={rangeSlice} positive={rangePositive} />
          <div className="flex justify-end">
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="cursor-pointer text-xs font-bold text-primary"
            >
              {showAdvanced ? "Hide details" : "Show details"}
            </button>
          </div>
          {showAdvanced && (
            <div className="grid grid-cols-2 gap-3 border-t border-border pt-3 sm:grid-cols-4">
              <div>
                <div className="text-[11px] text-muted-foreground">High</div>
                <div className="text-sm font-bold">{formatCents(rangeHigh)}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Low</div>
                <div className="text-sm font-bold">{formatCents(rangeLow)}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Avg daily</div>
                <div className="text-sm font-bold">{formatPct(avgDailyPct, 2)}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Volatility</div>
                <div className="text-sm font-bold">{volatilityPct.toFixed(2)}%</div>
              </div>
            </div>
          )}
        </div>
      )}

      <div>
        <h2 className="mb-1 text-xs font-bold tracking-wide text-muted-foreground uppercase">
          Holdings
        </h2>
        {positions.length === 0 ? (
          <p className="py-6 text-sm text-muted-foreground">
            No positions yet.{" "}
            <Link href="/discover" className="font-bold text-primary">
              Find something to scout →
            </Link>
          </p>
        ) : (
          positions.map((p) => <HoldingRow key={p.artist_slug} position={p} />)
        )}
      </div>
    </div>
  );
}
