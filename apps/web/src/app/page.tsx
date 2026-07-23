"use client";

import { OnboardingScreen } from "@/components/OnboardingScreen";
import { useMe } from "@/lib/queries";

export default function HomePage() {
  const me = useMe();

  if (me.isLoading) {
    return <p className="py-16 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (!me.data) {
    return <OnboardingScreen />;
  }

  // The real dashboard (equity, holdings, discovery teaser) lands in
  // build step 3 alongside the other data-plumbed routes -- this just
  // proves the session is live.
  return (
    <div>
      <p className="text-sm font-bold text-muted-foreground">Welcome back, {me.data.username}</p>
      <p className="mt-2 text-sm text-muted-foreground">Dashboard lands in build step 3.</p>
    </div>
  );
}
