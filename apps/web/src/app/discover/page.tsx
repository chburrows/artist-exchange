"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { ArtistOut } from "@/lib/queries";
import { useArtists } from "@/lib/queries";
import { formatCents, formatPct } from "@/lib/format";

// Discovery feeds are not separate endpoints (ARCHITECTURE.md) -- derive
// them client-side by sorting/filtering the same `/artists` list.
const FEEDS = [
  { id: "all", label: "All" },
  { id: "movers", label: "Biggest movers" },
  { id: "under10", label: "Fastest growing under $10" },
  { id: "new", label: "New listings" },
] as const;

type FeedId = (typeof FEEDS)[number]["id"];

function applyFeed(artists: ArtistOut[], feed: FeedId): ArtistOut[] {
  switch (feed) {
    case "movers":
      return [...artists].sort(
        (a, b) => Math.abs(b.daily_change_pct ?? 0) - Math.abs(a.daily_change_pct ?? 0),
      );
    case "under10":
      return artists
        .filter((a) => a.spot_price_cents < 1000)
        .sort((a, b) => (b.daily_change_pct ?? 0) - (a.daily_change_pct ?? 0));
    case "new":
      return [...artists].sort(
        (a, b) => new Date(b.listed_at).getTime() - new Date(a.listed_at).getTime(),
      );
    case "all":
    default:
      return artists;
  }
}

function ArtistRow({ artist }: { artist: ArtistOut }) {
  const change = artist.daily_change_pct;
  const changeClass = change === null ? "text-muted-foreground" : change >= 0 ? "text-positive" : "text-destructive";

  return (
    <Link
      href={`/artist?slug=${encodeURIComponent(artist.slug)}`}
      className="flex min-h-11 items-center justify-between gap-4 border-b border-border py-3 last:border-b-0"
    >
      <div className="flex flex-col">
        <span className="text-sm font-bold">{artist.name}</span>
        <span className="text-xs text-muted-foreground">{artist.tier === "blue_chip" ? "Blue chip" : "Growth"}</span>
      </div>
      <div className="flex flex-col items-end">
        <span className="text-sm font-bold">{formatCents(artist.spot_price_cents)}</span>
        <span className={`text-xs font-bold ${changeClass}`}>
          {change === null ? "—" : formatPct(change)}
        </span>
      </div>
    </Link>
  );
}

export default function DiscoverPage() {
  const [feed, setFeed] = useState<FeedId>("all");
  const [tier, setTier] = useState<string | undefined>(undefined);
  const artists = useArtists(tier);

  const rows = useMemo(() => applyFeed(artists.data ?? [], feed), [artists.data, feed]);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="text-2xl font-bold">Discover</h1>

      <div className="flex flex-wrap gap-2">
        {FEEDS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFeed(f.id)}
            className={`min-h-9 rounded-full border border-border px-3 text-xs font-bold ${
              feed === f.id ? "bg-primary text-primary-foreground" : "bg-transparent text-muted-foreground"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2 text-xs">
        <button
          type="button"
          onClick={() => setTier(undefined)}
          className={`min-h-9 rounded-full border border-border px-3 font-bold ${tier === undefined ? "text-foreground" : "text-muted-foreground"}`}
        >
          All tiers
        </button>
        <button
          type="button"
          onClick={() => setTier("growth")}
          className={`min-h-9 rounded-full border border-border px-3 font-bold ${tier === "growth" ? "text-foreground" : "text-muted-foreground"}`}
        >
          Growth
        </button>
        <button
          type="button"
          onClick={() => setTier("blue_chip")}
          className={`min-h-9 rounded-full border border-border px-3 font-bold ${tier === "blue_chip" ? "text-foreground" : "text-muted-foreground"}`}
        >
          Blue chip
        </button>
      </div>

      {artists.isLoading && <p className="text-sm text-muted-foreground">Loading artists…</p>}
      {artists.isError && <p className="text-sm text-destructive">Couldn&apos;t load artists — try again.</p>}
      {artists.data && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">No artists match this feed right now.</p>
      )}

      <div className="flex flex-col">
        {rows.map((artist) => (
          <ArtistRow key={artist.slug} artist={artist} />
        ))}
      </div>
    </div>
  );
}
