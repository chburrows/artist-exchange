import { avatarStyle } from "@/lib/avatar";
import type { MockLeaderboardRow } from "@/lib/mock-discovery";
import { cn } from "@/lib/utils";

export function LeaderboardRow({ row }: { row: MockLeaderboardRow }) {
  return (
    <div
      className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5", row.isYou && "bg-secondary")}
    >
      <span className="w-5 shrink-0 text-sm font-extrabold text-muted-foreground">{row.rank}</span>
      <div
        aria-hidden
        className="h-8 w-8 shrink-0 rounded-full"
        style={{
          ...avatarStyle(row.user),
          boxShadow: row.isYou ? "0 0 0 2px var(--primary)" : undefined,
        }}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-bold">
          {row.user}
          {row.isYou && <span className="ml-1.5 text-xs font-medium text-muted-foreground">(you)</span>}
        </div>
        {row.note && <div className="truncate text-xs text-muted-foreground">{row.note}</div>}
      </div>
      <div
        className={cn(
          "shrink-0 text-sm font-extrabold",
          row.stat.trim().startsWith("-") ? "text-destructive" : "text-positive",
        )}
      >
        {row.stat}
      </div>
    </div>
  );
}
