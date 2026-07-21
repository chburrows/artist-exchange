"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ArtistAvatar } from "@/components/ArtistAvatar";
import { PriceChart } from "@/components/PriceChart";
import { TradeTicket } from "@/components/TradeTicket";
import { Badge } from "@/components/ui/badge";
import { changeSince, formatCents, formatDate, formatPct, formatPctAbs } from "@/lib/format";
import { useArtist, useArtistHistory, useMe, usePortfolio } from "@/lib/queries";

function ArtistPageContent() {
  const slug = useSearchParams().get("slug");
  const artist = useArtist(slug);
  const history = useArtistHistory(slug);
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);

  if (!slug) {
    return <p className="py-10 text-center text-sm text-muted-foreground">No artist selected.</p>;
  }
  if (artist.isLoading) {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (artist.isError || !artist.data) {
    return <p className="py-10 text-center text-sm text-destructive">Artist not found.</p>;
  }

  const a = artist.data;
  const tier = a.tier as "growth" | "blue_chip";
  const points = history.data?.points ?? [];
  const change = changeSince(points, 24);
  const position = portfolio.data?.positions.find((p) => p.artist_slug === slug);

  return (
    <div className="flex flex-col gap-6 pb-6 lg:flex-row lg:items-start lg:gap-8">
      <div className="min-w-0 flex-1">
        <Link href="/discover" className="text-sm text-muted-foreground">
          ← back
        </Link>

        <div className="mt-2 flex items-start justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <ArtistAvatar slug={a.slug} tier={tier} size={56} />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl font-extrabold sm:text-2xl">{a.name}</h1>
                <Badge>{tier === "growth" ? "Growth tier" : "Blue chip"}</Badge>
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-extrabold tabular-nums sm:text-[26px]">
              {formatCents(a.spot_price_cents)}
            </div>
            {change && (
              <div className={`text-sm font-bold ${change.pct >= 0 ? "text-positive" : "text-destructive"}`}>
                {formatPct(change.pct)} {change.sinceInception ? "(since listing)" : "(24h)"}
              </div>
            )}
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
          <PriceChart points={points} />
        </div>

        {change && (
          <div className="mt-4 rounded-xl bg-secondary p-3.5 text-sm">
            You&apos;d have found this on <b>{formatDate(change.fromIso)}</b> at{" "}
            <b>{formatCents(change.fromCents)}</b>.{" "}
            {change.pct >= 0 ? (
              <>
                Up <b className="text-positive">{formatPctAbs(change.pct)}</b> since.
              </>
            ) : (
              <>
                Down <b className="text-destructive">{formatPctAbs(change.pct)}</b> since.
              </>
            )}
          </div>
        )}

        <div className="mt-5 flex gap-6">
          <Stat label="Index score" value={a.index_score !== null ? a.index_score.toFixed(0) : "—"} />
          <Stat
            label="Fair value"
            value={a.fair_value_cents !== null ? formatCents(a.fair_value_cents) : "—"}
          />
          <Stat label="Tier" value={tier === "growth" ? "Growth" : "Blue chip"} />
        </div>

        <p className="mt-6 text-xs text-muted-foreground">
          {a.name} is not affiliated with or endorsed by Artist Exchange. Shares are play money
          only and carry no real-world value.
        </p>
      </div>

      <div className="lg:w-80 lg:shrink-0">
        {me.data ? (
          <TradeTicket artistSlug={a.slug} spotPriceCents={a.spot_price_cents} userShares={position?.shares ?? 0} />
        ) : (
          <div className="rounded-2xl border border-border bg-card p-5 text-center">
            <p className="text-sm text-muted-foreground">Sign up to start trading {a.name}.</p>
            <Link href="/" className="mt-3 inline-block text-sm font-bold text-primary">
              Get started →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-bold">{value}</div>
    </div>
  );
}

export default function ArtistPage() {
  return (
    <Suspense fallback={<p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>}>
      <ArtistPageContent />
    </Suspense>
  );
}
