"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType, SVGProps } from "react";

import { Avatar } from "@/components/Avatar";
import { BrandMark } from "@/components/BrandMark";
import {
  CompassIcon,
  HomeIcon,
  LogOutIcon,
  MoonIcon,
  SunIcon,
  TrophyIcon,
  WalletIcon,
} from "@/components/icons";
import { formatCents } from "@/lib/format";
import { useLogout, useMe, usePortfolio } from "@/lib/queries";
import { useTheme } from "@/lib/theme-context";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  match: (path: string) => boolean;
};

// Admin is intentionally absent: UserOut carries no role, so admin
// gating (and its UI) is the step-5 concern -- the primary nav is the
// four public surfaces the design ships. Artist detail highlights under
// Discover, where it's reached from.
const NAV: NavItem[] = [
  { href: "/", label: "Home", icon: HomeIcon, match: (p) => p === "/" },
  {
    href: "/discover",
    label: "Discover",
    icon: CompassIcon,
    match: (p) => p.startsWith("/discover") || p.startsWith("/artist"),
  },
  { href: "/portfolio", label: "Portfolio", icon: WalletIcon, match: (p) => p.startsWith("/portfolio") },
  { href: "/leaderboard", label: "Leaderboard", icon: TrophyIcon, match: (p) => p.startsWith("/leaderboard") },
];

function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label="Toggle dark mode"
      className={cn(
        "press flex size-9 items-center justify-center rounded-full border border-border text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      {theme === "dark" ? <SunIcon className="text-base" /> : <MoonIcon className="text-base" />}
    </button>
  );
}

function BalancePill({ cashCents }: { cashCents: number }) {
  return (
    <span
      title="Play money — no real funds"
      className="rounded-full bg-primary-soft px-3 py-1 font-mono text-xs font-bold tabular-nums text-primary"
    >
      {formatCents(cashCents)}
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const me = useMe();
  const loggedIn = !!me.data;
  const portfolio = usePortfolio(loggedIn);
  const logout = useLogout();
  const cash = portfolio.data?.cash_cents ?? null;

  return (
    <div className="min-h-screen md:flex">
      {/* Desktop sidebar */}
      <aside className="border-border bg-bg-alt sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r p-4 md:flex">
        <Link href="/" className="mb-6 flex items-center px-2 py-1">
          <BrandMark size={22} />
        </Link>
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "press flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="text-lg" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        {loggedIn && me.data ? (
          <div className="border-border flex flex-col gap-3 rounded-2xl border p-3">
            <div className="flex items-center gap-2.5">
              <Avatar seed={me.data.username} entity="user" size={34} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-bold">@{me.data.username}</div>
                {cash !== null && (
                  <div className="text-primary font-mono text-xs font-bold tabular-nums">
                    {formatCents(cash)}
                  </div>
                )}
              </div>
              <ThemeToggle />
            </div>
            <button
              type="button"
              onClick={() => logout.mutate()}
              className="press text-muted-foreground hover:text-foreground flex items-center justify-center gap-2 rounded-xl border border-border py-2 text-xs font-bold"
            >
              <LogOutIcon className="text-sm" />
              Log out
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <Link
              href="/"
              className="press bg-primary text-primary-foreground flex-1 rounded-xl px-3 py-2.5 text-center text-sm font-bold"
            >
              Start scouting
            </Link>
            <ThemeToggle />
          </div>
        )}
      </aside>

      {/* Right column */}
      <div className="flex min-h-screen flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="border-border bg-bg-alt/85 sticky top-0 z-40 flex items-center justify-between gap-3 border-b px-4 py-2.5 backdrop-blur-md md:hidden">
          <Link href="/" aria-label="Artist Exchange home">
            <BrandMark size={20} />
          </Link>
          <div className="flex items-center gap-2">
            {loggedIn && cash !== null && <BalancePill cashCents={cash} />}
            <ThemeToggle />
            {loggedIn && (
              <button
                type="button"
                onClick={() => logout.mutate()}
                aria-label="Log out"
                className="press text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-full border border-border"
              >
                <LogOutIcon className="text-base" />
              </button>
            )}
          </div>
        </header>

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-5 pb-28 md:px-8 md:py-8 md:pb-10">
          {children}
        </main>

        {/* Mobile bottom tab bar */}
        <nav className="border-border bg-bg-alt/90 pb-safe fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t pt-1.5 backdrop-blur-md md:hidden">
          {NAV.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-11 flex-col items-center justify-center gap-1 py-1 text-[0.62rem] font-semibold transition-colors",
                  active ? "text-primary" : "text-faint",
                )}
              >
                <Icon className="text-xl" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
