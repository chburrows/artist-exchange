"use client";

import Link from "next/link";
import { useState } from "react";

import { ShieldIcon } from "@/components/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { type FlaggedArtistOut, useClearFlag, useFlaggedArtists, useMe } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** The two `reason` triggers `jobs/recompute.py` can write, joined by
 * commas when both fire on the same night. Unknown values fall back to
 * the raw string rather than being dropped -- a new detector shipping
 * server-side must never render as a blank chip here. */
const REASON_LABELS: Record<string, { label: string; hint: string }> = {
  ratio_divergence: {
    label: "Ratio divergence",
    hint: "Playcount growth ran far ahead of unique-listener growth — the scrobble-bot signature.",
  },
  percentile_move: {
    label: "Outlier move",
    hint: "Index score moved further in one day than almost every other artist that night.",
  },
};

function formatDetailValue(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (value === null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** `detail` is a free-form JSON blob whose shape depends on which
 * detectors fired (`{ratio_divergence: {...}, percentile_move: {...}}`
 * today). Flattened generically, one `group.key` row per leaf, so a
 * detector added server-side shows up here with no frontend change. */
function flattenDetail(detail: Record<string, unknown>, prefix = ""): [string, string][] {
  return Object.entries(detail).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? flattenDetail(value as Record<string, unknown>, path)
      : [[path, formatDetailValue(value)] as [string, string]];
  });
}

function ReasonChips({ reason }: { reason: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {reason.split(",").map((trigger) => {
        const known = REASON_LABELS[trigger.trim()];
        return (
          <span
            key={trigger}
            title={known?.hint}
            className="bg-violet-soft text-violet rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold"
          >
            {known?.label ?? trigger.trim()}
          </span>
        );
      })}
    </div>
  );
}

