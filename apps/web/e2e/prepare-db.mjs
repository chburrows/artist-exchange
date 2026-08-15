#!/usr/bin/env node
/**
 * Resets and reseeds the database before the e2e suite runs, via the
 * real `ax reset` CLI -- not Playwright's `globalSetup`, deliberately:
 * `globalSetup` isn't guaranteed to finish before `webServer` starts
 * talking to the database, and `ax reset` does a `DROP SCHEMA public
 * CASCADE`. Running it as its own step before `playwright test` is even
 * invoked (see package.json's `e2e` script) guarantees the schema is
 * stable before either server starts.
 */
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// Mirrors e2e/config.ts -- duplicated, not imported, since this file
// runs under plain Node (before `playwright test`) and can't load
// TypeScript without extra tooling for three constants.
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange";
const EMAIL_LOG_PATH = process.env.EMAIL_LOG_PATH ?? "/tmp/ax-e2e-email-log.jsonl";

fs.rmSync(EMAIL_LOG_PATH, { force: true });

console.log(`[e2e] resetting ${DATABASE_URL} via \`uv run ax reset\`...`);
execSync("uv run ax reset --users 5 --days 12 --seed 4242", {
  cwd: REPO_ROOT,
  stdio: "inherit",
  env: { ...process.env, DATABASE_URL },
});
console.log("[e2e] database ready.");
