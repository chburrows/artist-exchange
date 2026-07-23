"use client";

import Link from "next/link";

import { OnboardingScreen } from "@/components/OnboardingScreen";
import { formatCents, formatPct } from "@/lib/format";
import { useArtists, useMe, usePortfolio } from "@/lib/queries";

export default function HomePage() {
  const me = useMe();
  const loggedIn = !!me.data;
  const portfolio = usePortfolio(loggedIn);
  const artists = useArtists();

  if (me.isLoading) {
    return <p className="py-16 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (!me.data) {
    return <OnboardingScreen />;
  }

  const movers = [...(artists.data ?? [])]
    .sort((a, b) => Math.abs(b.daily_change_pct ?? 0) - Math.abs(a.daily_change_pct ?? 0))
    .slice(0, 3);
  const topHoldings = [...(portfolio.data?.positions ?? [])]
    .sort((a, b) => b.market_value_cents - a.market_value_cents)
    .slice(0, 3);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <p className="text-sm font-bold text-muted-foreground">Welcome back, {me.data.username}</p>

      <Link
        href="/portfolio"
        className="flex justify-between rounded-xl border border-border p-4"
      >
        <div>
          <p className="text-xs text-muted-foreground">Cash</p>
          <p className="text-lg font-bold">
            {portfolio.data ? formatCents(portfolio.data.cash_cents) : "—"}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Total equity</p>
          <p className="text-lg font-bold">
            {portfolio.data ? formatCents(portfolio.data.equity_cents) : "—"}
          </p>
        </div>
      </Link>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold">Your top holdings</h2>
          <Link href="/portfolio" className="text-xs text-muted-foreground underline underline-offset-2">
            See all
          </Link>
        </div>
        {topHoldings.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No positions yet.{" "}
            <Link href="/discover" className="font-bold text-primary underline underline-offset-2">
              Discover an artist
            </Link>{" "}
            to make your first trade.
          </p>
        ) : (
          <div className="flex flex-col">
            {topHoldings.map((p) => (
              <Link
                key={p.artist_slug}
                href={`/artist?slug=${encodeURIComponent(p.artist_slug)}`}
                className="flex min-h-11 items-center justify-between gap-4 border-b border-border py-3 last:border-b-0"
              >
                <span className="text-sm font-bold">{p.artist_name}</span>
                <span className="text-sm font-bold">{formatCents(p.market_value_cents)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold">Biggest movers</h2>
          <Link href="/discover" className="text-xs text-muted-foreground underline underline-offset-2">
            See all
          </Link>
        </div>
        <div className="flex flex-col">
          {movers.map((artist) => {
            const change = artist.daily_change_pct;
            const changeClass = change === null ? "text-muted-foreground" : change >= 0 ? "text-positive" : "text-destructive";
            return (
              <Link
                key={artist.slug}
                href={`/artist?slug=${encodeURIComponent(artist.slug)}`}
                className="flex min-h-11 items-center justify-between gap-4 border-b border-border py-3 last:border-b-0"
              >
                <span className="text-sm font-bold">{artist.name}</span>
                <span className={`text-sm font-bold ${changeClass}`}>
                  {change === null ? "—" : formatPct(change)}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
