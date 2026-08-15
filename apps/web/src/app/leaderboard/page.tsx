"use client";

import { useState } from "react";

import { Avatar } from "@/components/Avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBps } from "@/lib/format";
import { usePortfolioLeaderboard, useScoutLeaderboard } from "@/lib/queries";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "portfolio", label: "Portfolio return" },
  { id: "scout", label: "Talent Scout" },
] as const;

type TabId = (typeof TABS)[number]["id"];

type Entry = { rank: number; username: string; statBps: number; sub?: string; isYou: boolean };

// Medal ring colors for the podium, #1 -> #3.
const RING = ["#e5c14e", "#c2c7d0", "#cd8b5a"];

function statTone(bps: number) {
  return bps >= 0 ? "text-positive" : "text-destructive";
}

function Podium({ top }: { top: Entry[] }) {
  if (top.length === 0) return null;
  // Visual podium order: 2nd, 1st, 3rd -- with #1 raised and largest.
  const order = [1, 0, 2].filter((i) => top[i]);
  return (
    <div className="border-border bg-card flex items-end justify-center gap-4 rounded-2xl border px-4 py-6 sm:gap-8">
      {order.map((i) => {
        const e = top[i];
        const first = e.rank === 1;
        return (
          <div
            key={e.rank}
            className={cn("flex flex-col items-center gap-1.5", first ? "-translate-y-2" : "")}
          >
            <Avatar
              seed={e.username}
              entity="user"
              size={first ? 68 : 52}
              ring
              ringColor={RING[e.rank - 1] ?? "var(--border-strong)"}
            />
            <span className="max-w-[84px] truncate text-xs font-bold sm:text-sm">{e.username}</span>
            <span
              className={cn(
                "font-mono text-xs font-bold tabular-nums sm:text-sm",
                statTone(e.statBps),
              )}
            >
              {formatBps(e.statBps)}
            </span>
            <span className="text-faint font-mono text-[0.65rem] font-bold tabular-nums">
              #{e.rank}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Row({ entry }: { entry: Entry }) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-2xl border px-4 py-3",
        entry.isYou ? "border-primary bg-primary-soft" : "border-border bg-card",
      )}
    >
      <span className="text-faint w-6 shrink-0 font-mono text-xs font-bold tabular-nums">
        {entry.rank}
      </span>
      <Avatar seed={entry.username} entity="user" size={32} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">
          {entry.username}
          {entry.isYou && <span className="text-primary"> (you)</span>}
        </div>
        {entry.sub && <div className="text-muted-foreground truncate text-xs">{entry.sub}</div>}
      </div>
      <span className={cn("font-mono text-sm font-bold tabular-nums", statTone(entry.statBps))}>
        {formatBps(entry.statBps)}
      </span>
    </div>
  );
}

function Board({
  entries,
  you,
  isLoading,
  isError,
  noSnapshot,
}: {
  entries: Entry[];
  you: Entry | null;
  isLoading: boolean;
  isError: boolean;
  noSnapshot: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-32 w-full rounded-2xl" />
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-2xl" />
        ))}
      </div>
    );
  }
  if (isError)
    return <p className="text-destructive text-sm">Couldn&apos;t load the leaderboard.</p>;
  if (noSnapshot) {
    return (
      <p className="text-muted-foreground text-sm">
        No nightly snapshot has run yet — check back tomorrow.
      </p>
    );
  }

  const top = entries.slice(0, 3);
  const rest = entries.slice(3);
  const showYouSeparately = you !== null && !entries.some((e) => e.isYou);

  return (
    <div className="flex flex-col gap-3">
      <Podium top={top} />
      {rest.map((e) => (
        <Row key={e.rank} entry={e} />
      ))}
      {showYouSeparately && you && (
        <div className="mt-1 border-t border-dashed border-border pt-3">
          <Row entry={you} />
        </div>
      )}
    </div>
  );
}

function PortfolioBoard() {
  const board = usePortfolioLeaderboard();
  const entries: Entry[] = (board.data?.rows ?? []).map((r) => ({
    rank: r.rank,
    username: r.username,
    statBps: r.return_bps,
    isYou: r.is_you,
  }));
  const you = board.data?.you
    ? {
        rank: board.data.you.rank,
        username: board.data.you.username,
        statBps: board.data.you.return_bps,
        isYou: true,
      }
    : null;
  return (
    <Board
      entries={entries}
      you={you}
      isLoading={board.isLoading}
      isError={board.isError}
      noSnapshot={!board.data || board.data.as_of_date === null}
    />
  );
}

function ScoutBoard() {
  const board = useScoutLeaderboard();
  const entries: Entry[] = (board.data?.rows ?? []).map((r) => ({
    rank: r.rank,
    username: r.username,
    statBps: r.return_bps,
    sub: `Called ${r.artist_name}`,
    isYou: r.is_you,
  }));
  const you = board.data?.you
    ? {
        rank: board.data.you.rank,
        username: board.data.you.username,
        statBps: board.data.you.return_bps,
        sub: `Called ${board.data.you.artist_name}`,
        isYou: true,
      }
    : null;
  return (
    <Board
      entries={entries}
      you={you}
      isLoading={board.isLoading}
      isError={board.isError}
      noSnapshot={!board.data || board.data.as_of_date === null}
    />
  );
}

export default function LeaderboardPage() {
  const [tab, setTab] = useState<TabId>("portfolio");

  return (
    <div className="animate-rise-in mx-auto flex max-w-2xl flex-col gap-5">
      <h1 className="font-heading text-2xl font-bold sm:text-3xl">Leaderboard</h1>

      <div className="bg-secondary flex gap-1 rounded-xl p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-pressed={tab === t.id}
            className={cn(
              "press min-h-10 flex-1 rounded-lg text-sm font-bold transition-colors",
              tab === t.id ? "bg-primary text-primary-foreground" : "text-muted-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "portfolio" ? <PortfolioBoard /> : <ScoutBoard />}
    </div>
  );
}
