"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { useConsumeSignup } from "@/lib/queries";
import { generateUsername } from "@/lib/username";

// The exact `detail` string `POST /auth/signup/consume` responds with on
// a 409 for a caller-chosen username (`api/routers/auth.py`) -- matched
// by text rather than status code because `unwrap()` (queries.ts) only
// ever throws the parsed error body, not the response object.
const USERNAME_TAKEN_DETAIL = "username already taken";

function VerifySignupContent() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const consume = useConsumeSignup();
  const attempted = useRef(false);
  const [retryUsername, setRetryUsername] = useState(generateUsername);
  // Set from the mutation's own onError, not derived from consume.isError --
  // that flag resets to false the instant a retry's mutate() is called,
  // which would otherwise unmount this form and flash the generic
  // "Confirming your account…" message for the duration of the request.
  const [showConflictForm, setShowConflictForm] = useState(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    consume.mutate(
      { token },
      {
        onSuccess: () => router.replace("/"),
        onError: (error) => setShowConflictForm(errorMessage(error, "") === USERNAME_TAKEN_DETAIL),
      },
    );
  }, [token, consume, router]);

  if (!token) return <Message text="No token present." />;

  if (showConflictForm) {
    const handleRetry = (e: React.FormEvent) => {
      e.preventDefault();
      consume.mutate(
        { token, username: retryUsername },
        {
          onSuccess: () => router.replace("/"),
          onError: (error) =>
            setShowConflictForm(errorMessage(error, "") === USERNAME_TAKEN_DETAIL),
        },
      );
    };
    return (
      <div className="animate-pop-in mx-auto flex max-w-xs flex-col gap-4 py-20 text-center">
        <BrandMark size={40} withWordmark={false} className="mx-auto" />
        <p className="text-muted-foreground text-sm">That username&apos;s taken. Try another:</p>
        <form onSubmit={handleRetry} className="flex flex-col gap-3 text-left">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="retry-username">Username</Label>
            <Input
              id="retry-username"
              value={retryUsername}
              onChange={(e) => setRetryUsername(e.target.value)}
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9_\-]{3,24}"
              required
            />
          </div>
          <Button type="submit" disabled={consume.isPending}>
            {consume.isPending ? "Trying…" : "Try this username"}
          </Button>
        </form>
      </div>
    );
  }

  if (consume.isError) {
    return (
      <div className="animate-pop-in flex flex-col items-center gap-3 py-20 text-center">
        <Message text={errorMessage(consume.error, "This link is invalid or expired.")} />
        <Link href="/" className="text-primary text-sm font-bold">
          Back to signup →
        </Link>
      </div>
    );
  }

  return (
    <div className="animate-pop-in mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
      <BrandMark size={44} withWordmark={false} className="animate-pulse-glow" />
      <p className="text-muted-foreground text-sm">Confirming your account…</p>
    </div>
  );
}

function Message({ text }: { text: string }) {
  return <p className="text-muted-foreground py-20 text-center text-sm">{text}</p>;
}

export default function VerifySignupPage() {
  return (
    <Suspense fallback={<Message text="Confirming your account…" />}>
      <VerifySignupContent />
    </Suspense>
  );
}
