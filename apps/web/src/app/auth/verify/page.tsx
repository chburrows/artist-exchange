"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

// Login magic-link consume. Fires `POST /auth/magic-link/consume` on
// mount once wired in build step 2 -- a bare GET must not mutate state.
function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  return (
    <div>
      <h1 className="text-2xl font-bold">Signing you in…</h1>
      <p className="text-muted-foreground mt-2">
        {token ? "Consuming magic link…" : "No token present."} Real consume call lands in build
        step 2.
      </p>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyContent />
    </Suspense>
  );
}
