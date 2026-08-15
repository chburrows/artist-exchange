"use client";

import { useMemo, useState } from "react";

import { ArtistCard } from "@/components/ArtistCard";
import { Skeleton } from "@/components/ui/skeleton";
import { SearchIcon } from "@/components/icons";
import type { ArtistOut } from "@/lib/queries";
import { useArtists } from "@/lib/queries";
import { cn } from "@/lib/utils";

// Discovery feeds are not separate endpoints (ARCHITECTURE.md) -- derive
// them client-side by sorting/filtering the same `/artists` list.
const SORTS = [
  { id: "movers", label: "Movers" },
  { id: "under10", label: "Under $10" },
  { id: "new", label: "New" },
  { id: "az", label: "A–Z" },
] as const;

type SortId = (typeof SORTS)[number]["id"];

const TIERS = [
  { id: undefined, label: "All" },
  { id: "growth", label: "Growth" },
  { id: "blue_chip", label: "Blue chip" },
] as const;

function applySort(artists: ArtistOut[], sort: SortId): ArtistOut[] {
  switch (sort) {
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
    case "az":
      return [...artists].sort((a, b) => a.name.localeCompare(b.name));
    default:
      return artists;
  }
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "press min-h-9 rounded-full border px-3.5 py-1.5 text-xs font-bold whitespace-nowrap transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export default function DiscoverPage() {
  const [sort, setSort] = useState<SortId>("movers");
  const [tier, setTier] = useState<string | undefined>(undefined);
  const [query, setQuery] = useState("");
  const artists = useArtists(tier);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? (artists.data ?? []).filter((a) => a.name.toLowerCase().includes(q))
      : (artists.data ?? []);
    return applySort(filtered, sort);
  }, [artists.data, sort, query]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <h1 className="font-heading text-2xl font-bold sm:text-3xl">Discover</h1>

      <div className="relative">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-base" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search artists…"
          aria-label="Search artists"
          className="border-input bg-card placeholder:text-muted-foreground focus-visible:ring-ring h-11 w-full rounded-xl border pr-4 pl-10 text-sm outline-none focus-visible:ring-2"
        />
      </div>

      <div className="no-scrollbar flex items-center gap-2 overflow-x-auto">
        {TIERS.map((t) => (
          <Chip key={t.label} active={tier === t.id} onClick={() => setTier(t.id)}>
            {t.label}
          </Chip>
        ))}
        <span className="bg-border mx-1 h-5 w-px shrink-0" />
        {SORTS.map((s) => (
          <Chip key={s.id} active={sort === s.id} onClick={() => setSort(s.id)}>
            {s.label}
          </Chip>
        ))}
      </div>

      {artists.isError && (
        <p className="text-destructive text-sm">Couldn&apos;t load artists — try again.</p>
      )}
      {artists.data && rows.length === 0 && (
        <p className="text-muted-foreground py-8 text-center text-sm">
          {query ? `No artists match “${query}”.` : "No artists match this filter right now."}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {artists.isLoading
          ? Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-[124px] w-full rounded-2xl" />
            ))
          : rows.map((artist) => (
              <ArtistCard key={artist.slug} artist={artist} className="w-full" />
            ))}
      </div>
    </div>
  );
}
