import { Inter, Space_Grotesk } from "next/font/google";

// Self-hosted via next/font -- no runtime request, no layout shift.
// Swapping either font later means changing only the call here; the
// `--font-heading` / `--font-body` tokens in globals.css never change.
// next/font's own `variable` is deliberately NOT named `--font-body`/
// `--font-heading` -- those are the semantic tokens in globals.css, and
// naming this the same would make the token definition self-referential.
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
