# apps/web — Architecture (rebuild)

`apps/web` is being deleted and rebuilt with a new visual design. This doc is
the lean spec for the rebuild: constraints that don't change, the stack, and
the build order. It's meant to survive the deletion — read it _before_
scaffolding, not after. History and rationale for the old app live in git
(`apps/web/ARCHITECTURE_NOTES.md` at the last commit before deletion) and in
project memory (`project_web_rewrite` / `project_phase5_spa`) if deeper "why"
is ever needed; don't duplicate that here.

## Non-negotiable constraints

These come from the root `CLAUDE.md` / `PLAN.md` and apply regardless of
visual design:

- **Static export SPA.** `next.config.ts` → `output: "export"`. No SSR data
  path, ever — Railway serves the build as static files. Any "just add a
  server action" instinct is wrong for this app.
- **Artist detail can't be a dynamic segment.** Static export requires
  `generateStaticParams` to enumerate every path at build time, but the
  artist list is DB-driven and grows without a rebuild. Use a query-param or
  client-resolved route (`/artist?slug=x`), not `/artist/[slug]`.
- **Cross-origin, same-site cookie auth.** Web and API are always same-site
  (subdomains of one registrable domain in prod; `localhost:3000`/`:8000`
  locally — port doesn't affect `SameSite`). Every fetch needs
  `credentials: "include"` explicitly. Cookies are `SameSite=Lax` everywhere;
  `Secure` is the only thing that varies (off for plain-HTTP local/test, on
  in prod) — this is already correct in `services/api/.../auth.py`, the
  frontend just needs to not fight it.
- **Integer cents on the client too.** Never float/decimal for price or
  balance math; format at render only (one `formatCents` util).
- **Generated API client, never hand-edited.** `openapi-typescript` against
  the live API → `lib/schema.d.ts` + `openapi-fetch` client. Regenerate, don't
  patch.
- **Trade quotes are always server-computed.** No client-side `qty * price`
  estimate — the AMM's slippage/fees make that wrong. Show a loading state.
- **No artist photography; procedural avatars for artists _and_ users.**
  Right-of-publicity constraint from `CLAUDE.md`. Deterministic from a seed
  (name/id), no network request, no stored image. Give artists and users
  visibly different generation styles (e.g. different shape grammar or
  palette rules per entity type) so the two are never confused at a glance.
- **Every artist page carries the "not affiliated with or endorsed by"
  disclaimer.**

## Stack

| Layer         | Choice                                                                                                                                                                                                                                           |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Framework     | Next.js, App Router, static export — latest stable                                                                                                                                                                                               |
| UI runtime    | React — latest stable                                                                                                                                                                                                                            |
| Data fetching | TanStack Query — latest stable, wrapping the generated `openapi-fetch` client                                                                                                                                                                    |
| Styling       | Tailwind CSS v4                                                                                                                                                                                                                                  |
| Components    | shadcn — copy in components as needed (`pnpm dlx shadcn add ...`); it's not a runtime dependency, which is the point: no framework lock-in, fully editable, minimal tech debt                                                                    |
| PWA           | Web manifest + minimal service worker (app-shell caching only)                                                                                                                                                                                   |
| E2E           | Playwright — write fresh specs covering the real signup/magic-link/collision contract against the same backend; the old `apps/web/e2e/` specs are **not** carried forward (see "Carry forward as-is")                                            |
| Deploy        | Railway, Dockerfile-first — carry `railway.json` + `Dockerfile` forward as-is, they bake in several non-obvious static-export-to-`serve` fixes (the `Dockerfile`'s base image has a known vulnerability scan result — see "Carry forward as-is") |

Check actual latest versions at scaffold time rather than pinning them here.

## Design system (single source of truth)

The goal: change a font or color once and have it apply everywhere.

- One tokens file (`globals.css` or `tokens.css`) defines **semantic** CSS
  custom properties — `--color-bg`, `--color-fg`, `--color-primary`,
  `--color-positive` / `--color-destructive` (gains/losses), `--font-heading`,
  `--font-body`, type-scale steps. Components consume these (via Tailwind
  v4's `@theme inline`) or Tailwind utilities that map to them — never a raw
  hex code or literal `font-family` in a component.
- Load fonts via `next/font` (self-hosted, no runtime request, no layout
  shift); swapping a font means changing the `next/font` call + the token
  that references it, nothing downstream.
- Dark mode: class-based (`.dark`), toggle persisted to `localStorage`,
  applied via a `beforeInteractive` inline bootstrap script. This isn't
  optional polish — a statically exported page can't know the visitor's
  theme preference at build time, so without the bootstrap script you get a
  flash of the wrong theme on every load.

## Mobile-first & responsive

- Write unprefixed Tailwind classes for mobile; add `sm:`/`md:`/`lg:` for
  larger breakpoints, never the reverse.
- Minimum 44px touch targets. Respect `env(safe-area-inset-*)` for notches
  once installed as a PWA.

## PWA

- `manifest.json` + icon set, installable on mobile and desktop.
- Service worker caches the static app shell only. Never cache API
  responses — this is a live market; a stale cached price is a bug, not an
  optimization. Network-only for anything under the API origin.
- An offline fallback page for the shell is enough; there's no offline
  trading story.

## Data layer

- `lib/api.ts` (generated `openapi-fetch` client) + `lib/schema.d.ts`
  (generated by `pnpm generate:api`) — regenerate against a running local API,
  never hand-edit either.
- `lib/queries.ts` — hand-written TanStack Query hooks wrapping the generated
  client. This is the only layer that should know about query keys/caching.

## Routes

Carry forward the same route set — the product surface hasn't changed:

`/` (home/onboarding), `/discover`, `/portfolio`, `/leaderboard`,
`/artist` (query-param, per the static-export constraint above), `/admin`
(role-gated via `useMe`), `/auth/verify`, `/auth/verify-signup`.

## Admin

Role-gated, minimal: surface the Phase 3 quarantine queue
(`flagged_artists`), open and cleared, with a per-row clear action.

The role comes from `is_admin` on `UserOut` (`useMe`) — added for this,
since `UserOut` previously carried no role at all. **That gate is
cosmetic**: it hides the nav entry and the queue, while `CurrentAdminDep`
on every `/admin/*` route is the real one. `is_admin` has no self-service
path; `ax promote-admin` is the only grant.

Quarantines never auto-clear — an unattended flag freezes that artist's
fair value indefinitely — so the page states that plainly, and states
that a clear only takes effect at the next nightly recompute.

## Auth contract (backend already ships this — build the UI to match)

Signup is two-step and email is mandatory; there is no "attach email later"
flow to build.

- **`POST /auth/signup`** takes `{email, username?}` and always returns 202
  (anti-enumeration — same shape whether or not the address already has an
  account). If `username` is omitted the server generates one at consume
  time. The client should prefill an editable username suggestion on mount
  (adjective+noun+2-digit suffix, no dependency, no network call —
  `lib/username.ts`, carried forward as-is) so the field is never blank, but
  the user can type over it before submitting.
- Submitting moves the UI to a "check your inbox" state, **not** a session —
  signup no longer authenticates synchronously.
- **`/auth/verify-signup`** (query param `token`) fires `POST
/auth/signup/consume` on mount, same pattern as the existing
  **`/auth/verify`** login-consume route. Both consume endpoints are `POST`,
  not `GET` — a bot or link-scanner hitting a bare `GET` must not be able to
  mutate state.
- **Username collision on consume returns 409** and does _not_ burn the
  token (the email ownership proof still stands). Show an inline "that
  username's taken" retry prefilled with a fresh suggestion, resubmitting
  the **same token** with a new `username` — don't send the user back to the
  start of signup.
- **`PATCH /auth/username`** renames a logged-in user. No dedicated
  settings/profile page is needed for v1 — the reference implementation
  exposed it as a `@username` button on the Portfolio page header opening a
  small rename dialog, which is fine to repeat rather than building a
  settings surface for one field.
- `POST /auth/email` does not exist — do not build an "attach email" screen.

## Leaderboard & discovery

- `GET /leaderboard/{portfolio,scout}` are public endpoints that also accept
  an optional session. Always render the caller's own rank/row ("you") even
  when it falls outside the displayed top 25 — the endpoints return it
  either way; don't hide it behind a "load more."
- Discovery feeds ("fastest growing under $10," "biggest movers," "new
  listings") are **not separate endpoints** — derive them client-side by
  sorting/filtering the same artist list the `/artists` route already
  fetches. Don't go looking for a discovery API.

## Shareable portfolio card

A cheap virality lever, confirmed with the user as mobile-first: render
username/equity/return/holdings onto an offscreen `<canvas>`, then
`navigator.share({ files })` where available (mobile) with a plain image
download as the desktop fallback. No image-generation service/dependency —
canvas is enough.

## Testing

This rebuild is not exempt from tests — write them alongside each step below,
not as a deferred follow-up phase:

- Unit tests for pure helpers (`formatCents`, avatar generation, username
  suggestion, etc.) as they're written.
- Playwright coverage for the signup/magic-link/username-collision contract,
  written fresh against the new UI. The old `e2e/*` specs are not carried
  forward (see "Carry forward as-is") — port their _intent_, not their code.
- The API's `EMAIL_PROVIDER=console` mode (refused whenever `is_production`)
  writes magic-link and signup-verification sends to a JSON-lines file
  instead of calling Resend — this is how a spec gets a real token with no
  inbox. Read the token from that file rather than inventing another way to
  intercept email in tests.
- Known Playwright gotchas from the previous build, worth guarding against
  again: a username `<input maxLength={24}>` silently truncating a generated
  test username; `getByLabel("Email")` matching a dialog's own accessible
  name ambiguously (use `{ exact: true }`); and a page-wide element-count
  assertion (e.g. counting `svg path`s) picking up Next's dev-overlay icons —
  scope such assertions to `main`, not the whole page.

## Build order

1. **Skeleton**: scaffold, design-token infra, PWA shell, generated API
   client, routing shell — structurally complete, deliberately unstyled or
   minimally styled.
2. Auth flow wired to the real endpoints (signup, magic link, session), with
   Playwright coverage landing alongside it, not after.
3. Core routes with real data plumbing, placeholder visuals.
4. Apply the Claude-design visual design on top. Steps 1–3 exist so that
   restyling never requires re-plumbing — don't invest real visual design
   effort before the design file lands.
   Use the claude_design MCP (https://api.anthropic.com/v1/design/mcp, auth via /design-login) to import this project:
   https://claude.ai/design/p/5ae6c253-8c0b-4754-8aff-e4d332068835?file=Artist+Exchange.dc.html
5. Admin page

Implement: Artist Exchange.dc.html

## Carry forward as-is

Only these files survive the rebuild unchanged — everything else in the old
`apps/web` is rebuilt from scratch (notably `lib/avatar.ts`, `lib/errors.ts`,
and `e2e/*` — do not port them, see "Testing"):

- `.env.example`
- `.env.local`
- `Dockerfile` — **known issue**: its base image, `node:20-slim`, scans at 2
  critical / 29 high severity vulnerabilities. Carry the file forward per
  this spec, but that scan result is not resolved by doing so — revisit the
  base image (newer Node, `-alpine`, or distroless) before this ships to
  production.
- `railway.json`
- `lib/username.ts`

Regenerate rather than port: `lib/schema.d.ts`.

## Preserve the _behavior_, rebuild the code

- **`PriceChart`** (market price vs. index fair value) is the product's
  signature UI — whatever replaces it must keep the two-series-diverging
  legibility when both series are shown. Space points by index, not literal
  elapsed time (backfilled/dev history is unevenly spaced; time-based x-axis
  misrepresents it).
- **The fair-value series is user-toggleable and off by default.** Default
  view is market price alone; a visible control on the chart itself (not
  buried in a settings page) reveals the index fair-value line on demand.
  Persist the choice the same way as the dark-mode preference
  (`localStorage`), so a user who opts in doesn't have to re-toggle every
  visit. Rationale/tradeoff for defaulting off — and the tension with
  `CONCEPT.md`'s "signature visual" framing — is discussed in project memory
  (`project_web_rewrite`); don't re-litigate it here.
- Username generation stays duplicated client (prefill suggestion) and
  server (`username_gen.py`, source of truth) — not a bug to fix by sharing
  code across languages.
