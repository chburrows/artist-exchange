"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Avatar } from "@/components/Avatar";
import { ChangeBadge } from "@/components/ChangeBadge";
import { PriceChart } from "@/components/PriceChart";
import { TradeTicket } from "@/components/TradeTicket";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowLeftIcon } from "@/components/icons";
import { tierLabel } from "@/lib/artist";
import { formatCents } from "@/lib/format";
import { useArtistHistory, useMe } from "@/lib/queries";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-border flex items-center justify-between border-t py-3">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="font-mono text-sm font-semibold tabular-nums">{value}</span>
    </div>
  );
}

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
    return <p className="text-muted-foreground text-sm">No artist selected.</p>;
  }
  if (history.isLoading) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-14 w-14 rounded-2xl" />
        <Skeleton className="h-56 w-full rounded-2xl" />
      </div>
    );
  }
  if (history.isError || !history.data) {
    return <p className="text-destructive text-sm">Couldn&apos;t find that artist.</p>;
  }

  const { artist, points } = history.data;
  const spot = artist.spot_price_cents;
  const fairCents = [...points].reverse().find((p) => p.fair_value_cents !== null)?.fair_value_cents ?? null;
  const divergencePct = fairCents !== null && spot > 0 ? ((fairCents - spot) / spot) * 100 : null;

  return (
    <div className="animate-rise-in mx-auto flex max-w-4xl flex-col gap-5">
      <Link
        href="/discover"
        className="text-muted-foreground hover:text-foreground -mb-1 flex w-fit items-center gap-1.5 text-sm font-semibold"
      >
        <ArrowLeftIcon className="text-base" /> Discover
      </Link>

      <div className="flex items-center gap-4">
        <Avatar seed={artist.slug} entity="artist" size={56} />
        <div className="min-w-0">
          <h1 className="font-heading truncate text-2xl font-bold">{artist.name}</h1>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-violet bg-violet-soft rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold">
              {tierLabel(artist.tier)}
            </span>
            {artist.index_score !== null && (
              <span className="text-faint text-xs">Index score {artist.index_score.toFixed(1)}</span>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-baseline gap-3">
        <span className="font-heading text-4xl font-bold tabular-nums">{formatCents(spot)}</span>
        <ChangeBadge pct={artist.daily_change_pct} size="md" />
      </div>

      <div className="md:grid md:grid-cols-[1fr_320px] md:items-start md:gap-6">
        <div className="flex flex-col gap-4">
          <PriceChart points={points} />

          {divergencePct !== null && (
            <div className="border-violet bg-violet-soft text-violet flex items-center gap-2 rounded-2xl border px-4 py-3 text-sm font-semibold">
              <span className="bg-violet size-2 shrink-0 rounded-full" />
              {divergencePct >= 0
                ? `Trading ${divergencePct.toFixed(0)}% below fair value`
                : `Trading ${Math.abs(divergencePct).toFixed(0)}% above fair value`}
            </div>
          )}

          <div className="border-border bg-card rounded-2xl border px-4 pb-1">
            {fairCents !== null && <Stat label="Fair-value index" value={formatCents(fairCents)} />}
            <Stat label="Shares outstanding" value={artist.net_supply.toLocaleString()} />
            {artist.index_score !== null && (
              <Stat label="Index score" value={artist.index_score.toFixed(1)} />
            )}
          </div>

          <p className="text-faint text-xs leading-relaxed">
            {artist.name} is not affiliated with or endorsed by Artist Exchange. Prices are play money and
            reflect public popularity signals, not real-world endorsement.
          </p>
        </div>

        <div className="mt-4 md:sticky md:top-24 md:mt-0">
          {me.data ? (
            <TradeTicket artistSlug={artist.slug} spotPriceCents={spot} />
          ) : (
            <div className="border-border bg-card text-muted-foreground rounded-2xl border p-5 text-sm">
              <Link href="/" className="text-primary font-bold underline underline-offset-2">
                Sign in
              </Link>{" "}
              to trade {artist.name}.
            </div>
          )}
        </div>
      </div>
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
