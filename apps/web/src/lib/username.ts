/** Client-side default-username suggestion for the signup form --
 * prefilled-but-editable, no dependency, no network call.
 *
 * Mirrors the shape of `services/api/src/ax/api/username_gen.py`'s
 * server-side generator (adjective + noun + 2-digit suffix), but is not
 * shared code with it -- different languages, matched approach only.
 * That server-side copy is the one that actually matters for
 * correctness (it's what `POST /auth/signup/consume` falls back to if a
 * request omits `username` entirely); this one only exists so the input
 * isn't empty before the user has typed anything. */

const ADJECTIVES = [
  "quiet",
  "brave",
  "lucky",
  "electric",
  "velvet",
  "neon",
  "golden",
  "midnight",
  "crimson",
  "silver",
  "amber",
  "restless",
  "solar",
  "hollow",
  "vivid",
  "gilded",
  "wild",
  "faded",
  "arctic",
  "feral",
];

const NOUNS = [
  "scout",
  "comet",
  "otter",
  "falcon",
  "harbor",
  "ember",
  "meadow",
  "cipher",
  "atlas",
  "raven",
  "compass",
  "current",
  "signal",
  "orbit",
  "canyon",
  "lantern",
  "echo",
  "tide",
  "prism",
  "drift",
];

function pick<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)];
}

export function generateUsername(): string {
  const suffix = Math.floor(Math.random() * 100)
    .toString()
    .padStart(2, "0");
  return `${pick(ADJECTIVES)}${pick(NOUNS)}${suffix}`;
}
