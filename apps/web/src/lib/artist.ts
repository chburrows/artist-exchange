/** Small presentational helpers shared across artist surfaces. The API
 * ships `tier` as a raw enum string and change as a signed percentage;
 * these keep the label/direction mapping in one place. */

export function tierLabel(tier: string): string {
  return tier === "blue_chip" ? "Blue chip" : "Growth";
}

export function directionOf(pct: number | null): "up" | "down" | "flat" {
  if (pct === null || pct === 0) return "flat";
  return pct > 0 ? "up" : "down";
}
