"use client";

import Link from "next/link";
import { useState } from "react";

import { Avatar } from "@/components/Avatar";
import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { RenameUsernameDialog } from "@/components/RenameUsernameDialog";
import { ShareCard } from "@/components/ShareCard";
import type { ShareCardData } from "@/components/ShareCard";
import { Skeleton } from "@/components/ui/skeleton";
import { ShareIcon, SparkIcon } from "@/components/icons";
import { formatCents } from "@/lib/format";
import type { PortfolioResponse } from "@/lib/queries";
import { useMe, usePortfolio, usePortfolioHistory, useScoutLeaderboard } from "@/lib/queries";
import { cn } from "@/lib/utils";

type BestCall = {
  name: string;
  slug: string;
  gainPct: number;
  boughtCents: number;
  nowCents: number;
};

function bestCallOf(portfolio: PortfolioResponse): BestCall | null {
  let best: BestCall | null = null;
  for (const p of portfolio.positions) {
    const costBasis = p.market_value_cents - p.unrealized_pnl_cents;
    if (costBasis <= 0) continue;
    const gainPct = (p.unrealized_pnl_cents / costBasis) * 100;
    if (!best || gainPct > best.gainPct) {
      best = {
        name: p.artist_name,
        slug: p.artist_slug,
        gainPct,
        boughtCents: p.avg_cost_cents,
        nowCents: p.spot_price_cents,
      };
    }
  }
  return best;
}

export default function PortfolioPage() {
  const me = useMe();
  const loggedIn = !!me.data;
  const portfolio = usePortfolio(loggedIn);
  const history = usePortfolioHistory(loggedIn);
  const scout = useScoutLeaderboard();
  const [renameOpen, setRenameOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  if (me.isLoading) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-44 w-full rounded-2xl" />
      </div>
    );
  }
  if (!me.data) {
    return (
      <div className="text-muted-foreground mx-auto max-w-md py-16 text-center text-sm">
        <Link href="/" className="text-primary font-bold underline underline-offset-2">
          Sign in
        </Link>{" "}
        to see your portfolio.
      </div>
    );
  }

  const points = history.data ?? [];
  const todayPct =
    points.length >= 2
      ? (() => {
          const prev = points[points.length - 2].equity_cents;
          const last = points[points.length - 1].equity_cents;
          return prev === 0 ? null : ((last - prev) / prev) * 100;
        })()
      : null;

  const best = portfolio.data ? bestCallOf(portfolio.data) : null;
  const invested = portfolio.data ? portfolio.data.equity_cents - portfolio.data.cash_cents : 0;

  const shareData: ShareCardData | null =
    best && portfolio.data
      ? {
          username: me.data.username,
          best,
          equityCents: portfolio.data.equity_cents,
          todayPct,
          scoutRank: scout.data?.you?.rank ?? null,
        }
      : null;

  return (
    <div className="animate-rise-in mx-auto flex max-w-2xl flex-col gap-5">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-bold sm:text-3xl">Portfolio</h1>
        <button
          type="button"
          onClick={() => setRenameOpen(true)}
          className="press border-border text-muted-foreground hover:text-foreground flex items-center gap-2 rounded-full border py-1.5 pr-3.5 pl-1.5 text-xs font-bold"
        >
          <Avatar seed={me.data.username} entity="user" size={24} />@{me.data.username}
        </button>
      </div>
      <RenameUsernameDialog
        currentUsername={me.data.username}
        open={renameOpen}
        onOpenChange={setRenameOpen}
      />

      {history.isLoading ? (
        <Skeleton className="h-44 w-full rounded-2xl" />
      ) : (
        <PortfolioValueChart points={points} />
      )}

      {portfolio.isLoading && <Skeleton className="h-20 w-full rounded-2xl" />}
      {portfolio.isError && (
        <p className="text-destructive text-sm">Couldn&apos;t load your portfolio — try again.</p>
      )}

      {portfolio.data && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div className="border-border bg-card rounded-2xl border p-4">
              <p className="text-faint text-xs">Cash</p>
              <p className="font-mono text-lg font-bold tabular-nums">
                {formatCents(portfolio.data.cash_cents)}
              </p>
            </div>
            <div className="border-border bg-card rounded-2xl border p-4">
              <p className="text-faint text-xs">Invested</p>
              <p className="font-mono text-lg font-bold tabular-nums">{formatCents(invested)}</p>
            </div>
          </div>

          {best && best.gainPct > 0 && shareData && (
            <div className="border-violet bg-violet-soft flex items-center gap-3 rounded-2xl border p-4">
              <Avatar seed={best.slug} entity="artist" size={40} />
              <div className="min-w-0 flex-1">
                <p className="text-violet flex items-center gap-1 font-mono text-[0.62rem] font-bold tracking-wide uppercase">
                  <SparkIcon /> Your best call
                </p>
                <p className="truncate text-sm font-bold">
                  {best.name}{" "}
                  <span className="text-positive font-mono tabular-nums">
                    +{best.gainPct.toFixed(1)}%
                  </span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShareOpen(true)}
                className="press border-violet text-violet flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold"
              >
                <ShareIcon className="text-sm" /> Share
              </button>
            </div>
          )}

          <div>
            <h2 className="font-heading mb-2.5 text-base font-bold">Holdings</h2>
            {portfolio.data.positions.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No positions yet.{" "}
                <Link
                  href="/discover"
                  className="text-primary font-bold underline underline-offset-2"
                >
                  Discover an artist
                </Link>{" "}
                to make your first trade.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {portfolio.data.positions.map((p) => {
                  const up = p.unrealized_pnl_cents >= 0;
                  return (
                    <Link
                      key={p.artist_slug}
                      href={`/artist?slug=${encodeURIComponent(p.artist_slug)}`}
                      className="press border-border bg-card hover:border-border-strong flex items-center gap-3 rounded-2xl border p-3.5"
                    >
                      <Avatar seed={p.artist_slug} entity="artist" size={38} />
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-bold">{p.artist_name}</span>
                        <span className="text-faint font-mono text-[0.7rem] tabular-nums">
                          {p.shares} share{p.shares === 1 ? "" : "s"} · avg cost{" "}
                          {formatCents(p.avg_cost_cents)}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="block font-mono text-sm font-bold tabular-nums">
                          {formatCents(p.market_value_cents)}
                        </span>
                        <span
                          className={cn(
                            "font-mono text-[0.7rem] font-bold tabular-nums",
                            up ? "text-positive" : "text-destructive",
                          )}
                        >
                          {up ? "+" : ""}
                          {formatCents(p.unrealized_pnl_cents)}
                        </span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {shareOpen && shareData && <ShareCard data={shareData} onClose={() => setShareOpen(false)} />}
    </div>
  );
}
