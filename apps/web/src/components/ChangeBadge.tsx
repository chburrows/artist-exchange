import { formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The pill that carries a percentage change, colored + tinted by sign.
 * `pct` is already a percentage (e.g. `daily_change_pct`), not a
 * fraction. A `null` reads as an em-dash in the neutral tone. */
export function ChangeBadge({
  pct,
  className,
  size = "sm",
}: {
  pct: number | null;
  className?: string;
  size?: "sm" | "md";
}) {
  const tone =
    pct === null || pct === 0
      ? "bg-muted text-muted-foreground"
      : pct > 0
        ? "bg-positive-soft text-positive"
        : "bg-destructive-soft text-destructive";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-mono font-bold tabular-nums",
        size === "sm" ? "px-2 py-0.5 text-[0.7rem]" : "px-2.5 py-1 text-xs",
        tone,
        className,
      )}
    >
      {pct === null ? "—" : formatPct(pct)}
    </span>
  );
}
