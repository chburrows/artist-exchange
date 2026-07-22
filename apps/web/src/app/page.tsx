"use client";

import Link from "next/link";

import { ArtistCard } from "@/components/ArtistCard";
import { HoldingRow } from "@/components/HoldingRow";
import { OnboardingScreen } from "@/components/OnboardingScreen";
import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { formatCents, formatPct, pctChange } from "@/lib/format";
import {
  useArtists,
  useMe,
  usePortfolio,
  usePortfolioHistory,
  useScoutLeaderboard,
} from "@/lib/queries";

export default function HomePage() {
  const me = useMe();

  if (me.isLoading) {
    return <p className="py-16 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (!me.data) {
    return <OnboardingScreen />;
  }
  return <HomeDashboard username={me.data.username} />;
}

function HomeDashboard({ username }: { username: string }) {
  const portfolio = usePortfolio(true);
  const artists = useArtists("growth");
  const history = usePortfolioHistory(true);
  const scoutLeaderboard = useScoutLeaderboard();

  const positions = portfolio.data?.positions ?? [];
  const equityCents = portfolio.data?.equity_cents ?? 0;

  // Real day-over-day change: today's live equity against last night's
  // nightly snapshot -- absent (not faked) until at least one snapshot
  // exists for this account.
  const historyPoints = history.data?.points ?? [];
  const yesterday = historyPoints[historyPoints.length - 1];
  const hasDayChange = yesterday !== undefined && yesterday.equity_cents > 0;
  const dayChangeCents = hasDayChange ? equityCents - yesterday.equity_cents : 0;
  const dayChangePct = hasDayChange ? pctChange(yesterday.equity_cents, equityCents) : 0;

  const chartPoints = historyPoints.slice(-30).map((p) => ({ valueCents: p.equity_cents }));

  const bestCall = [...positions].sort((a, b) => {
    const pctA = pctChange(a.avg_cost_cents, a.spot_price_cents);
    const pctB = pctChange(b.avg_cost_cents, b.spot_price_cents);
    return pctB - pctA;
  })[0];
  const bestCallPct = bestCall ? pctChange(bestCall.avg_cost_cents, bestCall.spot_price_cents) : 0;

  const scoutRank = scoutLeaderboard.data?.you?.rank;
  const scoutReturnPct = scoutLeaderboard.data?.you
    ? scoutLeaderboard.data.you.return_bps / 100
    : null;

  const discoveryTeaser = (artists.data ?? [])
    .map((a) => ({ ...a, changePct: a.daily_change_pct ?? 0 }))
    .sort((a, b) => b.changePct - a.changePct)
    .slice(0, 4);

  return (
    <div className="flex flex-col gap-6 pb-6">
      <p className="text-sm font-bold text-muted-foreground">Welcome back, {username}</p>

      <div className="rounded-2xl border border-border bg-card p-5">
        <div className="text-xs text-muted-foreground">Your portfolio</div>
        <div className="text-3xl font-extrabold tracking-tight">{formatCents(equityCents)}</div>
        {hasDayChange ? (
          <div className={`text-sm font-bold ${dayChangeCents >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatCents(dayChangeCents)} ({formatPct(dayChangePct)}) today
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">New today</div>
        )}

        {chartPoints.length > 0 && (
          <div className="mt-3">
            <PortfolioValueChart points={chartPoints} positive={dayChangeCents >= 0} height={72} />
          </div>
        )}

        {bestCall && (
          <div className="mt-3 border-t border-border pt-3">
            <div className="mb-1 text-[11px] text-muted-foreground">Best call this week</div>
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-bold">{bestCall.artist_name}</span>
              <span className={`text-sm font-bold ${bestCallPct >= 0 ? "text-positive" : "text-destructive"}`}>
                {formatPct(bestCallPct)}
              </span>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-border bg-card p-4 sm:col-span-2">
          <h2 className="mb-2 text-xs font-bold tracking-wide text-muted-foreground uppercase">
            Your holdings
          </h2>
          {positions.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              No positions yet.{" "}
              <Link href="/discover" className="font-bold text-primary">
                Start scouting →
              </Link>
            </p>
          ) : (
            positions.slice(0, 3).map((p) => <HoldingRow key={p.artist_slug} position={p} />)
          )}
        </div>
        <Link
          href="/leaderboard"
          className="flex flex-col justify-center rounded-2xl bg-secondary p-4 text-center"
        >
          <div className="text-[11px] text-muted-foreground">Talent Scout</div>
          {scoutReturnPct !== null ? (
            <>
              <div className="text-2xl font-extrabold text-primary">
                {formatPct(scoutReturnPct)}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">
                rank #{scoutRank} · view leaderboard
              </div>
            </>
          ) : (
            <div className="mt-1 text-[11px] text-muted-foreground">view leaderboard →</div>
          )}
        </Link>
      </div>

      <div>
        <div className="mb-2.5 flex items-center justify-between">
          <h2 className="text-xs font-bold tracking-wide text-muted-foreground uppercase">
            Discover something new
          </h2>
          <Link href="/discover" className="text-xs font-bold text-primary">
            See all in Discovery →
          </Link>
        </div>
        {discoveryTeaser.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing to discover yet.</p>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-1 sm:grid sm:grid-cols-4 sm:overflow-visible">
            {discoveryTeaser.map((a) => (
              <ArtistCard
                key={a.slug}
                slug={a.slug}
                name={a.name}
                tier={a.tier as "growth"}
                priceCents={a.spot_price_cents}
                changePct={a.changePct}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
