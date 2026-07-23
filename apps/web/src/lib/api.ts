/**
 * Generated client config. Types come from `schema.d.ts` (regenerate both
 * via `pnpm generate:api` against a running API) -- do not hand-edit
 * business logic here. Hand-written query/mutation hooks that use this
 * client live in `queries.ts`.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const api = createClient<paths>({
  baseUrl,
  // The session cookie is httpOnly and cross-site (static export SPA on
  // a different origin than the API, per CLAUDE.md) -- every request must
  // opt in to sending/receiving it explicitly.
  credentials: "include",
});
