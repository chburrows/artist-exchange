import { expect, test } from "@playwright/test";

import { API_BASE_URL } from "./config";
import { lastLinkFor } from "./email";

test("claim a username, buy a share, and see the position in your portfolio", async ({ page }) => {
  const username = `e2e_${Date.now()}`;
  const email = `${username}@example.com`;

  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();

  // Phase 7: signup only creates the account once the emailed
  // confirmation link is followed.
  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();

  // A real listed artist from `ax reset`'s seeded universe -- not
  // hardcoded, since the curated seed can change.
  const artists: { slug: string; name: string }[] = await (
    await page.request.get(`${API_BASE_URL}/artists`)
  ).json();
  expect(artists.length).toBeGreaterThan(0);
  const artist = artists[0];

  await page.goto(`/artist?slug=${artist.slug}`);
  await expect(page.getByRole("heading", { name: artist.name, level: 1 })).toBeVisible();

  // Trim the ticket's default qty (10) down to 1 -- the smallest trade
  // that can never trip a slippage/exposure guardrail regardless of
  // which artist happened to sort first, since this spec is testing the
  // buy-then-see-it-in-your-portfolio wiring, not guardrail sizing.
  const decrease = page.getByRole("button", { name: "Decrease shares" });
  for (let i = 0; i < 9; i++) await decrease.click();

  await page.getByRole("button", { name: "Buy 1 share" }).click();
  await expect(page.getByText(/^Bought 1 share at/)).toBeVisible();

  await page.goto("/portfolio");
  await expect(page.getByText(artist.name)).toBeVisible();
  await expect(page.getByText("1 sh ·")).toBeVisible();
});
