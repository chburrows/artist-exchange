import { avatarStyle } from "@/lib/avatar";
import { cn } from "@/lib/utils";

export function ArtistAvatar({
  slug,
  tier,
  size = 40,
  className,
}: {
  slug: string;
  tier?: "growth" | "blue_chip";
  size?: number;
  className?: string;
}) {
  const ringColor = tier === "blue_chip" ? "var(--border)" : "var(--primary)";
  return (
    <div
      aria-hidden
      className={cn("shrink-0 rounded-full", className)}
      style={{
        width: size,
        height: size,
        boxShadow: `0 0 0 2px ${ringColor}`,
        ...avatarStyle(slug),
      }}
    />
  );
}
