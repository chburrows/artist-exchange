"use client";

import { useState } from "react";

import { Avatar } from "@/components/Avatar";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CompassIcon, SparkIcon, TrendingUpIcon } from "@/components/icons";
import { directionOf } from "@/lib/artist";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { errorMessage } from "@/lib/errors";
import { formatCents, formatPct } from "@/lib/format";
import { useArtists, useRequestSignup } from "@/lib/queries";
import { generateUsername } from "@/lib/username";
import { cn } from "@/lib/utils";

import { SignInPanel } from "./SignInPanel";

const FEATURES = [
  {
    icon: CompassIcon,
    title: "Discover",
    body: "Fastest growing, under $10. New listings surface every day.",
    tone: "text-primary",
  },
  {
    icon: TrendingUpIcon,
    title: "Trade",
    body: "Buy and sell against a live fair-value index. No leverage, no order book.",
    tone: "text-violet",
  },
  {
    icon: SparkIcon,
    title: "Prove it",
    body: "Talent Scout ranks discovery skill, not capital. Being early is the record.",
    tone: "text-positive",
  },
];

export function OnboardingScreen() {
  const [email, setEmail] = useState("");
  // Prefilled-but-editable: a client-side suggestion so the field isn't
  // empty on first render, not the value the server actually falls back
  // to if this were left blank (that's `POST /auth/signup/consume`'s own
  // generator -- see `services/api/src/ax/api/username_gen.py`).
  const [username, setUsername] = useState(generateUsername);
  const [signInOpen, setSignInOpen] = useState(false);
  const [checkInboxFor, setCheckInboxFor] = useState<string | null>(null);
  const requestSignup = useRequestSignup();
  const artists = useArtists();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || username.length < 3) return;
    requestSignup.mutate({ email, username }, { onSuccess: () => setCheckInboxFor(email) });
  };

  if (checkInboxFor) {
    return (
      <div className="animate-pop-in mx-auto flex max-w-md flex-col items-center gap-5 py-16 text-center">
        <BrandMark size={44} withWordmark={false} className="animate-pulse-glow" />
        <h1 className="font-heading text-2xl font-bold">Check your inbox</h1>
        <p className="text-muted-foreground text-sm leading-relaxed">
          We sent a confirmation link to <span className="text-foreground font-bold">{checkInboxFor}</span>.
          Tap it to finish creating your account and claim your {formatCents(STARTING_BALANCE_CENTS)} of play
          money.
        </p>
        <p className="text-faint text-xs">No password, no code to type — just the link.</p>
      </div>
    );
  }

  const ticker = artists.data ?? [];

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-12 py-4">
      <section className="animate-rise-in flex flex-col items-center gap-5 pt-6 text-center md:pt-10">
        <span className="text-primary font-mono text-[0.7rem] font-semibold tracking-[0.14em] uppercase">
          Play-money markets on real popularity
        </span>
        <h1 className="font-heading text-4xl leading-[1.03] font-bold tracking-tight sm:text-6xl">
          Discover them
          <br />
          before they blow up.
        </h1>
        <p className="text-muted-foreground max-w-xl text-sm leading-relaxed sm:text-base">
          Trade shares of emerging artists against a live popularity index. Being early is the whole game —
          and now it&apos;s provable.
        </p>

        <form onSubmit={handleSubmit} className="mt-2 flex w-full max-w-sm flex-col gap-3 text-left">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="crate_diver"
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9_\-]{3,24}"
              required
            />
          </div>
          {requestSignup.isError && (
            <p className="text-destructive text-xs">{errorMessage(requestSignup.error)}</p>
          )}
          <Button type="submit" size="lg" disabled={requestSignup.isPending}>
            {requestSignup.isPending
              ? "Sending confirmation…"
              : `Get started — ${formatCents(STARTING_BALANCE_CENTS)} free`}
          </Button>
          <p className="text-faint text-center text-[0.7rem]">
            No password. We&apos;ll email you a magic link. Play money only — no real funds.
          </p>
        </form>

        <button
          type="button"
          className="text-muted-foreground hover:text-foreground text-sm underline underline-offset-4"
          onClick={() => setSignInOpen(true)}
        >
          I already have an account
        </button>
        <SignInPanel open={signInOpen} onOpenChange={setSignInOpen} />
      </section>

      {ticker.length > 0 && (
        <div className="border-border overflow-hidden border-y py-3.5">
          <div className="animate-ticker flex w-max gap-7">
            {[...ticker, ...ticker].map((a, i) => {
              const dir = directionOf(a.daily_change_pct);
              return (
                <div key={i} className="flex flex-none items-center gap-2">
                  <Avatar seed={a.slug} entity="artist" size={22} />
                  <span className="text-[0.8rem] font-semibold">{a.name}</span>
                  <span
                    className={cn(
                      "font-mono text-[0.72rem] font-semibold tabular-nums",
                      dir === "up" ? "text-positive" : dir === "down" ? "text-destructive" : "text-faint",
                    )}
                  >
                    {a.daily_change_pct === null ? "—" : formatPct(a.daily_change_pct)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-3">
        {FEATURES.map((f) => {
          const Icon = f.icon;
          return (
            <div key={f.title} className="border-border bg-card rounded-2xl border p-6">
              <Icon className={cn("mb-3 text-2xl", f.tone)} />
              <h3 className="font-heading mb-1.5 text-lg font-bold">{f.title}</h3>
              <p className="text-muted-foreground text-sm leading-relaxed">{f.body}</p>
            </div>
          );
        })}
      </section>
    </div>
  );
}
