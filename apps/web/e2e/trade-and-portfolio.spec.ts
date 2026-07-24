import { expect, test } from "@playwright/test";

import { lastLinkFor } from "./email";

/** Signup through to a real trade against the seeded artist universe
 * (`e2e/prepare-db.mjs` runs `ax reset` before this suite starts) --
 * covers the core-routes data plumbing landing in build step 3:
 * discover -> artist quote/execute -> portfolio reflects the fill. */
test("buying an artist from its page updates the portfolio", async ({ page }) => {
  const email = `trade_${Date.now()}@example.com`;
  const username = `trader${Date.now() % 100000}`;

  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();
  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  await page.goto("/discover");
  const firstArtist = page.locator("main a[href^='/artist?slug=']").first();
  const artistName = await firstArtist.locator("span").first().innerText();
  await firstArtist.click();

  await expect(page.getByRole("button", { name: "Confirm buy" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm buy" }).click();
  await expect(page.getByText(/^Bought 1 share/)).toBeVisible();

  await page.goto("/portfolio");
  await expect(page.locator("main").getByText(artistName)).toBeVisible();
  await expect(page.getByText(/1 share · avg cost/)).toBeVisible();
});

test("leaderboard renders both the portfolio and scout rankings", async ({ page }) => {
  await page.goto("/leaderboard");
  await expect(page.getByRole("heading", { name: "Leaderboard" })).toBeVisible();
  await expect(page.locator("main").getByText(/^#1$/)).toBeVisible();

  await page.getByRole("button", { name: "Talent Scout" }).click();
  await expect(page.locator("main").getByText(/^#1$/)).toBeVisible();
});
