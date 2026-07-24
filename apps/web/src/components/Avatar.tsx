import { artistAvatar, userAvatar } from "@/lib/avatar";
import { cn } from "@/lib/utils";

type Entity = "artist" | "user";
type Shape = "circle" | "rounded" | "square";

/** Renders a procedural avatar (see `lib/avatar.ts`) as an inline,
 * self-contained SVG. Decorative by default (`aria-hidden`) since a name
 * always sits beside it; pass `label` when the avatar stands alone. */
export function Avatar({
  seed,
  entity = "artist",
  size = 40,
  shape = entity === "artist" ? "rounded" : "circle",
  ring,
  ringColor = "rgba(255,255,255,0.25)",
  label,
  className,
}: {
  seed: string;
  entity?: Entity;
  size?: number;
  shape?: Shape;
  ring?: boolean;
  ringColor?: string;
  label?: string;
  className?: string;
}) {
  const radius = shape === "circle" ? "50%" : shape === "rounded" ? `${size * 0.28}px` : "0";
  const a11y = label
    ? ({ role: "img", "aria-label": label } as const)
    : ({ "aria-hidden": true } as const);

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={cn("block shrink-0", className)}
      style={{ borderRadius: radius, overflow: "hidden" }}
      {...a11y}
    >
      {entity === "artist" ? <ArtistFacets seed={seed} /> : <UserBlobs seed={seed} />}
      {ring && <circle cx="50" cy="50" r="48" fill="none" stroke={ringColor} strokeWidth={2.5} />}
    </svg>
  );
}

function ArtistFacets({ seed }: { seed: string }) {
  const { bg, facets } = artistAvatar(seed);
  return (
    <>
      <rect x="0" y="0" width="100" height="100" fill={bg} />
      {facets.map((f, i) => (
        <polygon key={i} points={f.points} fill={f.fill} />
      ))}
    </>
  );
}

function UserBlobs({ seed }: { seed: string }) {
  const { bg, blobs } = userAvatar(seed);
  return (
    <>
      <rect x="0" y="0" width="100" height="100" fill={bg} />
      {blobs.map((b, i) => (
        <circle key={i} cx={b.cx} cy={b.cy} r={b.r} fill={b.fill} opacity={0.92} />
      ))}
    </>
  );
}
