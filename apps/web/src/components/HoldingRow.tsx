import Link from "next/link";

import { ArtistAvatar } from "@/components/ArtistAvatar";
import { formatCents, formatPct, pctChange } from "@/lib/format";
import type { PortfolioPosition } from "@/lib/queries";

export function HoldingRow({ position }: { position: PortfolioPosition }) {
  const costCents = position.avg_cost_cents * position.shares;
  const gainPct = pctChange(costCents, position.market_value_cents);
  const positive = position.unrealized_pnl_cents >= 0;

  return (
    <Link
      href={`/artist?slug=${position.artist_slug}`}
      className="flex items-center gap-3 border-b border-border py-3 last:border-0"
    >
      <ArtistAvatar slug={position.artist_slug} size={32} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-bold">{position.artist_name}</div>
        <div className="text-xs text-muted-foreground">
          {position.shares} sh · avg {formatCents(position.avg_cost_cents)}
        </div>
      </div>
      <div className="text-right">
        <div className="text-sm font-bold tabular-nums">{formatCents(position.market_value_cents)}</div>
        <div className={`text-xs font-bold ${positive ? "text-positive" : "text-destructive"}`}>
          {formatPct(gainPct, 0)}
        </div>
      </div>
    </Link>
  );
}
