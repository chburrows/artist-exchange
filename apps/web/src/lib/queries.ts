"use client";

/** Hand-written TanStack Query hooks over the generated `api` client
 * (query keys, cache invalidation) -- this layer is genuinely
 * hand-written, unlike `api.ts`/`schema.d.ts`. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { components } from "./schema";

export type ArtistOut = components["schemas"]["ArtistOut"];
export type HistoryPoint = components["schemas"]["HistoryPoint"];
export type UserOut = components["schemas"]["UserOut"];
export type PortfolioPosition = components["schemas"]["PortfolioPosition"];
export type TradeSide = components["schemas"]["TradeSide"];
export type QuoteResponse = components["schemas"]["QuoteResponse"];

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) throw result.error;
  if (result.data === undefined) throw new Error("empty response");
  return result.data;
}

// --- auth -----------------------------------------------------------------

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

export function useSignup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (username: string) =>
      unwrap(await api.POST("/auth/signup", { body: { username } })),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data.user);
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
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
      queryClient.removeQueries({ queryKey: ["portfolio"] });
    },
  });
}

export function useRequestMagicLink() {
  return useMutation({
    mutationFn: async (email: string) =>
      unwrap(await api.POST("/auth/magic-link", { body: { email } })),
  });
}

export function useConsumeMagicLink() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (token: string) =>
      unwrap(await api.GET("/auth/magic-link/consume", { params: { query: { token } } })),
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data.user);
    },
  });
}

// --- artists ----------------------------------------------------------------

export function useArtists(tier?: "growth" | "blue_chip") {
  return useQuery({
    queryKey: ["artists", tier ?? "all"],
    queryFn: async () =>
      unwrap(await api.GET("/artists", { params: { query: tier ? { tier } : {} } })),
    staleTime: 15_000,
  });
}

export function useArtist(slug: string | null) {
  return useQuery({
    queryKey: ["artist", slug],
    queryFn: async () => unwrap(await api.GET("/artists/{slug}", { params: { path: { slug: slug! } } })),
    enabled: !!slug,
    staleTime: 10_000,
  });
}

export function useArtistHistory(slug: string | null) {
  return useQuery({
    queryKey: ["artist-history", slug],
    queryFn: async () =>
      unwrap(await api.GET("/artists/{slug}/history", { params: { path: { slug: slug! } } })),
    enabled: !!slug,
    staleTime: 10_000,
  });
}

// --- portfolio ----------------------------------------------------------------

export function usePortfolio(enabled: boolean) {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: async () => unwrap(await api.GET("/portfolio")),
    enabled,
    staleTime: 5_000,
  });
}

// --- trades ----------------------------------------------------------------

export interface TradeInput {
  artistSlug: string;
  side: TradeSide;
  shares: number;
}

/** A live preview, re-fetched as the trade ticket's side/shares change --
 * modeled as a query (cached, refetch-on-change) even though the
 * endpoint is a POST, since it has no side effects. `null` input (e.g.
 * shares not yet a positive number) disables the fetch entirely rather
 * than quoting a meaningless trade. */
export function useTradeQuote(input: TradeInput | null) {
  return useQuery({
    queryKey: ["trade-quote", input?.artistSlug, input?.side, input?.shares],
    queryFn: async () =>
      unwrap(
        await api.POST("/trades/quote", {
          body: { artist_slug: input!.artistSlug, side: input!.side, shares: input!.shares },
        }),
      ),
    enabled: !!input && input.shares > 0,
    staleTime: 0,
    retry: false,
  });
}

export function useExecuteTrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ artistSlug, side, shares }: TradeInput) =>
      unwrap(
        await api.POST("/trades", {
          body: {
            artist_slug: artistSlug,
            side,
            shares,
            idempotency_key: crypto.randomUUID(),
          },
        }),
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["artist", variables.artistSlug] });
      queryClient.invalidateQueries({ queryKey: ["artist-history", variables.artistSlug] });
      queryClient.invalidateQueries({ queryKey: ["artists"] });
    },
  });
}
