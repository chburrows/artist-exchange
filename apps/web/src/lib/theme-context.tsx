"use client";

import Script from "next/script";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "ax-theme";

const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

// Runs via next/script `beforeInteractive`, injected into <head> and
// executed before first paint -- applies the persisted (or OS-preferred)
// theme class before React ever renders, so there is no flash of the
// wrong theme. Kept as a plain string, not a hook, since it must run
// outside of and before the React tree exists.
const THEME_BOOTSTRAP = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
    var dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();
`;

export function ThemeBootstrapScript() {
  return (
    // Next.js's own App Router docs place `beforeInteractive` scripts
    // exactly here (root layout); this lint rule predates App Router
    // support for the strategy and still assumes Pages Router.
    // eslint-disable-next-line @next/next/no-before-interactive-script-outside-document
    <Script id="theme-bootstrap" strategy="beforeInteractive">
      {THEME_BOOTSTRAP}
    </Script>
  );
}

function readCurrentTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  // Reads the class the bootstrap script already applied, rather than
  // guessing again. A static export prerenders this page's HTML with no
  // knowledge of the visitor's real theme, so the two renders (build-time
  // and the client's first paint) can only be reconciled by re-reading
  // the actual DOM/localStorage state after mount -- the textbook
  // external-system-sync effect, not state that could be derived from
  // props or computed during render.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(readCurrentTheme());
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Private-browsing / storage-disabled: theme just won't persist.
      }
      return next;
    });
  }, []);

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
