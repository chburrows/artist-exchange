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
// to work with. `themeColor` reacts to the visitor's theme so the mobile
// status bar matches the app-shell chrome in both modes.
export const viewport: Viewport = {
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0b0f" },
  ],
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
