"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { errorMessage } from "@/lib/errors";
import { useConsumeMagicLink } from "@/lib/queries";

function VerifyContent() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const consume = useConsumeMagicLink();
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    consume.mutate(token, {
      onSuccess: () => router.replace("/"),
    });
  }, [token, consume, router]);

  if (!token) return <Message text="Missing or invalid link." />;
  if (consume.isError) {
    return <Message text={errorMessage(consume.error, "This link is invalid or expired.")} />;
  }
  return <Message text="Signing you in…" />;
}

function Message({ text }: { text: string }) {
  return <p className="py-16 text-center text-sm text-muted-foreground">{text}</p>;
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<Message text="Signing you in…" />}>
      <VerifyContent />
    </Suspense>
  );
}
