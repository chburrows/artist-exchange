/** Deterministic "geometric avatar from a name hash" (CLAUDE.md: no
 * artist photography in v1 -- sidesteps image licensing and right-of-
 * publicity exposure). Same input always produces the same avatar, with
 * no network request and no stored image. */

/** Exported for `ShareCardDialog`, which needs the raw hue pair to draw
 * the same deterministic identity onto a `<canvas>` -- canvas fill
 * styles can't consume the CSS `repeating-linear-gradient()` string
 * `avatarStyle` below produces for the DOM. */
export function hashString(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

export interface AvatarStyle {
  background: string;
}

export function avatarStyle(seed: string): AvatarStyle {
  const hash = hashString(seed);
  const hue = hash % 360;
  const hue2 = (hue + 35 + (hash % 25)) % 360;
  const angle = 100 + (hash % 60);
  return {
    background: `repeating-linear-gradient(${angle}deg, hsl(${hue} 65% 55%) 0px, hsl(${hue} 65% 55%) 6px, hsl(${hue2} 60% 40%) 6px, hsl(${hue2} 60% 40%) 12px)`,
  };
}
