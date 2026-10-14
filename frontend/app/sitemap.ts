import type { MetadataRoute } from "next";

import { BRAND_URL, PUBLIC_PATHS } from "@/lib/hosts";
import { INDEXED as JOURNAL_INDEXED } from "@/lib/journal/publication";
import { sitemapUrls } from "@/lib/sitemap";
import { LEGENDS, LEGENDS_INDEXED } from "@/lib/legends";

/**
 * `/sitemap.xml`, which answered 404 until now.
 *
 * All of the thinking, and all of the tests, live in `lib/sitemap.ts`. This
 * file exists only because Next needs the route to be a default export here.
 *
 * The one subtraction, and it is still DERIVED rather than hand-kept: The
 * Journal has to be public for the panel to serve it — that is what
 * `PUBLIC_PATHS` decides — and the home page now links it, but while its
 * INDEX gate is shut its pages
 * declare `robots: index:false`. Listing a page here and telling the crawler
 * not to index it are opposite instructions, and the sitemap is the one that
 * actively invites the visit. The filter reads the same constant the pages
 * read, so the two can never drift; there is no second list to keep.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  // `/legends` is public so its pages can be served, but it is a prefix with no
  // page of its own, and each legend page says `index: false` while it is
  // shown to Natalia and Robbie — same reasoning as the Journal above.
  // `/start` too: it says `index: false` (it is the bio-link landing, a copy of
  // what the home offers), and listing it asked Google to come and index it.
  const paths = PUBLIC_PATHS.filter((p) => (p !== "/blog" || JOURNAL_INDEXED) && p !== "/legends" && p !== "/start");
  // With the legends' switch on, the index and every page are listed; the
  // pages are not in PUBLIC_PATHS one by one, `/legends` is their prefix.
  const legends = LEGENDS_INDEXED ? ["/legends", ...LEGENDS.map((l) => `/legends/${l.slug}`)] : [];
  return sitemapUrls(BRAND_URL, [...paths, ...legends]);
}
