import { expect, test } from "@playwright/test";

import { API_BASE_URL } from "./config";

test("artist page renders both the market price and fair value series", async ({ page }) => {
  const artists: { slug: string; name: string }[] = await (
    await page.request.get(`${API_BASE_URL}/artists`)
  ).json();
  expect(artists.length).toBeGreaterThan(0);
  const artist = artists[0];

  await page.goto(`/artist?slug=${artist.slug}`);

  await expect(page.getByText("Market price")).toBeVisible();
  await expect(page.getByText("Index fair value")).toBeVisible();
  // The signature dual-line chart (PLAN.md): solid market price plus
  // dashed index fair value -- every listed artist has at least a
  // listing-day point for both, so this holds regardless of which
  // artist sorted first. Scoped to `main`, not the whole page: Next's
  // dev-mode overlay button can inject its own <svg><path> icon outside
  // `main`, which a page-wide locator would count too.
  await expect(page.locator("main svg path")).toHaveCount(2);
});
