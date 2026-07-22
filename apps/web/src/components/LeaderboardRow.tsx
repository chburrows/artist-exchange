import { avatarStyle } from "@/lib/avatar";
import { cn } from "@/lib/utils";

export interface LeaderboardRowData {
  rank: number;
  username: string;
  statText: string;
  /** Numeric form of `statText` -- only its sign is used, to color it. */
  statValue: number;
  note?: string;
  isYou?: boolean;
}

export function LeaderboardRow({ row }: { row: LeaderboardRowData }) {
  return (
    <div
      className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5", row.isYou && "bg-secondary")}
    >
      <span className="w-5 shrink-0 text-sm font-extrabold text-muted-foreground">{row.rank}</span>
      <div
        aria-hidden
        className="h-8 w-8 shrink-0 rounded-full"
        style={{
          ...avatarStyle(row.username),
          boxShadow: row.isYou ? "0 0 0 2px var(--primary)" : undefined,
        }}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-bold">
          {row.username}
          {row.isYou && <span className="ml-1.5 text-xs font-medium text-muted-foreground">(you)</span>}
        </div>
        {row.note && <div className="truncate text-xs text-muted-foreground">{row.note}</div>}
      </div>
      <div
        className={cn(
          "shrink-0 text-sm font-extrabold",
          row.statValue < 0 ? "text-destructive" : "text-positive",
        )}
      >
        {row.statText}
      </div>
    </div>
  );
}
