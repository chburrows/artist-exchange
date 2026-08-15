import { execFileSync } from "node:child_process";
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DATABASE_URL } from "./config";
import { lastLinkFor } from "./email";

// Playwright transpiles specs to CJS, so `__dirname` is available here
// and `import.meta.url` is not -- unlike `prepare-db.mjs`, which node
// runs as real ESM.
const REPO_ROOT = path.resolve(__dirname, "../../..");
// Absolute, so it does not depend on the working directory `uv` picks.
const FIXTURE = path.join(__dirname, "admin_fixture.py");

// Any date works -- it is only a queue key. Fixed rather than "today" so
// a rerun near midnight can't produce two rows for the same artist.
const FLAG_DATE = "2026-01-01";

function ax(...args: string[]): void {
  execFileSync("uv", ["run", ...args], {
    cwd: REPO_ROOT,
    stdio: "pipe",
    env: { ...process.env, DATABASE_URL },
  });
}

async function signUp(page: Page, username: string): Promise<void> {
  const email = `${username}@example.com`;
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByRole("button", { name: /get started/i }).click();
  await expect(page.getByText(/check your inbox/i)).toBeVisible();
  await page.goto(lastLinkFor(email));
  await expect(page.getByText(`Welcome back, ${username}`)).toBeVisible();
}

/** Grabs a real seeded artist to flag, straight from the list the app
 * itself renders -- no assumption about which slugs `ax seed-artists`
 * happens to ship. */
async function pickArtist(page: Page, index: number): Promise<string> {
  await page.goto("/discover");
  const links = page.locator("main a[href^='/artist?slug=']");
  await expect(links.nth(index)).toBeVisible();
  const href = await links.nth(index).getAttribute("href");
  return decodeURIComponent(new URL(href!, "http://x").searchParams.get("slug")!);
}

/** `is_admin` reaches the client only through `/auth/me` (`UserOut`), and
 * the SPA gate is cosmetic -- the API 403s regardless. This covers the
 * cosmetic half: an ordinary account must see neither the nav entry nor
 * the queue. */
test("a non-admin sees no admin nav entry and is turned away from /admin", async ({ page }) => {
  await signUp(page, `plainuser${Date.now() % 100000}`);

  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.goto("/admin");
  await expect(page.getByText(/this page is for admins/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review queue" })).toHaveCount(0);
});

test("an admin can read a quarantine's detail and clear it", async ({ page }) => {
  const username = `queenadmin${Date.now() % 100000}`;
  await signUp(page, username);

  const slug = await pickArtist(page, 0);

  ax("ax", "promote-admin", "--username", username);
  ax("python", FIXTURE, slug, FLAG_DATE);

  // The session predates the promotion, so `me` is cached as non-admin
  // until it refetches -- a reload is the honest way a real admin would
  // first see the entry.
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin" }).first()).toBeVisible();

  // Keyed on the fixture's own `(slug, date)` pair, never `.first()`:
  // `ax fake-history` leaves its own auto-cleared flags behind, the list
  // is ordered `as_of_date DESC`, and FLAG_DATE is older than every one
  // of them -- so "the first row for this artist" is the wrong row
  // exactly when the artist happens to carry a fake-history flag too.
  const rowFor = (l: string) =>
    page.locator("li", { has: page.getByRole("link", { name: l }) }).filter({ hasText: FLAG_DATE });

  const row = rowFor(slug);
  await expect(row).toBeVisible();
  // Both triggers from the seeded `reason`, plus a flattened detail leaf.
  await expect(row.getByText("Ratio divergence")).toBeVisible();
  await expect(row.getByText("Outlier move")).toBeVisible();
  await expect(row.getByText("ratio_divergence.z")).toBeVisible();
  await expect(row.getByText("4.200")).toBeVisible();

  // Two-step confirm, then the row leaves the open queue.
  await row.getByRole("button", { name: "Clear this flag" }).click();
  await row.getByRole("button", { name: "Yes, clear this flag" }).click();
  await expect(page.getByText(/the queue is clear/i)).toBeVisible();

  // ...and reappears under cleared history, attributed to this admin.
  await page.getByRole("button", { name: "Include cleared" }).click();
  await expect(rowFor(slug).getByText(`Cleared by ${username}`)).toBeVisible();
});

/** `flagged_artists` is keyed `(artist_id, as_of_date)`, so one artist
 * accumulates a row per detection night, and
 * `recompute._unresolved_flagged_artist_ids` keeps the artist
 * quarantined while *any* of them is open. Clearing one row therefore
 * does not lift the quarantine -- the queue has to say so, or an admin
 * reads "cleared" and finds the price still frozen a night later. */
test("a row warns when its artist has other open flags holding the quarantine", async ({
  page,
}) => {
  const username = `multiadmin${Date.now() % 100000}`;
  await signUp(page, username);
  const slug = await pickArtist(page, 1);

  ax("ax", "promote-admin", "--username", username);
  ax("python", FIXTURE, slug, "2026-03-01");
  ax("python", FIXTURE, slug, "2026-04-01");

  await page.goto("/admin");
  const march = page
    .locator("li", { has: page.getByRole("link", { name: slug }) })
    .filter({ hasText: "2026-03-01" });
  await expect(march.getByText("1 other open flag —", { exact: false })).toBeVisible();

  await march.getByRole("button", { name: "Clear this flag" }).click();
  await march.getByRole("button", { name: "Yes, clear this flag" }).click();

  // The surviving row is now the only one, so the warning goes away --
  // and the artist is still in the queue, which is the point.
  const april = page
    .locator("li", { has: page.getByRole("link", { name: slug }) })
    .filter({ hasText: "2026-04-01" });
  await expect(april).toBeVisible();
  await expect(april.getByText("other open", { exact: false })).toHaveCount(0);
});
