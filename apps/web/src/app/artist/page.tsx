"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PriceChart } from "@/components/PriceChart";
import { TradeTicket } from "@/components/TradeTicket";
import { formatCents, formatPct } from "@/lib/format";
import { useArtistHistory, useMe } from "@/lib/queries";

// Not a dynamic segment: static export requires `generateStaticParams` to
// enumerate every path at build time, but the artist list is DB-driven
// and grows without a rebuild. Query-param route instead, per
// ARCHITECTURE.md.
function ArtistPageContent() {
  const searchParams = useSearchParams();
  const slug = searchParams.get("slug");
  const me = useMe();
  const history = useArtistHistory(slug);

  if (!slug) {
    return <p className="text-sm text-muted-foreground">No artist selected.</p>;
  }
  if (history.isLoading) {
    return <p className="py-16 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (history.isError || !history.data) {
    return <p className="text-sm text-destructive">Couldn&apos;t find that artist.</p>;
  }

  const { artist, points } = history.data;
  const change = artist.daily_change_pct;
  const changeClass = change === null ? "text-muted-foreground" : change >= 0 ? "text-positive" : "text-destructive";

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <div className="flex items-baseline justify-between gap-4">
          <h1 className="text-2xl font-bold">{artist.name}</h1>
          <span className="text-xs font-bold text-muted-foreground">
            {artist.tier === "blue_chip" ? "Blue chip" : "Growth"}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-3 text-sm">
          <span className="font-bold">{formatCents(artist.spot_price_cents)}</span>
          <span className={`font-bold ${changeClass}`}>{change === null ? "—" : formatPct(change)}</span>
          {artist.index_score !== null && (
            <span className="text-muted-foreground">Index score {artist.index_score.toFixed(1)}</span>
          )}
        </div>
      </div>

      <PriceChart points={points} />

      {me.data ? (
        <TradeTicket artistSlug={artist.slug} />
      ) : (
        <div className="rounded-xl border border-border p-4 text-sm text-muted-foreground">
          <Link href="/" className="font-bold text-primary underline underline-offset-2">
            Sign in
          </Link>{" "}
          to trade {artist.name}.
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {artist.name} is not affiliated with or endorsed by Artist Exchange. Prices are play money and reflect
        public popularity signals, not real-world endorsement.
      </p>
    </div>
  );
}

export default function ArtistPage() {
  return (
    <Suspense>
      <ArtistPageContent />
    </Suspense>
  );
}
