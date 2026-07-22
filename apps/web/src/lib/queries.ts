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
export type FlaggedArtistOut = components["schemas"]["FlaggedArtistOut"];
export type EquityPoint = components["schemas"]["EquityPoint"];
export type PortfolioLeaderboardRow = components["schemas"]["PortfolioLeaderboardRow"];
export type ScoutLeaderboardRow = components["schemas"]["ScoutLeaderboardRow"];

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

/** Request step of Phase 7's verify-before-create signup -- queues a
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

export function useUpdateUsername() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (username: string) =>
      unwrap(await api.PATCH("/auth/username", { body: { username } })),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
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
      unwrap(await api.POST("/auth/magic-link/consume", { body: { token } })),
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

/** Real daily equity history (PLAN.md Phase 6), written nightly by
 * `jobs/leaderboard.py` -- empty for an account that predates tonight's
 * first run. `PortfolioValueChart` already renders an honest "not enough
 * history yet" state for fewer than two points, so an empty array needs
 * no special handling here. */
export function usePortfolioHistory(enabled: boolean) {
  return useQuery({
    queryKey: ["portfolio-history"],
    queryFn: async () => unwrap(await api.GET("/portfolio/history")),
    enabled,
    staleTime: 60_000,
  });
}

// --- leaderboards (PLAN.md Phase 6) ------------------------------------
//
// Both public: browsable with no account. Reads a table `jobs/leaderboard.py`
// refreshes once a night -- staleness up to a day old is expected, not a
// bug (PLAN.md: "leaderboards are the one place staleness is genuinely
// fine"). `you` comes back populated whenever the caller has a session
// and a snapshot exists for them, even if they fall outside `rows`.

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

// --- admin (oracle-manipulation review queue) --------------------------------
//
// A 401/403 here isn't an error state to retry -- it means "not logged in"
// or "not an admin," both of which the page itself renders explicitly
// (`useMe` already tells it which). `retry: false` avoids hammering the
// endpoint with doomed retries in either case.

export class ForbiddenError extends Error {}

export function useFlaggedArtists(enabled: boolean) {
  return useQuery({
    queryKey: ["admin", "flagged-artists"],
    queryFn: async (): Promise<FlaggedArtistOut[]> => {
      const { data, error, response } = await api.GET("/admin/flagged-artists");
      // 403 (logged in, not an admin) is a state the page renders
      // explicitly, not a transient failure -- a distinct error type lets
      // it tell that apart from a real fetch failure. 401 can't happen
      // here: `enabled` only turns this query on once `useMe` confirms a
      // session exists, mirroring `usePortfolio`.
      if (response.status === 403) throw new ForbiddenError();
      if (error) throw error;
      return data ?? [];
    },
    enabled,
    staleTime: 5_000,
    retry: false,
  });
}

export function useClearFlaggedArtist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ artistId, asOfDate }: { artistId: number; asOfDate: string }) =>
      unwrap(
        await api.POST("/admin/flagged-artists/{artist_id}/{as_of_date}/clear", {
          params: { path: { artist_id: artistId, as_of_date: asOfDate } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "flagged-artists"] });
    },
  });
}
