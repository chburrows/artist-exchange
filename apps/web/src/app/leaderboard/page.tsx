"use client";

import { useState } from "react";

import { LeaderboardRow } from "@/components/LeaderboardRow";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatPct, pctChange } from "@/lib/format";
import { MOCK_PORTFOLIO_LEADERBOARD, MOCK_SCOUT_LEADERBOARD } from "@/lib/mock-discovery";
import { useMe, usePortfolio } from "@/lib/queries";

/** Both tabs are illustrative placeholders (PLAN.md: leaderboards are a
 * Phase 6 nightly materialized view) -- "you" is spliced in using your
 * real portfolio return where that's cheaply available, at a fixed
 * illustrative rank, rather than fabricating a rank too. */
export default function LeaderboardPage() {
  const [tab, setTab] = useState<"portfolio" | "scout">("portfolio");
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);

  const portfolioRows = [...MOCK_PORTFOLIO_LEADERBOARD];
  if (me.data && portfolio.data) {
    const costBasis = portfolio.data.positions.reduce((s, p) => s + p.avg_cost_cents * p.shares, 0);
    const gain = portfolio.data.positions.reduce(
      (s, p) => s + p.unrealized_pnl_cents + p.realized_pnl_cents,
      0,
    );
    const pct = costBasis > 0 ? pctChange(costBasis, costBasis + gain) : 0;
    portfolioRows.splice(3, 0, {
      rank: 4,
      user: me.data.username,
      stat: formatPct(pct),
      isYou: true,
    });
    portfolioRows.forEach((r, i) => (r.rank = i + 1));
  }

  return (
    <div className="flex flex-col gap-4 pb-6">
      <Tabs value={tab} onValueChange={(v) => setTab(v as "portfolio" | "scout")}>
        <TabsList>
          <TabsTrigger value="portfolio">Portfolio return</TabsTrigger>
          <TabsTrigger value="scout">Talent Scout</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="flex flex-col gap-1.5">
        {(tab === "portfolio" ? portfolioRows : MOCK_SCOUT_LEADERBOARD).map((row) => (
          <LeaderboardRow key={row.rank} row={row} />
        ))}
      </div>
    </div>
  );
}
