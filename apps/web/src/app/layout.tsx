import type { Metadata, Viewport } from "next";

import { bodyFont, headingFont, monoFont } from "@/lib/fonts";
import { ServiceWorkerRegister } from "@/lib/register-service-worker";
import { ThemeBootstrapScript } from "@/lib/theme-context";

import { Providers } from "./providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Artist Exchange",
  description: "Trade play-money shares in rising artists.",
  manifest: "/manifest.json",
};

// `viewport-fit=cover` lets the layout extend under notches so the
// bottom tab bar's `env(safe-area-inset-bottom)` padding has something
// to work with. This static `themeColor` is only the pre-hydration
// fallback (a static export can't know the visitor's preference at
// build time) -- it's corrected to match the app's *actual* active
// theme (which is a manual toggle, not just OS preference) by the
// bootstrap script and `ThemeProvider` in theme-context.tsx before
// first paint, so it never sits on the wrong value the way a
// `prefers-color-scheme` media query would when the two disagree.
export const viewport: Viewport = {
  viewportFit: "cover",
  themeColor: "#0a0b0f",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // The theme-bootstrap script (below) adds/removes `dark` on this
    // element before React hydrates, on purpose -- it must run before
    // first paint to avoid a flash of the wrong theme, which means the
    // class it sets will always differ from this statically-exported
    // page's server-rendered markup.
    <html
      lang="en"
      className={`${bodyFont.variable} ${headingFont.variable} ${monoFont.variable}`}
      suppressHydrationWarning
    >
      <body>
        <ThemeBootstrapScript />
        <ServiceWorkerRegister />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
