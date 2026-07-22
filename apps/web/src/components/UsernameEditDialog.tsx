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
import { useUpdateUsername } from "@/lib/queries";

/** The one account-settings surface Phase 7 adds -- no dedicated
 * settings page exists yet, so this hangs off wherever the caller
 * mounts it (the Portfolio page) rather than justifying a new route. */
export function UsernameEditDialog({
  open,
  onOpenChange,
  currentUsername,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentUsername: string;
}) {
  const [username, setUsername] = useState(currentUsername);
  const update = useUpdateUsername();

  // Reset the form each time the dialog transitions closed -> open,
  // without an effect (React's own documented pattern for "adjust state
  // when a prop changes" -- an effect here would setState synchronously
  // on mount and cause an extra cascading render for no benefit).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setUsername(currentUsername);
      update.reset();
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.length < 3) return;
    update.mutate(username, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change your username</DialogTitle>
          <DialogDescription>
            Your old username becomes claimable by someone else right away.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-username">Username</Label>
            <Input
              id="edit-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9_\-]{3,24}"
              required
            />
          </div>
          {update.isError && (
            <p className="text-xs text-destructive">
              {errorMessage(update.error, "That username might be taken -- try another.")}
            </p>
          )}
          <Button type="submit" disabled={update.isPending || username === currentUsername}>
            {update.isPending ? "Saving…" : "Save"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
