/** Shared port/URL resolution for the Playwright config, prepare-db
 * script, and every spec -- one place so the three never drift out of
 * agreement about where the API and web servers actually are. */

export const API_PORT = process.env.E2E_API_PORT ?? "8000";
export const WEB_PORT = process.env.E2E_WEB_PORT ?? "3000";
export const API_BASE_URL = `http://localhost:${API_PORT}`;
export const WEB_BASE_URL = `http://localhost:${WEB_PORT}`;

// `ConsoleEmailProvider` (services/api/src/ax/providers/email.py) writes
// every "sent" message here instead of calling Resend -- this is how
// specs needing a real, consumable token get one without a real inbox.
// Nothing in production ever sets EMAIL_PROVIDER=console, so this path
// only exists for local dev and this test run.
export const EMAIL_LOG_PATH = process.env.EMAIL_LOG_PATH ?? "/tmp/ax-e2e-email-log.jsonl";

export const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql+psycopg://postgres:postgres@localhost:5432/artist_exchange";
