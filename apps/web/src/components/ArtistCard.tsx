import Link from "next/link";

import { ArtistAvatar } from "@/components/ArtistAvatar";
import { formatCents, formatPct } from "@/lib/format";

export function ArtistCard({
  slug,
  name,
  tier,
  priceCents,
  changePct,
  size = "md",
}: {
  slug: string;
  name: string;
  tier: "growth" | "blue_chip";
  priceCents: number;
  changePct?: number;
  size?: "sm" | "md";
}) {
  return (
    <Link
      href={`/artist?slug=${slug}`}
      className="flex min-w-[110px] shrink-0 flex-col gap-2.5 rounded-2xl border border-border bg-card p-3.5 transition-colors hover:border-primary/50"
    >
      <ArtistAvatar slug={slug} tier={tier} size={size === "sm" ? 32 : 40} />
      <div className="truncate text-sm font-bold">{name}</div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-bold tabular-nums">{formatCents(priceCents)}</span>
        {changePct !== undefined && (
          <span className={`text-xs font-bold ${changePct >= 0 ? "text-positive" : "text-destructive"}`}>
            {formatPct(changePct)}
          </span>
        )}
      </div>
    </Link>
  );
}
