import { seededRandom } from "@/lib/avatar";
import { cn } from "@/lib/utils";

/** A tiny decorative accent for artist cards -- NOT a price chart. We
 * don't ship per-card price history in the `/artists` list, so this
 * must not resemble one: it's a single smooth arc (never the jagged,
 * multi-point shape real price series render as elsewhere in the app,
 * e.g. PriceChart), so it can't be mistaken for genuine historical
 * movement. The seed only bows the curve for per-card visual variety;
 * the *direction* is always the real `daily_change_pct` sign (up-and-right
 * when the day is green, down-and-right when red), and the stroke uses
 * the matching positive/destructive token, so it never contradicts the
 * real number printed beside it. */
export function Sparkline({
  seed,
  direction,
  className,
}: {
  seed: string;
  direction: "up" | "down" | "flat";
  className?: string;
}) {
  const path = buildSpark(seed, direction);
  const stroke =
    direction === "up"
      ? "var(--positive)"
      : direction === "down"
        ? "var(--destructive)"
        : "var(--muted-foreground)";

  return (
    <svg
      viewBox="0 0 60 24"
      width="100%"
      height="24"
      preserveAspectRatio="none"
      aria-hidden="true"
      className={cn("block", className)}
    >
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function buildSpark(seed: string, direction: "up" | "down" | "flat"): string {
  const rnd = seededRandom(seed);
  const clamp = (v: number) => Math.max(2, Math.min(22, v));
  const startY = clamp(12 + (rnd() - 0.5) * 6);
  const delta = direction === "up" ? -8 : direction === "down" ? 8 : (rnd() - 0.5) * 3;
  const endY = clamp(startY + delta);
  const bowY = clamp((startY + endY) / 2 + (rnd() - 0.5) * 6);
  return `M0,${startY.toFixed(1)} Q30,${bowY.toFixed(1)} 60,${endY.toFixed(1)}`;
}
