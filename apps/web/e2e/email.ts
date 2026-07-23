import fs from "node:fs";

import { EMAIL_LOG_PATH } from "./config";

/** Pulls the most recent link URL sent to `email` out of
 * `ConsoleEmailProvider`'s log file (services/api/src/ax/providers/
 * email.py) -- how a spec gets a real, consumable magic-link or
 * signup-confirmation token without a real inbox. */
export function lastLinkFor(email: string): string {
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
