/**
 * Which pages a search engine is invited to index, and which are none of its
 * business.
 *
 * ── Why this exists ──────────────────────────────────────────────────────
 * `denverhomestory.com/sitemap.xml` answered 404. Google had found `/` and
 * `/fall` on its own and nothing else, so the page the whole funnel points at
 * — `/calculator` — was not in the index at all. A brand search for "Denver
 * Home Story" returns a different brokerage's business panel.
 *
 * ── The list is derived, never retyped ───────────────────────────────────
 * The entries come from `PUBLIC_PATHS`, the same constant `middleware.ts` uses
 * to decide what the brand hostname is even allowed to serve. A hand-kept
 * second list is how `/brief/<token>` ends up in a sitemap: that token IS the
 * credential for a partner's private answers, and publishing it would hand it
 * to every crawler on the internet. Deriving makes that impossible rather than
 * unlikely — a path has to be public for the panel before it can be listed
 * here.
 *
 * ── Unset means do nothing, not guess ────────────────────────────────────
 * With `NEXT_PUBLIC_BRAND_URL` empty this yields no entries at all, matching
 * the rule `lib/hosts.ts` sets for every value in it. A sitemap is a file of
 * absolute URLs; one built on a guessed origin would either point at a dead
 * domain or, worse, invite Google to index the operator panel under its own
 * hostname. Today's 404 is a better failure than either.
 *
 * ── What is deliberately absent ──────────────────────────────────────────
 * No `lastModified`. Build time is not modification time, and stamping today's
 * date on five pages at every deploy tells Google five things that are not
 * true. An absent field is read as "unknown", which is the honest answer.
 */

/** One entry, shaped as Next's `MetadataRoute.Sitemap` expects. */
export interface SitemapUrl {
  url: string;
  changeFrequency: "daily" | "weekly" | "monthly";
  priority: number;
}

/**
 * How often each page actually changes and how much it matters to the funnel.
 * Anything not named here is a public page that nobody has ranked yet; it is
 * still listed, at the neutral defaults.
 */
const WEIGHT: Record<string, { changeFrequency: SitemapUrl["changeFrequency"]; priority: number }> =
  {
    "/": { changeFrequency: "weekly", priority: 1 },
    // The page eleven Shorts point at, and the one Google has never seen.
    "/calculator": { changeFrequency: "monthly", priority: 0.9 },
    // Where every bio link lands.
    "/start": { changeFrequency: "monthly", priority: 0.8 },
    "/contact": { changeFrequency: "monthly", priority: 0.7 },
    // Seasonal: it stops being true in December.
    "/fall": { changeFrequency: "weekly", priority: 0.6 },
  };

const NEUTRAL = { changeFrequency: "monthly" as const, priority: 0.5 };

/**
 * The sitemap entries for a brand origin and a list of public paths.
 *
 * `brandUrl` is expected without a trailing slash, as `lib/hosts.ts` exports
 * it. An empty origin yields an empty list.
 */
export function sitemapUrls(
  brandUrl: string,
  paths: readonly string[],
): SitemapUrl[] {
  const origin = brandUrl.trim().replace(/\/$/, "");
  if (!origin) return [];

  return paths.map((path) => {
    const weight = WEIGHT[path] ?? NEUTRAL;
    return {
      // `/` would otherwise produce a doubled slash at the end of the origin.
      url: path === "/" ? `${origin}/` : `${origin}${path}`,
      changeFrequency: weight.changeFrequency,
      priority: weight.priority,
    };
  });
}
