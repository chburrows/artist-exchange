"use client";

import { useState } from "react";

import { LeaderboardRow } from "@/components/LeaderboardRow";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { formatPct, pctChange } from "@/lib/format";
import { MOCK_PORTFOLIO_LEADERBOARD, MOCK_SCOUT_LEADERBOARD } from "@/lib/mock-discovery";
import { useMe, usePortfolio } from "@/lib/queries";

/** Both tabs are illustrative placeholders (PLAN.md: leaderboards are a
 * Phase 6 nightly materialized view) -- "you" is spliced in using your
 * real portfolio return where that's cheaply available, ranked by that
 * value against the mock rows' own stats rather than at a fixed rank.
 * The mock rows carry `isMock` so they render a "(sample)" tag and are
 * never mistaken for real traders. */
export default function LeaderboardPage() {
  const [tab, setTab] = useState<"portfolio" | "scout">("portfolio");
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);

  // .map(), not [...MOCK_PORTFOLIO_LEADERBOARD] -- a shallow copy still
  // shares row objects with the module-level export, so mutating `.rank`
  // below would corrupt the shared mock data for every future render.
  const portfolioRows = MOCK_PORTFOLIO_LEADERBOARD.map((row) => ({ ...row }));
  if (me.data && portfolio.data) {
    const pct = pctChange(STARTING_BALANCE_CENTS, portfolio.data.equity_cents);
    const insertAt = portfolioRows.findIndex((row) => row.pctValue < pct);
    portfolioRows.splice(insertAt === -1 ? portfolioRows.length : insertAt, 0, {
      rank: 0,
      user: me.data.username,
      stat: formatPct(pct),
      pctValue: pct,
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
