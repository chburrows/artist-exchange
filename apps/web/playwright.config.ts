import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { API_BASE_URL, API_PORT, DATABASE_URL, EMAIL_LOG_PATH, WEB_BASE_URL, WEB_PORT } from "./e2e/config";

const REPO_ROOT = path.resolve(__dirname, "../..");

/** PLAN.md's testing strategy: "E2E -- deliberately thin, 4 specs...
 * E2E is for wiring, not logic." Runs against a real API + Postgres
 * (`e2e/prepare-db.mjs` resets and reseeds it before this config's
 * `webServer`s ever start -- see that file's docstring for why it isn't
 * a Playwright `globalSetup` instead), not a mocked backend, so a green
 * run here is the closest thing to "a friend can sign up and trade in a
 * browser" (PLAN.md Phase 5's own "Done when") that a CI job can check
 * unattended. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  // Every spec shares one reset-once database (`ax reset --users 5
  // --days 12`, not a per-test transaction like the Python suite) --
  // running workers in parallel would let two specs' signups/trades
  // interleave unpredictably against the same leaderboard/portfolio
  // state. Four specs is cheap enough to run serially.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: "line",
  use: {
    baseURL: WEB_BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn ax.api.main:app --port ${API_PORT}`,
      cwd: REPO_ROOT,
      url: `${API_BASE_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        DATABASE_URL,
        INTERNAL_JOB_TOKEN: process.env.INTERNAL_JOB_TOKEN ?? "e2e-job-token",
        SESSION_SECRET: process.env.SESSION_SECRET ?? "e2e-session-secret",
        ENVIRONMENT: "local",
        WEB_ORIGIN: WEB_BASE_URL,
        // Real magic-link tokens, no Resend quota or inbox needed -- see
        // e2e/config.ts and ax.providers.email.ConsoleEmailProvider.
        EMAIL_PROVIDER: "console",
        EMAIL_LOG_PATH,
      },
    },
    {
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      cwd: __dirname,
      url: WEB_BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: API_BASE_URL,
      },
    },
  ],
});
