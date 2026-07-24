/** Procedural avatars -- deterministic from a seed, no network request,
 * no stored image (right-of-publicity constraint from CLAUDE.md /
 * ARCHITECTURE.md). Artists and users use *visibly different* generation
 * grammars so the two are never confused at a glance:
 *
 *   - artists  -> "crystalline shard": an asymmetric fan of hard-edged
 *                 triangular facets. Sharp, energetic, gem-like.
 *   - users    -> "soft bloom": a cluster of overlapping rounded blobs
 *                 in a cooler, calmer palette. Round, friendly.
 *
 * All coordinates are in a 0..100 viewBox so the same data drives both
 * the SVG <Avatar> component and the canvas share-card renderer. Pure by
 * design -- no imports, no time, no I/O -- so it stays trivially
 * testable and identical on every render for a given seed. */

export type ArtistAvatar = {
  bg: string;
  facets: { points: string; fill: string }[];
};

export type UserAvatar = {
  bg: string;
  blobs: { cx: number; cy: number; r: number; fill: string }[];
};

/** FNV-1a seed -> xorshift stream in [0, 1). Same construction the
 * design mockups used, so seeds line up with the reference visuals. */
export function seededRandom(seed: string): () => number {
  let h = 2166136261;
  const str = String(seed);
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return (h >>> 0) / 4294967295;
  };
}

export function artistAvatar(seed: string): ArtistAvatar {
  const rnd = seededRandom(seed);
  const baseHue = rnd() * 360;
  const spread = 55 + rnd() * 40;
  const facetCount = 6;
  const cx = 50;
  const cy = 50;

  const outline: [number, number][] = [];
  for (let i = 0; i < facetCount; i++) {
    const angle = (i / facetCount) * Math.PI * 2 + rnd() * 0.3;
    const r = 46 + (rnd() - 0.5) * 14;
    outline.push([cx + Math.cos(angle) * r, cy + Math.sin(angle) * r]);
  }

  const facets = outline.map((p, i) => {
    const next = outline[(i + 1) % outline.length];
    const hueOffset = (rnd() - 0.5) * spread;
    const hue = (baseHue + hueOffset + 360) % 360;
    const light = 0.5 + rnd() * 0.28;
    const chroma = 0.14 + rnd() * 0.08;
    return {
      points: `${cx},${cy} ${p[0].toFixed(1)},${p[1].toFixed(1)} ${next[0].toFixed(1)},${next[1].toFixed(1)}`,
      fill: `oklch(${light.toFixed(2)} ${chroma.toFixed(2)} ${hue.toFixed(0)})`,
    };
  });

  const bgLight = 0.22 + rnd() * 0.1;
  return {
    bg: `oklch(${bgLight.toFixed(2)} 0.03 ${baseHue.toFixed(0)})`,
    facets,
  };
}

export function userAvatar(seed: string): UserAvatar {
  // Offset the stream from the artist grammar so a shared seed (an
  // artist and a fan who happen to share a name) still diverges.
  const rnd = seededRandom("user:" + seed);
  const baseHue = rnd() * 360;
  const blobCount = 5;

  const blobs = Array.from({ length: blobCount }, (_, i) => {
    // First blob anchors the composition centered and large; the rest
    // scatter around it to build a soft, off-center cluster.
    const centered = i === 0;
    const cx = centered ? 50 : 50 + (rnd() - 0.5) * 52;
    const cy = centered ? 50 : 50 + (rnd() - 0.5) * 52;
    const r = centered ? 34 : 18 + rnd() * 20;
    const hue = (baseHue + i * 30 + rnd() * 18) % 360;
    const light = 0.58 + rnd() * 0.24;
    const chroma = 0.1 + rnd() * 0.06;
    return { cx, cy, r, fill: `oklch(${light.toFixed(2)} ${chroma.toFixed(2)} ${hue.toFixed(0)})` };
  });

  const bgLight = 0.2 + rnd() * 0.08;
  return {
    bg: `oklch(${bgLight.toFixed(2)} 0.04 ${((baseHue + 180) % 360).toFixed(0)})`,
    blobs,
  };
}
