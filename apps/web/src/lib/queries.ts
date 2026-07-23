"use client";

/** Hand-written TanStack Query hooks over the generated `api` client
 * (query keys, cache invalidation) -- this layer is genuinely
 * hand-written, unlike `api.ts`/`schema.d.ts`. Artist/portfolio/trade
 * hooks land in build step 3 alongside the routes that need them. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { components } from "./schema";

export type UserOut = components["schemas"]["UserOut"];

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
