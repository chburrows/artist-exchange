"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { ThemeProvider } from "@/lib/theme-context";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AppShell>{children}</AppShell>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
