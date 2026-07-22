"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { useRequestMagicLink } from "@/lib/queries";

/** "I already have an account" -- signup has no password, so returning
 * on a new session means either the still-live session cookie (the
 * common case) or a magic link to the email verified at signup
 * (`auth.py`: `POST /auth/magic-link`). This dialog only covers
 * requesting that link; consuming it happens on `/auth/verify`. */
export function SignInPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [email, setEmail] = useState("");
  const requestLink = useRequestMagicLink();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    requestLink.mutate(email);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) requestLink.reset();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Sign in with email</DialogTitle>
          <DialogDescription>
            Only works if you&apos;ve attached an email to your account before. We&apos;ll send a
            one-time link.
          </DialogDescription>
        </DialogHeader>

        {requestLink.isSuccess ? (
          <p className="text-sm text-positive">
            If that email is registered, a sign-in link is on its way.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="signin-email">Email</Label>
              <Input
                id="signin-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </div>
            {requestLink.isError && (
              <p className="text-xs text-destructive">{errorMessage(requestLink.error)}</p>
            )}
            <Button type="submit" disabled={requestLink.isPending}>
              {requestLink.isPending ? "Sending…" : "Send sign-in link"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
