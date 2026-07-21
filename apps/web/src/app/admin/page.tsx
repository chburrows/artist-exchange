"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import {
  ForbiddenError,
  useClearFlaggedArtist,
  useFlaggedArtists,
  useMe,
  type FlaggedArtistOut,
} from "@/lib/queries";

/** Oracle-manipulation review queue (PLAN.md Phase 3 follow-up: "surface
 * `flagged_artists` in an admin view instead of relying on direct DB
 * access indefinitely"). The API is the actual gate -- `/admin/*` 403s a
 * non-admin -- so this page has no client-side route guard beyond
 * rendering whatever the API says. There's no self-service way to become
 * an admin; see `ax promote-admin`. */
export default function AdminPage() {
  const me = useMe();
  const flags = useFlaggedArtists(!!me.data);
  const clearFlag = useClearFlaggedArtist();

  if (me.isLoading) {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }

  if (!me.data) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-muted-foreground">Sign in as an admin to review flagged artists.</p>
        <Link href="/" className="text-sm font-bold text-primary">
          Get started →
        </Link>
      </div>
    );
  }

  if (flags.isError) {
    if (flags.error instanceof ForbiddenError) {
      return (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {me.data.username} isn&apos;t an admin.
        </p>
      );
    }
    return <p className="py-10 text-center text-sm text-destructive">Couldn&apos;t load the review queue.</p>;
  }

  if (flags.isLoading || !flags.data) {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-4 pb-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Oracle-manipulation review queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A flagged artist&apos;s fair value is held at its previous value until cleared here.
        </p>
      </div>

      {flags.data.length === 0 ? (
        <p className="py-6 text-sm text-muted-foreground">No open flags.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {flags.data.map((flag) => (
            <FlagRow
              key={`${flag.artist_id}-${flag.as_of_date}`}
              flag={flag}
              onClear={() => clearFlag.mutate({ artistId: flag.artist_id, asOfDate: flag.as_of_date })}
              clearing={
                clearFlag.isPending &&
                clearFlag.variables?.artistId === flag.artist_id &&
                clearFlag.variables?.asOfDate === flag.as_of_date
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FlagRow({
  flag,
  onClear,
  clearing,
}: {
  flag: FlaggedArtistOut;
  onClear: () => void;
  clearing: boolean;
}) {
  const triggers = flag.reason.split(",");

  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-border bg-card px-4 py-3.5">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="font-bold">{flag.artist_slug}</span>
          <span className="text-xs text-muted-foreground">{formatDate(flag.as_of_date)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {triggers.map((trigger) => (
            <Badge key={trigger} variant="outline">
              {trigger.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      </div>
      <Button size="sm" variant="outline" onClick={onClear} disabled={clearing}>
        {clearing ? "Clearing…" : "Clear"}
      </Button>
    </div>
  );
}
