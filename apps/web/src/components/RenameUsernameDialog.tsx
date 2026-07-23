"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { useUpdateUsername } from "@/lib/queries";

/** `PATCH /auth/username` has no dedicated settings page (ARCHITECTURE.md)
 * -- the reference implementation's `@username` button on the Portfolio
 * page header opening this dialog is the whole surface for v1. */
export function RenameUsernameDialog({
  currentUsername,
  open,
  onOpenChange,
}: {
  currentUsername: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [username, setUsername] = useState(currentUsername);
  const updateUsername = useUpdateUsername();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.length < 3) return;
    updateUsername.mutate(username, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          updateUsername.reset();
          setUsername(currentUsername);
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change username</DialogTitle>
          <DialogDescription>This is how you appear on leaderboards.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rename-username">Username</Label>
            <Input
              id="rename-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9_\-]{3,24}"
              required
            />
          </div>
          {updateUsername.isError && (
            <p className="text-xs text-destructive">{errorMessage(updateUsername.error)}</p>
          )}
          <Button type="submit" disabled={updateUsername.isPending}>
            {updateUsername.isPending ? "Saving…" : "Save"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
