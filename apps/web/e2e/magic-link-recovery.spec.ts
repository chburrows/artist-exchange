import { expect, test } from "@playwright/test";

import { lastLinkFor } from "./email";

test("magic-link recovery signs you back in on a fresh session", async ({ page }) => {
  // Kept within the username input's `maxLength={24}` -- a longer prefix
  // plus `Date.now()`'s 13 digits gets silently truncated by the
  // browser, so the account's real username would come back different
  // from what this test expects.
  const username = `e2r_${Date.now()}`;
  const email = `${username}@example.com`;

  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();

  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  // The actual recovery flow: log out, then request and follow a
  // sign-in link through the real SignInPanel UI.
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();

  await page.getByRole("button", { name: "I already have an account" }).click();
  // Scoped to the dialog: the onboarding screen behind it has its own
  // "Email" field too, so an unscoped `getByLabel("Email")` would
  // resolve ambiguously between the two.
  await page.getByRole("dialog").getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send sign-in link" }).click();
  await expect(page.getByText(/sign-in link is on its way/)).toBeVisible();

  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();
});
