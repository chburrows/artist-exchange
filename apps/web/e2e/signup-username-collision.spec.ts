import { expect, test } from "@playwright/test";

import { lastLinkFor } from "./email";

/** PLAN.md Phase 7's own "Done when": a second signup deliberately
 * colliding with an existing username gets a 409 on consume and succeeds
 * on retry with a different one, all against the *same* emailed token
 * (no second email needed). */
test("a colliding username on consume gets a 409 and succeeds after retrying with a new one", async ({
  page,
}) => {
  const base = `e2c_${Date.now()}`;
  const takenUsername = `${base}tkn`;
  const firstEmail = `${base}-first@example.com`;
  const secondEmail = `${base}-second@example.com`;

  // First account really claims the username.
  await page.goto("/");
  await page.getByLabel("Email").fill(firstEmail);
  await page.getByLabel("Username").fill(takenUsername);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();
  await page.goto(lastLinkFor(firstEmail));
  await expect(page.getByText(`Welcome back, ${takenUsername}`)).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();

  // Second signup deliberately reuses the now-taken username.
  await page.getByLabel("Email").fill(secondEmail);
  await page.getByLabel("Username").fill(takenUsername);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();

  await page.goto(lastLinkFor(secondEmail));
  await expect(page.getByText(/that username.s taken/i)).toBeVisible();

  const retryUsername = `${base}rtry`;
  await page.getByLabel("Username").fill(retryUsername);
  await page.getByRole("button", { name: "Try this username" }).click();

  await expect(page.getByText(`Welcome back, ${retryUsername}`)).toBeVisible();
});
