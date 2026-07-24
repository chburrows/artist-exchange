import { cn } from "@/lib/utils";

/** Shimmering placeholder used while data loads -- calmer than a bare
 * "Loading…" line and keeps layout from jumping when content arrives.
 * The shimmer animation lives in globals.css (`.ax-skeleton`) and is
 * disabled under prefers-reduced-motion. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("ax-skeleton rounded-lg", className)} aria-hidden="true" />;
}
