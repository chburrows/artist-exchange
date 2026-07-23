"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

// Not a dynamic segment: static export requires `generateStaticParams` to
// enumerate every path at build time, but the artist list is DB-driven
// and grows without a rebuild. Query-param route instead, per
// ARCHITECTURE.md.
function ArtistPageContent() {
  const searchParams = useSearchParams();
  const slug = searchParams.get("slug");

  return (
    <div>
      <h1 className="text-2xl font-bold">Artist{slug ? `: ${slug}` : ""}</h1>
      <p className="text-muted-foreground mt-2">
        Price chart, trade ticket, and the &quot;not affiliated with or endorsed by&quot;
        disclaimer. Real data plumbing lands in build step 3.
      </p>
    </div>
  );
}

export default function ArtistPage() {
  return (
    <Suspense>
      <ArtistPageContent />
    </Suspense>
  );
}
