"use client";

import Link from "next/link";

import { HoldingRow } from "@/components/HoldingRow";
import { formatCents, formatPct, pctChange } from "@/lib/format";
import { mockTalentScoutScore } from "@/lib/mock-discovery";
import { useMe, usePortfolio } from "@/lib/queries";

export default function PortfolioPage() {
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);

  if (me.isLoading || (me.data && portfolio.isLoading)) {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }

  if (!me.data) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-muted-foreground">Sign in to see your portfolio.</p>
        <Link href="/" className="text-sm font-bold text-primary">
          Get started →
        </Link>
      </div>
    );
  }

  if (portfolio.isError || !portfolio.data) {
    return <p className="py-10 text-center text-sm text-destructive">Couldn&apos;t load your portfolio.</p>;
  }

  const { cash_cents, equity_cents, positions } = portfolio.data;
  const costBasisCents = positions.reduce((sum, p) => sum + p.avg_cost_cents * p.shares, 0);
  const totalGainCents = positions.reduce((sum, p) => sum + p.unrealized_pnl_cents + p.realized_pnl_cents, 0);
  const totalGainPct = costBasisCents > 0 ? pctChange(costBasisCents, costBasisCents + totalGainCents) : 0;
  const scoutShares = positions.reduce((sum, p) => sum + p.scout_shares, 0);
  const scout = mockTalentScoutScore(me.data.id);

  return (
    <div className="flex flex-col gap-6 pb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs text-muted-foreground">Total value</div>
          <div className="text-3xl font-extrabold tracking-tight">{formatCents(equity_cents)}</div>
          {positions.length > 0 && (
            <div className={`text-sm font-bold ${totalGainCents >= 0 ? "text-positive" : "text-destructive"}`}>
              {formatPct(totalGainPct)} all-time
            </div>
          )}
          <div className="mt-1 text-xs text-muted-foreground">{formatCents(cash_cents)} cash available</div>
        </div>
        <div className="rounded-2xl border border-border bg-card px-4 py-3.5 text-right">
          <div className="text-[11px] whitespace-nowrap text-muted-foreground">Talent Scout score</div>
          <div className="text-xl font-extrabold text-primary">
            {scout.score} <span className="text-xs font-medium text-muted-foreground">· top {scout.percentile}%</span>
          </div>
          <div className="text-[11px] text-muted-foreground">{scoutShares} scout shares</div>
        </div>
      </div>

      <div>
        <h2 className="mb-1 text-xs font-bold tracking-wide text-muted-foreground uppercase">Holdings</h2>
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
