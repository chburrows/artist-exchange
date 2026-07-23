"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

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

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    consume.mutate({ token }, { onSuccess: () => router.replace("/") });
  }, [token, consume, router]);

  if (!token) return <Message text="No token present." />;

  const isUsernameConflict = consume.isError && errorMessage(consume.error, "") === USERNAME_TAKEN_DETAIL;

  if (isUsernameConflict) {
    const handleRetry = (e: React.FormEvent) => {
      e.preventDefault();
      consume.mutate({ token, username: retryUsername }, { onSuccess: () => router.replace("/") });
    };
    return (
      <div className="mx-auto flex max-w-xs flex-col gap-3 py-16 text-center">
        <p className="text-sm text-muted-foreground">That username&apos;s taken. Try another:</p>
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
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <Message text={errorMessage(consume.error, "This link is invalid or expired.")} />
        <Link href="/" className="text-sm font-bold text-primary">
          Back to signup →
        </Link>
      </div>
    );
  }

  return <Message text="Confirming your account…" />;
}

function Message({ text }: { text: string }) {
  return <p className="py-16 text-center text-sm text-muted-foreground">{text}</p>;
}

export default function VerifySignupPage() {
  return (
    <Suspense fallback={<Message text="Confirming your account…" />}>
      <VerifySignupContent />
    </Suspense>
  );
}
