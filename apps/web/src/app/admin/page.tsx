import { ShieldIcon } from "@/components/icons";

export default function AdminPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="font-heading flex items-center gap-2 text-2xl font-bold">
        <ShieldIcon className="text-violet text-2xl" />
        Admin
      </h1>
      <div className="border-border bg-card text-muted-foreground rounded-2xl border p-5 text-sm leading-relaxed">
        <p>
          The role-gated quarantine queue (<code className="font-mono text-xs">flagged_artists</code>) lands
          in build step 5. There is no clearing mechanism yet — quarantines never auto-clear, which the
          review UI will need to acknowledge.
        </p>
      </div>
    </div>
  );
}
