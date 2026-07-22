import { expect, test } from "@playwright/test";

test("both leaderboard tabs load real rankings from ax reset's simulated traders", async ({
  page,
}) => {
  await page.goto("/leaderboard");

  await expect(page.getByRole("tab", { name: "Portfolio return" })).toBeVisible();
  // `ax reset --users 5` (e2e/prepare-db.mjs) creates users named
  // sim_0000..sim_0004 and trades through the real ledger/AMM path, so
  // the nightly leaderboard snapshot it also runs has real rows to show.
  await expect(page.getByText(/sim_\d{4}/).first()).toBeVisible();

  await page.getByRole("tab", { name: "Talent Scout" }).click();
  await expect(page.getByText(/sim_\d{4}/).first()).toBeVisible();
});
