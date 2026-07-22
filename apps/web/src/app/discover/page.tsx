"use client";

import Link from "next/link";
import { useState } from "react";

import { ArtistAvatar } from "@/components/ArtistAvatar";
import { ArtistCard } from "@/components/ArtistCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { formatCents, formatPct } from "@/lib/format";
import { type ArtistOut, useArtists } from "@/lib/queries";

const PAGE_SIZE = 8;

/** `daily_change_pct` is null only if `price_history` somehow has zero
 * rows for a listed artist, which never happens in practice (CLAUDE.md:
 * a listed artist always has at least one row, written at listing) --
 * falls back to 0 (flat) rather than hiding the artist from every feed
 * that sorts by movement. */
function withChange(artists: ArtistOut[]) {
  return artists.map((a) => ({ ...a, changePct: a.daily_change_pct ?? 0 }));
}

function updatedLabel(dataUpdatedAt: number): string {
  if (!dataUpdatedAt) return "";
  const minutes = Math.round((Date.now() - dataUpdatedAt) / 60_000);
  return minutes < 1 ? "Updated just now" : `Updated ${minutes}m ago`;
}

export default function DiscoverPage() {
  const artists = useArtists();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  if (artists.isLoading) {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading artists…</p>;
  }
  if (artists.isError || !artists.data) {
    return <p className="py-10 text-center text-sm text-destructive">Couldn&apos;t load artists.</p>;
  }

  const growth = withChange(artists.data.filter((a) => a.tier === "growth"));
  const blueChip = artists.data.filter((a) => a.tier === "blue_chip");
  const biggestMovers = [...growth].sort((a, b) => b.changePct - a.changePct).slice(0, 6);
  const underTen = [...growth]
    .filter((a) => a.spot_price_cents < 1000)
    .sort((a, b) => b.changePct - a.changePct)
    .slice(0, 6);
  const newListings = [...artists.data]
    .sort((a, b) => new Date(b.listed_at).getTime() - new Date(a.listed_at).getTime())
    .slice(0, 5);
  const blueChipRoster = [...blueChip].sort((a, b) => b.spot_price_cents - a.spot_price_cents).slice(0, 5);
  const topMover = biggestMovers[0];

  const allWithChange = withChange(artists.data);
  const term = search.trim().toLowerCase();
  const filtered = term ? allWithChange.filter((a) => a.name.toLowerCase().includes(term)) : allWithChange;
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const pageItems = filtered.slice(currentPage * PAGE_SIZE, currentPage * PAGE_SIZE + PAGE_SIZE);
  const isFirstPage = currentPage === 0;
  const isLastPage = currentPage === totalPages - 1;

  return (
    <div className="flex flex-col gap-8 pb-6">
      <div>
        <h1 className="text-xl font-extrabold sm:text-2xl">Scout your next call</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Small caps move fast. Find them before the index does.
        </p>
      </div>

      {topMover && (
        <Link
          href={`/artist?slug=${topMover.slug}`}
          className="flex items-center justify-between rounded-2xl border border-border bg-card p-4 transition-colors hover:border-primary/50 sm:p-5"
        >
          <div className="flex items-center gap-3.5">
            <ArtistAvatar slug={topMover.slug} tier={topMover.tier as "growth"} size={48} />
            <div>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="rounded-full bg-primary px-2 py-0.5 text-[10px] font-extrabold text-primary-foreground">
                  HOT
                </span>
                <span className="text-sm font-bold sm:text-base">{topMover.name}</span>
              </div>
              <div className="text-xs text-muted-foreground">Biggest mover today</div>
            </div>
          </div>
          <div className="text-lg font-extrabold text-positive sm:text-2xl">
            {formatPct(topMover.changePct)}
          </div>
        </Link>
      )}

      <Section title="Biggest movers">
        {biggestMovers.map((a) => (
          <ArtistCard
            key={a.slug}
            slug={a.slug}
            name={a.name}
            tier={a.tier as "growth"}
            priceCents={a.spot_price_cents}
            changePct={a.changePct}
          />
        ))}
      </Section>

      <Section title="Fastest growing · under $10">
        {underTen.map((a) => (
          <ArtistCard
            key={a.slug}
            slug={a.slug}
            name={a.name}
            tier={a.tier as "growth"}
            priceCents={a.spot_price_cents}
            changePct={a.changePct}
            size="sm"
          />
        ))}
      </Section>

      <div className="grid grid-cols-1 gap-8 sm:grid-cols-2">
        <div>
          <h2 className="mb-2.5 text-xs font-bold tracking-wide text-muted-foreground uppercase">
            New listings
          </h2>
          {newListings.map((a) => (
            <Link
              key={a.slug}
              href={`/artist?slug=${a.slug}`}
              className="flex items-center gap-3 border-b border-border py-2.5 last:border-0"
            >
              <ArtistAvatar slug={a.slug} tier={a.tier as "growth" | "blue_chip"} size={32} />
              <span className="flex-1 truncate text-sm font-bold">{a.name}</span>
              <span className="rounded-full bg-secondary px-2.5 py-1 text-[11px] font-bold text-muted-foreground">
                just listed
              </span>
            </Link>
          ))}
        </div>
        <div>
          <h2 className="mb-2.5 text-xs font-bold tracking-wide text-muted-foreground uppercase">
            Blue chip
          </h2>
          {blueChipRoster.map((a) => (
            <Link
              key={a.slug}
              href={`/artist?slug=${a.slug}`}
              className="flex items-center gap-3 border-b border-border py-2.5 last:border-0"
            >
              <ArtistAvatar slug={a.slug} tier="blue_chip" size={32} />
              <span className="flex-1 truncate text-sm font-bold">{a.name}</span>
              <span className="text-sm font-bold tabular-nums">{formatCents(a.spot_price_cents)}</span>
            </Link>
          ))}
        </div>
      </div>

      <div className="border-t border-border pt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-bold tracking-wide text-muted-foreground uppercase">
            Browse all artists
          </h2>
          <div className="flex items-center gap-2.5">
            <span className="text-[11px] text-muted-foreground">
              {updatedLabel(artists.dataUpdatedAt)}
            </span>
            <Button variant="outline" size="sm" onClick={() => artists.refetch()}>
              <span className={cn("inline-block", artists.isFetching && "animate-spin")}>↻</span>{" "}
              Refresh
            </Button>
          </div>
        </div>

        <div className="relative mb-4">
          <span className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-sm text-muted-foreground">
            ⌕
          </span>
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            placeholder="Search by artist…"
            className="pl-9"
          />
        </div>

        {pageItems.length > 0 ? (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {pageItems.map((a) => (
              <ArtistCard
                key={a.slug}
                slug={a.slug}
                name={a.name}
                tier={a.tier as "growth" | "blue_chip"}
                priceCents={a.spot_price_cents}
                changePct={a.changePct}
                size="sm"
              />
            ))}
          </div>
        ) : (
          <p className="py-9 text-center text-sm text-muted-foreground">
            No artists match &quot;{search}&quot;
          </p>
        )}

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Page {currentPage + 1} of {totalPages} · {filtered.length} artists
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={isFirstPage}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              ← Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={isLastPage}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            >
              Next →
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="mb-2.5 text-xs font-bold tracking-wide text-muted-foreground uppercase">
        {title}
      </h2>
      <div className="flex gap-3 overflow-x-auto pb-1 sm:grid sm:grid-cols-3 sm:overflow-visible lg:grid-cols-6">
        {children}
      </div>
    </div>
  );
}
