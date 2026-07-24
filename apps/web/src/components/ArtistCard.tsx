import Link from "next/link";

import { Avatar } from "@/components/Avatar";
import { ChangeBadge } from "@/components/ChangeBadge";
import { Sparkline } from "@/components/Sparkline";
import { directionOf, tierLabel } from "@/lib/artist";
import { formatCents } from "@/lib/format";
import type { ArtistOut } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** A tappable artist tile for the Home rails and Discover grid.
 *
 * Rendered as an anchor to `/artist?slug=` (not a button) so it stays a
 * real link, and the artist name is the first `<span>` in the tile --
 * both relied on by the discover e2e flow. */
export function ArtistCard({ artist, className }: { artist: ArtistOut; className?: string }) {
  const direction = directionOf(artist.daily_change_pct);

  return (
    <Link
      href={`/artist?slug=${encodeURIComponent(artist.slug)}`}
      className={cn(
        "press group flex w-[160px] shrink-0 flex-col gap-2.5 rounded-2xl border border-border bg-card p-3.5",
        "hover:border-border-strong focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
        className,
      )}
    >
      <div className="flex items-center gap-2.5">
        <Avatar seed={artist.slug} entity="artist" size={32} />
        <div className="min-w-0">
          <span className="block truncate text-[0.8rem] font-semibold">{artist.name}</span>
          <span className="text-faint block truncate text-[0.68rem]">{tierLabel(artist.tier)}</span>
        </div>
      </div>

      <Sparkline seed={artist.slug} direction={direction} />

      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[0.85rem] font-bold tabular-nums">
          {formatCents(artist.spot_price_cents)}
        </span>
        <ChangeBadge pct={artist.daily_change_pct} />
      </div>
    </Link>
  );
}
