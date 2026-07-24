"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Avatar } from "@/components/Avatar";
import { PriceChart } from "@/components/PriceChart";
import { TradeTicket } from "@/components/TradeTicket";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowLeftIcon, ChevronDownIcon } from "@/components/icons";
import { tierLabel } from "@/lib/artist";
import { formatCents } from "@/lib/format";
import { useArtistHistory, useMe } from "@/lib/queries";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border-border flex items-center justify-between border-t py-3">
      <span
        title={hint}
        className={cn(
          "text-muted-foreground text-sm",
          hint && "cursor-help underline decoration-dotted underline-offset-2",
        )}
      >
        {label}
      </span>
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

      <div className="flex items-center gap-3">
        <Avatar seed={artist.slug} entity="artist" size={44} />
        <div className="min-w-0">
          <h1 className="font-heading truncate text-xl font-bold">{artist.name}</h1>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="text-violet bg-violet-soft rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold">
              {tierLabel(artist.tier)}
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 md:grid md:grid-cols-[1fr_320px] md:items-start md:gap-6">
        <div className="md:col-start-1 md:row-start-1">
          <PriceChart points={points} spotPriceCents={spot} />
        </div>

        <div className="md:sticky md:top-24 md:col-start-2 md:row-start-1">
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

        <div className="flex flex-col gap-4 md:col-start-1 md:row-start-2">
          {divergencePct !== null && (
            <div className="border-violet bg-violet-soft text-violet flex items-center gap-2 rounded-2xl border px-4 py-3 text-sm font-semibold">
              <span className="bg-violet size-2 shrink-0 rounded-full" />
              {divergencePct >= 0
                ? `Trading ${divergencePct.toFixed(0)}% below fair value`
                : `Trading ${Math.abs(divergencePct).toFixed(0)}% above fair value`}
            </div>
          )}

          <details className="group border-border bg-card rounded-2xl border px-4">
            <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center justify-between py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
              Details
              <ChevronDownIcon className="transition-transform duration-200 group-open:rotate-180" />
            </summary>
            <div className="pb-1">
              {fairCents !== null && (
                <Stat
                  label="Fair-value index"
                  value={formatCents(fairCents)}
                  hint="Derived from real-world popularity data, recomputed nightly. Not a live trading price — market price glides toward this value over time."
                />
              )}
              <Stat label="Shares outstanding" value={artist.net_supply.toLocaleString()} />
              {artist.index_score !== null && (
                <Stat label="Index score" value={artist.index_score.toFixed(1)} />
              )}
            </div>
          </details>

          <p className="text-faint text-xs leading-relaxed">
            {artist.name} is not affiliated with or endorsed by Artist Exchange. Prices are play money and
            reflect public popularity signals, not real-world endorsement.
          </p>
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
