"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { useArtists, useSignup } from "@/lib/queries";

import { SignInPanel } from "./SignInPanel";

const STEPS = [
  "Discover an artist before they blow up",
  "Back your pick with play money",
  "Watch the index catch up to you",
];

export function OnboardingScreen() {
  const [username, setUsername] = useState("");
  const [signInOpen, setSignInOpen] = useState(false);
  const signup = useSignup();
  const roster = useArtists();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.length < 3) return;
    signup.mutate(username);
  };

  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-5 py-10 text-center sm:py-16">
      <Logo />
      <h1 className="text-3xl leading-tight font-extrabold tracking-tight sm:text-4xl">
        Find them first.
        <br />
        Prove it forever.
      </h1>
      <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
        Trade play-money shares in rising artists. Price tracks a real popularity index — being
        early is what pays.
      </p>

      <form onSubmit={handleSubmit} className="flex w-full max-w-xs flex-col gap-3 pt-2">
        <div className="flex flex-col gap-1.5 text-left">
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
        {signup.isError && (
          <p className="text-xs text-destructive">
            {errorMessage(signup.error, "That username might be taken -- try another.")}
          </p>
        )}
        <Button type="submit" size="lg" disabled={signup.isPending}>
          {signup.isPending ? "Creating account…" : `Get started — ${formatCents(STARTING_BALANCE_CENTS)} free`}
        </Button>
      </form>

      <button
        type="button"
        className="text-sm text-muted-foreground underline underline-offset-2"
        onClick={() => setSignInOpen(true)}
      >
        I already have an account
      </button>
      <SignInPanel open={signInOpen} onOpenChange={setSignInOpen} />

      <ol className="mt-4 grid grid-cols-1 gap-4 text-left sm:grid-cols-3">
        {STEPS.map((step, i) => (
          <li key={step}>
            <span className="text-xs font-extrabold text-primary">{i + 1}</span>
            <p className="mt-1 text-xs text-muted-foreground">{step}</p>
          </li>
        ))}
      </ol>

      {roster.data && roster.data.length > 0 && (
        <div className="mt-2 w-full">
          <p className="mb-2.5 text-xs text-muted-foreground">Meet the roster</p>
          <div className="flex justify-center gap-2.5">
            {roster.data.slice(0, 5).map((a) => (
              <ArtistAvatar key={a.slug} slug={a.slug} tier={a.tier as "growth" | "blue_chip"} size={44} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Logo() {
  return (
    <div className="flex h-6 items-end gap-1">
      <span className="h-2.5 w-1.5 rounded-sm bg-primary" />
      <span className="h-6 w-1.5 rounded-sm bg-primary" />
      <span className="h-4 w-1.5 rounded-sm bg-primary" />
    </div>
  );
}
