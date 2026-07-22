import { expect, test } from "@playwright/test";

import { lastLinkFor } from "./email";

test("magic-link recovery signs you back in on a fresh session", async ({ page }) => {
  // Kept within the username input's `maxLength={24}` (OnboardingScreen)
  // -- "e2e_recover_" plus a 13-digit `Date.now()` was silently truncated
  // by the browser, so the account's real username came back one
  // character shorter than this test's own assertion expected.
  const username = `e2r_${Date.now()}`;
  const email = `${username}@example.com`;

  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();

  // Phase 7: email is mandatory and verified at signup itself, so there's
  // no separate "attach an email" setup step here anymore -- the account
  // already has the address the recovery flow below sends a link to.
  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  // The actual recovery flow: log out, then request and follow a
  // sign-in link through the real SignInPanel UI.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();

  await page.getByRole("button", { name: "I already have an account" }).click();
  // Scoped to the dialog: the onboarding screen behind it now has its own
  // "Email" field too (Phase 7), so an unscoped `getByLabel("Email")`
  // would resolve ambiguously between the two.
  await page.getByRole("dialog").getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send sign-in link" }).click();
  await expect(page.getByText(/sign-in link is on its way/)).toBeVisible();

  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();
});
