import { cn } from "@/lib/utils";

/** The Artist Exchange mark: a faceted pentagon in the grow-accent,
 * optionally with the wordmark. The polygon geometry is the brand's
 * signature and appears anywhere the app names itself. */
export function BrandMark({
  size = 20,
  withWordmark = true,
  className,
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" className="shrink-0">
        <polygon points="10,1 18,7 15,19 5,19 2,7" className="fill-primary" />
      </svg>
      {withWordmark && (
        <span className="font-heading text-[0.95rem] font-bold tracking-tight whitespace-nowrap">
          Artist Exchange
        </span>
      )}
    </span>
  );
}
