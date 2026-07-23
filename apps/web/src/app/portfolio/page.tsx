"use client";

import Link from "next/link";
import { useState } from "react";

import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { RenameUsernameDialog } from "@/components/RenameUsernameDialog";
import { formatCents } from "@/lib/format";
import { useMe, usePortfolio, usePortfolioHistory } from "@/lib/queries";

export default function PortfolioPage() {
  const me = useMe();
  const loggedIn = !!me.data;
  const portfolio = usePortfolio(loggedIn);
  const history = usePortfolioHistory(loggedIn);
  const [renameOpen, setRenameOpen] = useState(false);

  if (me.isLoading) {
    return <p className="py-16 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (!me.data) {
    return (
      <div className="mx-auto max-w-md py-16 text-center text-sm text-muted-foreground">
        <Link href="/" className="font-bold text-primary underline underline-offset-2">
          Sign in
        </Link>{" "}
        to see your portfolio.
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <button
          type="button"
          onClick={() => setRenameOpen(true)}
          className="min-h-9 rounded-full border border-border px-3 text-xs font-bold text-muted-foreground"
        >
          @{me.data.username}
        </button>
      </div>
      <RenameUsernameDialog currentUsername={me.data.username} open={renameOpen} onOpenChange={setRenameOpen} />

      {history.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading equity history…</p>
      ) : (
        <PortfolioValueChart points={history.data ?? []} />
      )}

      {portfolio.isLoading && <p className="text-sm text-muted-foreground">Loading holdings…</p>}
      {portfolio.isError && <p className="text-sm text-destructive">Couldn&apos;t load your portfolio — try again.</p>}

      {portfolio.data && (
        <>
          <div className="flex justify-between rounded-xl border border-border p-4">
            <div>
              <p className="text-xs text-muted-foreground">Cash</p>
              <p className="text-lg font-bold">{formatCents(portfolio.data.cash_cents)}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Total equity</p>
              <p className="text-lg font-bold">{formatCents(portfolio.data.equity_cents)}</p>
            </div>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-bold">Holdings</h2>
            {portfolio.data.positions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No positions yet.{" "}
                <Link href="/discover" className="font-bold text-primary underline underline-offset-2">
                  Discover an artist
                </Link>{" "}
                to make your first trade.
              </p>
            ) : (
              <div className="flex flex-col">
                {portfolio.data.positions.map((p) => (
                  <Link
                    key={p.artist_slug}
                    href={`/artist?slug=${encodeURIComponent(p.artist_slug)}`}
                    className="flex min-h-11 items-center justify-between gap-4 border-b border-border py-3 last:border-b-0"
                  >
                    <div className="flex flex-col">
                      <span className="text-sm font-bold">{p.artist_name}</span>
                      <span className="text-xs text-muted-foreground">
                        {p.shares} share{p.shares === 1 ? "" : "s"} · avg cost {formatCents(p.avg_cost_cents)}
                      </span>
                    </div>
                    <div className="flex flex-col items-end">
                      <span className="text-sm font-bold">{formatCents(p.market_value_cents)}</span>
                      <span
                        className={`text-xs font-bold ${p.unrealized_pnl_cents >= 0 ? "text-positive" : "text-destructive"}`}
                      >
                        {p.unrealized_pnl_cents >= 0 ? "+" : ""}
                        {formatCents(p.unrealized_pnl_cents)}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
