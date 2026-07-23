"use client";

import Link from "next/link";

import { useLogout, useMe } from "@/lib/queries";
import { useTheme } from "@/lib/theme-context";

const NAV_LINKS = [
  { href: "/discover", label: "Discover" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/admin", label: "Admin" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { theme, toggleTheme } = useTheme();
  const me = useMe();
  const logout = useLogout();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-border flex items-center justify-between gap-4 border-b p-4">
        <Link href="/" className="font-heading text-lg font-semibold">
          Artist Exchange
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
            </Link>
          ))}
          <button
            type="button"
            onClick={toggleTheme}
            className="border-border min-h-11 min-w-11 rounded-md border px-3"
            aria-label="Toggle dark mode"
          >
            {theme === "dark" ? "Dark" : "Light"}
          </button>
          {me.data && (
            <button
              type="button"
              onClick={() => logout.mutate()}
              className="border-border min-h-11 rounded-md border px-3"
            >
              Log out
            </button>
          )}
        </nav>
      </header>
      <main className="flex-1 p-4">{children}</main>
    </div>
  );
}
