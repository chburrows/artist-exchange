"use client";

import Link from "next/link";

import { ArtistCard } from "@/components/ArtistCard";
import { Avatar } from "@/components/Avatar";
import { OnboardingScreen } from "@/components/OnboardingScreen";
import { PortfolioValueChart } from "@/components/PortfolioValueChart";
import { Skeleton } from "@/components/ui/skeleton";
import { CompassIcon, SparkIcon, TrophyIcon } from "@/components/icons";
import type { ArtistOut } from "@/lib/queries";
import {
  useArtists,
  useMe,
  usePortfolioHistory,
  useScoutLeaderboard,
} from "@/lib/queries";

function Rail({
  title,
  href,
  artists,
  loading,
}: {
  title: string;
  href: string;
  artists: ArtistOut[];
  loading: boolean;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-bold">{title}</h2>
        <Link href={href} className="text-faint hover:text-foreground text-xs font-semibold">
          See all →
        </Link>
      </div>
      <div className="no-scrollbar -mx-4 flex gap-3 overflow-x-auto px-4 pb-1">
        {loading
          ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[124px] w-[160px] shrink-0 rounded-2xl" />)
          : artists.map((artist) => <ArtistCard key={artist.slug} artist={artist} />)}
      </div>
    </section>
  );
}

export default function HomePage() {
  const me = useMe();
  const loggedIn = !!me.data;
  const history = usePortfolioHistory(loggedIn);
  const scout = useScoutLeaderboard();
  const artists = useArtists();

  if (me.isLoading) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-44 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }
  if (!me.data) {
    return <OnboardingScreen />;
  }

  const all = artists.data ?? [];
  const fastestUnder10 = [...all]
    .filter((a) => a.spot_price_cents < 1000)
    .sort((a, b) => (b.daily_change_pct ?? 0) - (a.daily_change_pct ?? 0))
    .slice(0, 10);
  const movers = [...all]
    .sort((a, b) => Math.abs(b.daily_change_pct ?? 0) - Math.abs(a.daily_change_pct ?? 0))
    .slice(0, 10);
  const fresh = [...all]
    .sort((a, b) => new Date(b.listed_at).getTime() - new Date(a.listed_at).getTime())
    .slice(0, 10);

  const scoutRank = scout.data?.you?.rank ?? null;

  return (
    <div className="animate-rise-in mx-auto flex max-w-3xl flex-col gap-7">
      <div className="flex items-center gap-3">
        <Avatar seed={me.data.username} entity="user" size={44} />
        <div>
          <p className="text-faint text-xs">Talent scout</p>
          <p className="text-sm">
            Welcome back, <span className="text-foreground font-bold">{me.data.username}</span>
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="md:col-span-2">
          {history.isLoading ? (
            <Skeleton className="h-44 w-full rounded-2xl" />
          ) : (
            <PortfolioValueChart points={history.data ?? []} />
          )}
        </div>
        <Link
          href="/leaderboard"
          className="press border-violet bg-violet-soft flex flex-col justify-center gap-1 rounded-2xl border p-5"
        >
          <span className="text-violet flex items-center gap-1.5 font-mono text-[0.65rem] font-bold tracking-wide uppercase">
            <TrophyIcon /> Talent Scout rank
          </span>
          <span className="font-heading text-3xl font-bold tabular-nums">
            {scoutRank !== null ? `#${scoutRank}` : "—"}
          </span>
          <span className="text-muted-foreground text-xs">
            {scoutRank !== null ? "Gains made while artists were still small" : "Trade to earn a rank"}
          </span>
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Link
          href="/discover"
          className="press bg-primary text-primary-foreground flex items-center justify-center gap-2 rounded-2xl px-4 py-3.5 text-sm font-bold"
        >
          <CompassIcon className="text-base" /> Discover artists
        </Link>
        <Link
          href="/portfolio"
          className="press border-border-strong text-foreground hover:bg-accent flex items-center justify-center gap-2 rounded-2xl border px-4 py-3.5 text-sm font-bold"
        >
          <SparkIcon className="text-base" /> Your portfolio
        </Link>
      </div>

      <Rail title="Fastest growing, under $10" href="/discover" artists={fastestUnder10} loading={artists.isLoading} />
      <Rail title="Biggest movers today" href="/discover" artists={movers} loading={artists.isLoading} />
      <Rail title="New listings" href="/discover" artists={fresh} loading={artists.isLoading} />
    </div>
  );
}
