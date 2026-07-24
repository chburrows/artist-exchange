"use client";

import Script from "next/script";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "ax-theme";
const LIGHT_THEME_COLOR = "#f7f6f2";
const DARK_THEME_COLOR = "#0a0b0f";

const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null);

// Keeps the `<meta name="theme-color">` tag (which paints the mobile
// status bar / home-indicator strip) in sync with the *app's* active
// theme. This has to be a direct DOM write, not a `prefers-color-scheme`
// media query on the meta tag, because the app's theme is a manual
// toggle that can and does disagree with the OS setting.
function applyThemeColor(dark: boolean) {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? DARK_THEME_COLOR : LIGHT_THEME_COLOR);
}

// Runs via next/script `beforeInteractive`, injected into <head> and
// executed before first paint -- applies the persisted (or OS-preferred)
// theme class before React ever renders, so there is no flash of the
// wrong theme. A static export can't know the visitor's preference at
// build time, which is exactly why this can't be done any other way.
// Kept as a plain string, not a hook, since it must run outside of and
// before the React tree exists.
const THEME_BOOTSTRAP = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
    var dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.classList.add("dark");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? ${JSON.stringify(DARK_THEME_COLOR)} : ${JSON.stringify(LIGHT_THEME_COLOR)});
  } catch (e) {}
})();
`;

export function ThemeBootstrapScript() {
  return (
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
  // guessing again -- the textbook external-system-sync effect, not
  // state derivable from props or render.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(readCurrentTheme());
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    applyThemeColor(theme === "dark");
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
