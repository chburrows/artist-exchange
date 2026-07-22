"use client";

import Link from "next/link";
import { useState } from "react";

import { HoldingRow } from "@/components/HoldingRow";
import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { ShareCardDialog } from "@/components/ShareCardDialog";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { formatCents, formatPct, pctChange } from "@/lib/format";
import { useMe, usePortfolio, usePortfolioHistory, useScoutLeaderboard } from "@/lib/queries";

const RANGES = ["1W", "1M", "3M", "1Y", "ALL"] as const;
type Range = (typeof RANGES)[number];
const RANGE_DAYS: Record<Range, number> = { "1W": 7, "1M": 30, "3M": 90, "1Y": 365, ALL: Infinity };

export default function PortfolioPage() {
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);
  const history = usePortfolioHistory(!!me.data);
  const scoutLeaderboard = useScoutLeaderboard();
  const [range, setRange] = useState<Range>("1M");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

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

  // Your single best scouting call: the currently-held scout-qualified
  // position with the highest unrealized return, computed live from real
  // position data -- not the (up to a day stale) leaderboard snapshot.
  // `scoutLeaderboard`'s "you" entry supplies the rank, which genuinely
  // can only come from the nightly-refreshed table (PLAN.md: ranking
  // requires comparing against every other user).
  const bestScout = positions
    .filter((p) => p.scout_shares > 0)
    .map((p) => ({ position: p, pct: pctChange(p.avg_cost_cents, p.spot_price_cents) }))
    .sort((a, b) => b.pct - a.pct)[0];
  const scoutRank = scoutLeaderboard.data?.you?.rank;

  // Real nightly equity snapshots (PLAN.md Phase 6), oldest first --
  // empty for an account that predates tonight's first run.
  const equityPoints = (history.data?.points ?? []).map((p) => ({ valueCents: p.equity_cents }));
  const hasEnoughHistory = equityPoints.length >= 2;
  const rangeDays = hasEnoughHistory ? Math.min(RANGE_DAYS[range], equityPoints.length) : 0;
  const rangeSlice = hasEnoughHistory ? equityPoints.slice(equityPoints.length - rangeDays) : [];
  const rangeChangePct = hasEnoughHistory
    ? pctChange(rangeSlice[0].valueCents, rangeSlice[rangeSlice.length - 1].valueCents)
    : 0;
  const rangePositive = rangeChangePct >= 0;
  const rangeHigh = hasEnoughHistory ? Math.max(...rangeSlice.map((p) => p.valueCents)) : 0;
  const rangeLow = hasEnoughHistory ? Math.min(...rangeSlice.map((p) => p.valueCents)) : 0;
  const avgDailyPct = hasEnoughHistory ? rangeChangePct / rangeSlice.length : 0;
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
          <button
            onClick={() => setShareOpen(true)}
            className="mt-2 cursor-pointer text-xs font-bold text-primary"
          >
            Share ↗
          </button>
        </div>
        <div className="rounded-2xl border border-border bg-card px-4 py-3.5 text-right">
          <div className="text-[11px] whitespace-nowrap text-muted-foreground">Talent Scout</div>
          {bestScout ? (
            <>
              <div className="text-xl font-extrabold text-primary">
                {formatPct(bestScout.pct)}
                {scoutRank !== undefined && (
                  <span className="text-xs font-medium text-muted-foreground"> · #{scoutRank}</span>
                )}
              </div>
              <div className="max-w-[10rem] truncate text-[11px] text-muted-foreground">
                on {bestScout.position.artist_name}
              </div>
            </>
          ) : (
            <div className="text-[11px] text-muted-foreground">
              {scoutShares} scout shares
            </div>
          )}
        </div>
      </div>

      {equityPoints.length > 0 && (
        <div className="rounded-2xl border border-border bg-card p-5">
          {hasEnoughHistory && (
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
          )}
          <PortfolioValueChart points={hasEnoughHistory ? rangeSlice : equityPoints} positive={rangePositive} />
          {hasEnoughHistory && (
            <div className="flex justify-end">
              <button
                onClick={() => setShowAdvanced((v) => !v)}
                className="cursor-pointer text-xs font-bold text-primary"
              >
                {showAdvanced ? "Hide details" : "Show details"}
              </button>
            </div>
          )}
          {hasEnoughHistory && showAdvanced && (
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

      <ShareCardDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        username={me.data.username}
        equityCents={equity_cents}
        totalGainPct={totalGainPct}
        topPositions={positions}
      />
    </div>
  );
}
