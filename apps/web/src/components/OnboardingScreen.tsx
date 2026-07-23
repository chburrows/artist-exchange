"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { STARTING_BALANCE_CENTS } from "@/lib/constants";
import { errorMessage } from "@/lib/errors";
import { formatCents } from "@/lib/format";
import { useRequestSignup } from "@/lib/queries";
import { generateUsername } from "@/lib/username";

import { SignInPanel } from "./SignInPanel";

const STEPS = [
  "Discover an artist before they blow up",
  "Back your pick with play money",
  "Watch the index catch up to you",
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || username.length < 3) return;
    requestSignup.mutate({ email, username }, { onSuccess: () => setCheckInboxFor(email) });
  };

  if (checkInboxFor) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-16 text-center">
        <h1 className="text-2xl font-extrabold tracking-tight">Check your inbox</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          We sent a confirmation link to <span className="font-bold">{checkInboxFor}</span>. Click it to
          finish creating your account and claim your {formatCents(STARTING_BALANCE_CENTS)}.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-5 py-10 text-center sm:py-16">
      <h1 className="text-3xl leading-tight font-extrabold tracking-tight sm:text-4xl">
        Find them first.
        <br />
        Prove it forever.
      </h1>
      <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
        Trade play-money shares in rising artists. Price tracks a real popularity index — being early is
        what pays.
      </p>

      <form onSubmit={handleSubmit} className="flex w-full max-w-xs flex-col gap-3 pt-2">
        <div className="flex flex-col gap-1.5 text-left">
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
        {requestSignup.isError && (
          <p className="text-xs text-destructive">{errorMessage(requestSignup.error)}</p>
        )}
        <Button type="submit" size="lg" disabled={requestSignup.isPending}>
          {requestSignup.isPending ? "Sending confirmation…" : `Get started — ${formatCents(STARTING_BALANCE_CENTS)} free`}
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
    </div>
  );
}
