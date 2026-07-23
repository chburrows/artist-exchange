"use client";

/** Hand-written TanStack Query hooks over the generated `api` client
 * (query keys, cache invalidation) -- this layer is genuinely
 * hand-written, unlike `api.ts`/`schema.d.ts`. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { components } from "./schema";

export type UserOut = components["schemas"]["UserOut"];
export type ArtistOut = components["schemas"]["ArtistOut"];
export type HistoryPoint = components["schemas"]["HistoryPoint"];
export type PortfolioResponse = components["schemas"]["PortfolioResponse"];
export type EquityPoint = components["schemas"]["EquityPoint"];
export type QuoteResponse = components["schemas"]["QuoteResponse"];
export type TradeSide = components["schemas"]["TradeSide"];

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) throw result.error;
  if (result.data === undefined) throw new Error("empty response");
  return result.data;
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async (): Promise<UserOut | null> => {
      const { data, error, response } = await api.GET("/auth/me");
      if (response.status === 401) return null;
      if (error) throw error;
      return data ?? null;
    },
    staleTime: 60_000,
    retry: false,
  });
}

/** Request step of verify-before-create signup -- queues a
 * `pending_signups` row and emails a confirm link. No session yet: that
 * only happens once the link is consumed (`useConsumeSignup`). */
export function useRequestSignup() {
  return useMutation({
    mutationFn: async (body: { email: string; username?: string }) =>
      unwrap(await api.POST("/auth/signup", { body })),
  });
}

/** Consume step: creates the account, grants the starting balance, and
 * opens the session, all at once. `username` is only sent when the
 * caller is overriding a 409'd suggestion -- omitted on the first try. */
export function useConsumeSignup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { token: string; username?: string }) =>
      unwrap(await api.POST("/auth/signup/consume", { body })),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data.user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/auth/logout");
      if (error) throw error;
    },
    onSuccess: () => {
      queryClient.setQueryData(["me"], null);
    },
  });
}

export function useRequestMagicLink() {
  return useMutation({
    mutationFn: async (email: string) => unwrap(await api.POST("/auth/magic-link", { body: { email } })),
  });
}

export function useConsumeMagicLink() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (token: string) =>
      unwrap(await api.POST("/auth/magic-link/consume", { body: { token } })),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data.user);
    },
  });
}

export function useUpdateUsername() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (username: string) =>
      unwrap(await api.PATCH("/auth/username", { body: { username } })),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data);
    },
  });
}

/** Public: browsing the universe needs no account (`artists.py`). */
export function useArtists(tier?: string) {
  return useQuery({
    queryKey: ["artists", tier ?? null],
    queryFn: async (): Promise<ArtistOut[]> =>
      unwrap(await api.GET("/artists", { params: { query: { tier: tier ?? undefined } } })),
    staleTime: 30_000,
  });
}

export function useArtistHistory(slug: string | null) {
  return useQuery({
    queryKey: ["artist-history", slug],
    queryFn: async () =>
      unwrap(await api.GET("/artists/{slug}/history", { params: { path: { slug: slug ?? "" } } })),
    enabled: slug !== null,
    staleTime: 10_000,
  });
}

/** Gated by `enabled` rather than skipped outright -- callers pass
 * `!!me.data` so the hook order stays stable whether or not a session
 * exists yet (`useMe` may still be loading on first render). */
export function usePortfolio(enabled: boolean) {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: async (): Promise<PortfolioResponse> => unwrap(await api.GET("/portfolio")),
    enabled,
  });
}

export function usePortfolioHistory(enabled: boolean) {
  return useQuery({
    queryKey: ["portfolio-history"],
    queryFn: async (): Promise<EquityPoint[]> => unwrap(await api.GET("/portfolio/history")).points,
    enabled,
  });
}

/** Public: `leaderboard.py` accepts an optional session just to surface
 * `you` -- no auth required to view the rankings themselves. */
export function usePortfolioLeaderboard() {
  return useQuery({
    queryKey: ["leaderboard", "portfolio"],
    queryFn: async () => unwrap(await api.GET("/leaderboard/portfolio")),
    staleTime: 60_000,
  });
}

export function useScoutLeaderboard() {
  return useQuery({
    queryKey: ["leaderboard", "scout"],
    queryFn: async () => unwrap(await api.GET("/leaderboard/scout")),
    staleTime: 60_000,
  });
}

export type TradeQuoteInput = { artist_slug: string; side: TradeSide; shares: number };

/** Read-only preview -- `trades.py` takes no lock and writes nothing, so
 * this is a plain mutation (fires on demand) rather than a query keyed
 * off the input, even though nothing here mutates the trade tables. */
export function useQuoteTrade() {
  return useMutation({
    mutationFn: async (body: TradeQuoteInput): Promise<QuoteResponse> => unwrap(await api.POST("/trades/quote", { body })),
  });
}

export function useExecuteTrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: TradeQuoteInput & { idempotency_key?: string }) =>
      unwrap(await api.POST("/trades", { body })),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-history"] });
      queryClient.invalidateQueries({ queryKey: ["artist-history", variables.artist_slug] });
      queryClient.invalidateQueries({ queryKey: ["artists"] });
    },
  });
}
