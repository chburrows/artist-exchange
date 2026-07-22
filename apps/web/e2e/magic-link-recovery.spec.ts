import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { API_BASE_URL, EMAIL_LOG_PATH } from "./config";

/** Pulls the most recent magic-link URL sent to `email` out of
 * `ConsoleEmailProvider`'s log file -- the e2e equivalent of
 * `tests/conftest.py`'s `FakeEmailProvider.last_link()` in the Python
 * suite, reading the real (dev-only) provider's output instead of an
 * in-process fake. */
function lastLinkFor(email: string): string {
  const lines = fs.readFileSync(EMAIL_LOG_PATH, "utf-8").trim().split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const entry: { to: string; html: string } = JSON.parse(lines[i]);
    if (entry.to === email) {
      const match = entry.html.match(/href="([^"]+)"/);
      if (!match) throw new Error(`no link found in the email sent to ${email}`);
      return match[1];
    }
  }
  throw new Error(`no email found for ${email} in ${EMAIL_LOG_PATH}`);
}

test("magic-link recovery signs you back in on a fresh session", async ({ page }) => {
  // Kept within the username input's `maxLength={24}` (OnboardingScreen)
  // -- "e2e_recover_" plus a 13-digit `Date.now()` was silently truncated
  // by the browser, so the account's real username came back one
  // character shorter than this test's own assertion expected.
  const username = `e2r_${Date.now()}`;
  const email = `${username}@example.com`;

  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  // There's no "attach email" UI yet (only recovery -- SignInPanel), so
  // attaching one is test setup for the flow under test, done against
  // the real endpoint using this page's own session cookie, not the flow
  // this spec is actually verifying.
  const attachStatus = await page.evaluate(
    async ({ apiBaseUrl, email }) => {
      const res = await fetch(`${apiBaseUrl}/auth/email`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      return res.status;
    },
    { apiBaseUrl: API_BASE_URL, email },
  );
  expect(attachStatus).toBe(202);

  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  // The actual recovery flow: log out, then request and follow a
  // sign-in link through the real SignInPanel UI.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();

  await page.getByRole("button", { name: "I already have an account" }).click();
  // Not `exact: false` (the default): the dialog's own accessible name
  // ("Sign in with email", from its DialogTitle) also substring-matches
  // "Email" and resolves ambiguously alongside the real input.
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Send sign-in link" }).click();
  await expect(page.getByText(/sign-in link is on its way/)).toBeVisible();

  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();
});