function FlagRow({ flag, siblingOpen }: { flag: FlaggedArtistOut; siblingOpen: number }) {
  const clear = useClearFlag();
  const [confirming, setConfirming] = useState(false);
  const cleared = flag.cleared_at !== null;
  const details = flattenDetail(flag.detail);

  return (
    <li
      className={cn(
        "border-border bg-card flex flex-col gap-3 rounded-2xl border p-4",
        cleared && "opacity-60",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={`/artist?slug=${encodeURIComponent(flag.artist_slug)}`}
          className="font-heading hover:text-primary text-base font-bold underline-offset-4 hover:underline"
        >
          {flag.artist_slug}
        </Link>
        <span className="text-faint font-mono text-xs font-bold tabular-nums">{flag.as_of_date}</span>
      </div>

      <ReasonChips reason={flag.reason} />

      {details.length > 0 && (
        <dl className="border-border grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t pt-3 text-xs">
          {details.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground font-mono">{key}</dt>
              <dd className="text-right font-mono font-bold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {cleared ? (
        <p className="text-muted-foreground text-xs">
          Cleared by <span className="font-bold">{flag.cleared_by ?? "unknown"}</span> on{" "}
          {flag.cleared_at?.slice(0, 10)}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {/* `recompute._unresolved_flagged_artist_ids` carries a
              quarantine forward on *any* open row for the artist, so one
              row is not one quarantine -- saying "cleared" here while
              the artist stays frozen would be a lie the admin only
              discovers a night later. */}
          {siblingOpen > 0 && (
            <p className="text-muted-foreground text-xs">
              This artist has {siblingOpen} other open{" "}
              {siblingOpen === 1 ? "flag" : "flags"} — it stays quarantined until every one is
              cleared.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {confirming ? (
              <>
                <button
                  type="button"
                  disabled={clear.isPending}
                  onClick={() =>
                    clear.mutate({ artist_id: flag.artist_id, as_of_date: flag.as_of_date })
                  }
                  className="press bg-destructive text-destructive-foreground min-h-11 rounded-xl px-4 text-xs font-bold disabled:opacity-50"
                >
                  {clear.isPending ? "Clearing…" : "Yes, clear this flag"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="press text-muted-foreground hover:text-foreground min-h-11 px-2 text-xs font-bold"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="press border-border hover:bg-secondary min-h-11 rounded-xl border px-4 text-xs font-bold"
              >
                Clear this flag
              </button>
            )}
            {clear.isError && (
              <span className="text-destructive text-xs">Couldn&apos;t clear — try again.</span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export default function AdminPage() {
  const me = useMe();
  const [includeCleared, setIncludeCleared] = useState(false);
  const isAdmin = me.data?.is_admin === true;
  const flags = useFlaggedArtists(isAdmin, includeCleared);

  if (me.isLoading) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-32 w-full rounded-2xl" />
      </div>
    );
  }

  // `useMe` maps only a 401 to `null` -- a network blip or a 5xx leaves
  // `data` undefined, which must not read as "signed out" and send a
  // logged-in admin to a sign-in prompt that won't help.
  if (me.isError) {
    return (
      <p className="text-destructive mx-auto max-w-md py-16 text-center text-sm">
        Couldn&apos;t confirm your account — reload to try again.
      </p>
    );
  }

  if (!me.data) {
    return (
      <div className="text-muted-foreground mx-auto max-w-md py-16 text-center text-sm">
        <Link href="/" className="text-primary font-bold underline underline-offset-2">
          Sign in
        </Link>{" "}
        to reach the admin tools.
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="text-muted-foreground mx-auto max-w-md py-16 text-center text-sm">
        This page is for admins. Ask whoever runs the deployment to grant access.
      </div>
    );
  }

  const rows = flags.data ?? [];
  const openCount = rows.filter((f) => f.cleared_at === null).length;
  // Open flags per artist, so a row can say how many others still hold
  // the same artist under quarantine. Only meaningful on the open list;
  // the cleared view is history, not live state.
  const openPerArtist = new Map<number, number>();
  for (const f of rows) {
    if (f.cleared_at === null) {
      openPerArtist.set(f.artist_id, (openPerArtist.get(f.artist_id) ?? 0) + 1);
    }
  }

  return (
    <div className="animate-rise-in mx-auto flex max-w-2xl flex-col gap-5">
      <h1 className="font-heading flex items-center gap-2 text-2xl font-bold sm:text-3xl">
        <ShieldIcon className="text-violet text-2xl" />
        Review queue
      </h1>

      {/* The queue is the *only* exit from a quarantine: nothing expires
          it, so an unattended flag freezes that artist's fair value
          forever. Saying so on the page is a deliberate ask from
          ARCHITECTURE.md, not incidental copy. */}
      <div className="border-border bg-card text-muted-foreground rounded-2xl border p-4 text-xs leading-relaxed">
        A flagged artist is <strong className="text-foreground">quarantined</strong>: its published
        index score and fair value are held at the previous night&apos;s values while trading continues
        normally. Quarantines never expire on their own. A flag is one night&apos;s detection, and an
        artist stays quarantined while <em>any</em> of its flags is open — so clearing the last open
        flag for an artist is what lifts it, and fair value only starts moving again at the next
        nightly recompute.
      </div>

      <div className="bg-secondary flex gap-1 rounded-xl p-1">
        {[
          { id: false, label: "Open" },
          { id: true, label: "Include cleared" },
        ].map((t) => (
          <button
            key={String(t.id)}
            type="button"
            onClick={() => setIncludeCleared(t.id)}
            aria-pressed={includeCleared === t.id}
            className={cn(
              "press min-h-10 flex-1 rounded-lg text-sm font-bold transition-colors",
              includeCleared === t.id ? "bg-primary text-primary-foreground" : "text-muted-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {flags.isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36 w-full rounded-2xl" />
          ))}
        </div>
      ) : flags.isError ? (
        <p className="text-destructive text-sm">Couldn&apos;t load the review queue.</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center text-sm">
          {includeCleared ? "No artist has ever been flagged." : "Nothing quarantined — the queue is clear."}
        </p>
      ) : (
        <>
          <p className="text-faint text-xs font-bold">
            {openCount} open{includeCleared && rows.length > openCount ? ` · ${rows.length - openCount} cleared` : ""}
          </p>
          <ul className="flex flex-col gap-3">
            {rows.map((flag) => (
              <FlagRow
                key={`${flag.artist_id}-${flag.as_of_date}`}
                flag={flag}
                siblingOpen={(openPerArtist.get(flag.artist_id) ?? 1) - 1}
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
