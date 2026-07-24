"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { BrandMark } from "@/components/BrandMark";
import { errorMessage } from "@/lib/errors";
import { useConsumeMagicLink } from "@/lib/queries";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-pop-in mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
      {children}
    </div>
  );
}

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
    return (
      <Shell>
        <h1 className="font-heading text-2xl font-bold">Link invalid</h1>
        <p className="text-muted-foreground text-sm">No token present.</p>
      </Shell>
    );
  }
  if (consume.isError) {
    return (
      <Shell>
        <h1 className="font-heading text-2xl font-bold">Link invalid</h1>
        <p className="text-destructive text-sm">
          {errorMessage(consume.error, "That link is invalid or expired.")}
        </p>
        <Link href="/" className="text-primary text-sm font-bold">
          Back to signup →
        </Link>
      </Shell>
    );
  }
  return (
    <Shell>
      <BrandMark size={44} withWordmark={false} className="animate-pulse-glow" />
      <h1 className="font-heading text-2xl font-bold">Signing you in…</h1>
      <p className="text-muted-foreground text-sm">One second while we open your session.</p>
    </Shell>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <Shell>
          <h1 className="font-heading text-2xl font-bold">Signing you in…</h1>
        </Shell>
      }
    >
      <VerifyContent />
    </Suspense>
  );
}
