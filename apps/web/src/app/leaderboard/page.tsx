"use client";

import { useState } from "react";

import { LeaderboardRow, type LeaderboardRowData } from "@/components/LeaderboardRow";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCents, formatPct } from "@/lib/format";
import {
  type PortfolioLeaderboardRow,
  type ScoutLeaderboardRow,
  usePortfolioLeaderboard,
  useScoutLeaderboard,
} from "@/lib/queries";

function toPortfolioRow(row: PortfolioLeaderboardRow): LeaderboardRowData {
  const pct = row.return_bps / 100;
  return {
    rank: row.rank,
    username: row.username,
    statText: formatPct(pct),
    statValue: pct,
    isYou: row.is_you,
  };
}

function toScoutRow(row: ScoutLeaderboardRow): LeaderboardRowData {
  const pct = row.return_bps / 100;
  return {
    rank: row.rank,
    username: row.username,
    statText: formatPct(pct),
    statValue: pct,
    note: `Found ${row.artist_name} at ${formatCents(row.entry_price_cents)}`,
    isYou: row.is_you,
  };
}

/** Both rankings come straight from `jobs/leaderboard.py`'s nightly
 * snapshot (PLAN.md Phase 6) -- up to a day stale by design ("the one
 * place staleness is genuinely fine"), never computed live. `you` is
 * spliced in by the backend itself (keyed off the session cookie), even
 * when it falls outside the top slice `rows` returns. */
export default function LeaderboardPage() {
  const [tab, setTab] = useState<"portfolio" | "scout">("portfolio");
  const portfolio = usePortfolioLeaderboard();
  const scout = useScoutLeaderboard();

  const active = tab === "portfolio" ? portfolio : scout;

  return (
    <div className="flex flex-col gap-4 pb-6">
      <Tabs value={tab} onValueChange={(v) => setTab(v as "portfolio" | "scout")}>
        <TabsList>
          <TabsTrigger value="portfolio">Portfolio return</TabsTrigger>
          <TabsTrigger value="scout">Talent Scout</TabsTrigger>
        </TabsList>
      </Tabs>

      {active.isLoading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
      ) : active.isError || !active.data ? (
        <p className="py-10 text-center text-sm text-destructive">Couldn&apos;t load the leaderboard.</p>
      ) : active.data.as_of_date === null ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No rankings yet -- check back after tonight&apos;s update.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {tab === "portfolio"
            ? (portfolio.data!.rows as PortfolioLeaderboardRow[]).map((row) => (
                <LeaderboardRow key={row.rank} row={toPortfolioRow(row)} />
              ))
            : (scout.data!.rows as ScoutLeaderboardRow[]).map((row) => (
                <LeaderboardRow key={row.rank} row={toScoutRow(row)} />
              ))}
          {active.data.you && active.data.rows.every((r) => !r.is_you) && (
            <>
              <div className="my-1 border-t border-dashed border-border" />
              {tab === "portfolio" ? (
                <LeaderboardRow row={toPortfolioRow(active.data.you as PortfolioLeaderboardRow)} />
              ) : (
                <LeaderboardRow row={toScoutRow(active.data.you as ScoutLeaderboardRow)} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
