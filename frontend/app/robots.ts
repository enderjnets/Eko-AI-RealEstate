import type { MetadataRoute } from "next";

import { BRAND_URL, PUBLIC_PATHS } from "@/lib/hosts";

/**
 * `/robots.txt` — and the one honest thing it is here to do is name the
 * sitemap.
 *
 * ── What this is NOT for ─────────────────────────────────────────────────
 * It is not a way to keep anything out of Google. Cloudflare prepends its own
 * Content Signals block to whatever the app serves, and where two groups
 * disagree Google applies the least restrictive rule — that has already
 * happened on this infrastructure, on the Zorros staging site, where a
 * `Disallow: /` sat in the served file and was inert. `lib/hosts.ts` says the
 * same thing at the top. Keeping the panel out of the index is done by the
 * middleware's redirects and by canonical tags, not here.
 *
 * Measured on 16-sep-2026: the served `robots.txt` was 1,248 bytes of
 * Cloudflare's comments and **zero directives**, because the app had no
 * `robots.ts` at all. So a `Sitemap:` line is new information rather than a
 * contested one — nothing to lose a merge against.
 *
 * Whether it survives the edge has to be read from the served file after
 * deploying, never from this source. If Cloudflare drops it, the sitemap is
 * still reachable and can be submitted by hand in Search Console.
 *
 * ── Unset means do nothing ───────────────────────────────────────────────
 * With no brand domain configured there is no absolute sitemap URL to name,
 * and a `Sitemap:` line pointing at a guessed origin is worse than none.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: PUBLIC_PATHS },
    ...(BRAND_URL ? { sitemap: `${BRAND_URL}/sitemap.xml` } : {}),
  };
}
