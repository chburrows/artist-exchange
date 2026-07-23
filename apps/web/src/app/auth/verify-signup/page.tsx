"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

// Signup verify-then-create. Fires `POST /auth/signup/consume` on mount
// once wired in build step 2; a 409 username collision resubmits the
// same token with a new username rather than restarting signup.
function VerifySignupContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  return (
    <div>
      <h1 className="text-2xl font-bold">Confirming your account…</h1>
      <p className="text-muted-foreground mt-2">
        {token ? "Consuming signup token…" : "No token present."} Real consume call and the
        username-collision retry land in build step 2.
      </p>
    </div>
  );
}

export default function VerifySignupPage() {
  return (
    <Suspense>
      <VerifySignupContent />
    </Suspense>
  );
}
