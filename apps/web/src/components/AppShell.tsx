"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatCents } from "@/lib/format";
import { useLogout, useMe, usePortfolio } from "@/lib/queries";
import { useTheme } from "@/lib/theme-context";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/discover", label: "Discover" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/leaderboard", label: "Ranks" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const me = useMe();
  const portfolio = usePortfolio(!!me.data);
  const logout = useLogout();

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const signedIn = !!me.data;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur-sm sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <Logo />
          <span className="hidden text-base font-extrabold tracking-tight sm:inline">
            Artist Exchange
          </span>
        </Link>

        <div className="flex items-center gap-2">
          {signedIn && portfolio.data && (
            <Link
              href="/portfolio"
              className="hidden rounded-full bg-secondary px-3.5 py-2 text-sm font-bold whitespace-nowrap sm:inline-block"
            >
              {formatCents(portfolio.data.cash_cents)}{" "}
              <span className="font-medium text-muted-foreground">cash</span>
            </Link>
          )}
          <Button variant="outline" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === "dark" ? "☀" : "☾"}
          </Button>
          {signedIn && (
            <Button variant="ghost" size="sm" onClick={() => logout.mutate()}>
              Log out
            </Button>
          )}
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl items-start">
        {signedIn && (
          <aside className="sticky top-16 hidden w-20 shrink-0 flex-col items-center gap-6 self-start py-8 md:flex">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex flex-col items-center gap-1.5"
              >
                <span
                  className={cn(
                    "h-6 w-6 rounded-md border border-border bg-secondary",
                    isActive(item.href) && "border-transparent bg-primary",
                  )}
                  aria-hidden
                />
                <span
                  className={cn(
                    "text-[11px] font-bold text-muted-foreground",
                    isActive(item.href) && "text-primary",
                  )}
                >
                  {item.label}
                </span>
              </Link>
            ))}
          </aside>
        )}

        <main
          className={cn(
            "min-w-0 max-w-5xl flex-1 px-4 pt-6 sm:px-6",
            signedIn ? "pb-24 md:pb-10" : "pb-10",
          )}
        >
          {children}
        </main>
      </div>

      {signedIn && (
        <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-border bg-background py-2 md:hidden">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-bold text-muted-foreground",
                isActive(item.href) && "text-primary",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      )}
    </div>
  );
}

function Logo() {
  return (
    <div className="flex h-4 items-end gap-0.5" aria-hidden>
      <span className="h-2 w-1 rounded-sm bg-primary" />
      <span className="h-4 w-1 rounded-sm bg-primary" />
      <span className="h-2.5 w-1 rounded-sm bg-primary" />
    </div>
  );
}
