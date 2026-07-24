import { IBM_Plex_Mono, Inter, Space_Grotesk } from "next/font/google";

// Self-hosted via next/font -- no runtime request, no layout shift.
// Swapping any font later means changing only the call here; the
// `--font-heading` / `--font-body` / `--font-mono` tokens in globals.css
// never change. next/font's own `variable` is deliberately NOT named
// `--font-body`/`--font-heading`/`--font-mono` -- those are the semantic
// tokens in globals.css, and naming this the same would make the token
// definition self-referential.
export const bodyFont = Inter({
  subsets: ["latin"],
  variable: "--font-body-family",
  display: "swap",
});

export const headingFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading-family",
  display: "swap",
});

// The numeric/"trading terminal" voice -- prices, changes, balances.
// IBM Plex Mono isn't a variable font, so next/font requires explicit
// weights.
export const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono-family",
  display: "swap",
});
