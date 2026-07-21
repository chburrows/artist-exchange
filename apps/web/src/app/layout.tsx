import type { Metadata } from "next";

import { ThemeBootstrapScript } from "@/lib/theme-context";

import { Providers } from "./providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Artist Exchange",
  description: "Trade play-money shares in rising artists.",
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
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeBootstrapScript />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
