"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { errorMessage } from "@/lib/errors";
import { useConsumeMagicLink } from "@/lib/queries";

// Login magic-link consume. `POST`, not `GET`, per auth.py's own
// reasoning: a bot or link-scanner hitting a bare `GET` must not be able
// to mutate state -- the mutation fires from an effect on mount instead
// of happening as a side effect of routing.
function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const router = useRouter();
  const consume = useConsumeMagicLink();
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    consume.mutate(token, { onSuccess: () => router.replace("/") });
  }, [token, consume, router]);

  if (!token) {
    return <p className="text-sm text-muted-foreground">No token present.</p>;
  }
  if (consume.isError) {
    return (
      <p className="text-sm text-destructive">
        {errorMessage(consume.error, "That link is invalid or expired.")}
      </p>
    );
  }
  return <p className="text-sm text-muted-foreground">Signing you in…</p>;
}

export default function VerifyPage() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-2xl font-bold">Signing you in…</h1>
      <div className="mt-2">
        <Suspense>
          <VerifyContent />
        </Suspense>
      </div>
    </div>
  );
}
