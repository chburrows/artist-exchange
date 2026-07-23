"use client";

import { useState } from "react";

import { formatBps } from "@/lib/format";
import { usePortfolioLeaderboard, useScoutLeaderboard } from "@/lib/queries";

const TABS = [
  { id: "portfolio", label: "Portfolio return" },
  { id: "scout", label: "Talent Scout" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function RankBadge({ rank }: { rank: number }) {
  return <span className="w-6 shrink-0 text-xs font-bold text-muted-foreground">#{rank}</span>;
}

function PortfolioTable() {
  const board = usePortfolioLeaderboard();

  if (board.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (board.isError) return <p className="text-sm text-destructive">Couldn&apos;t load the leaderboard.</p>;
  if (!board.data || board.data.as_of_date === null) {
    return <p className="text-sm text-muted-foreground">No nightly snapshot has run yet — check back tomorrow.</p>;
  }

  const { rows, you } = board.data;
  const showYouSeparately = you !== null && !rows.some((r) => r.is_you);

  return (
    <div className="flex flex-col">
      {rows.map((row) => (
        <div
          key={row.rank}
          className={`flex min-h-11 items-center gap-3 border-b border-border py-2 last:border-b-0 ${row.is_you ? "font-bold" : ""}`}
        >
          <RankBadge rank={row.rank} />
          <span className="flex-1 text-sm">{row.username}</span>
          <span className={`text-sm font-bold ${row.return_bps >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatBps(row.return_bps)}
          </span>
        </div>
      ))}
      {showYouSeparately && you && (
        <div className="mt-1 flex min-h-11 items-center gap-3 border-t-2 border-dashed border-border pt-2 font-bold">
          <RankBadge rank={you.rank} />
          <span className="flex-1 text-sm">{you.username} (you)</span>
          <span className={`text-sm font-bold ${you.return_bps >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatBps(you.return_bps)}
          </span>
        </div>
      )}
    </div>
  );
}

function ScoutTable() {
  const board = useScoutLeaderboard();

  if (board.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (board.isError) return <p className="text-sm text-destructive">Couldn&apos;t load the leaderboard.</p>;
  if (!board.data || board.data.as_of_date === null) {
    return <p className="text-sm text-muted-foreground">No nightly snapshot has run yet — check back tomorrow.</p>;
  }

  const { rows, you } = board.data;
  const showYouSeparately = you !== null && !rows.some((r) => r.is_you);

  return (
    <div className="flex flex-col">
      {rows.map((row) => (
        <div
          key={row.rank}
          className={`flex min-h-11 items-center gap-3 border-b border-border py-2 last:border-b-0 ${row.is_you ? "font-bold" : ""}`}
        >
          <RankBadge rank={row.rank} />
          <div className="flex flex-1 flex-col">
            <span className="text-sm">{row.username}</span>
            <span className="text-xs text-muted-foreground">{row.artist_name}</span>
          </div>
          <span className={`text-sm font-bold ${row.return_bps >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatBps(row.return_bps)}
          </span>
        </div>
      ))}
      {showYouSeparately && you && (
        <div className="mt-1 flex min-h-11 items-center gap-3 border-t-2 border-dashed border-border pt-2 font-bold">
          <RankBadge rank={you.rank} />
          <div className="flex flex-1 flex-col">
            <span className="text-sm">{you.username} (you)</span>
            <span className="text-xs text-muted-foreground">{you.artist_name}</span>
          </div>
          <span className={`text-sm font-bold ${you.return_bps >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatBps(you.return_bps)}
          </span>
        </div>
      )}
    </div>
  );
}

export default function LeaderboardPage() {
  const [tab, setTab] = useState<TabId>("portfolio");

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <h1 className="text-2xl font-bold">Leaderboard</h1>

      <div className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`min-h-9 rounded-full border border-border px-3 text-xs font-bold ${
              tab === t.id ? "bg-primary text-primary-foreground" : "text-muted-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "portfolio" ? <PortfolioTable /> : <ScoutTable />}
    </div>
  );
}
