import type { MetadataRoute } from "next";

import { BRAND_URL, PUBLIC_PATHS } from "@/lib/hosts";
import { PUBLISHED as JOURNAL_PUBLISHED } from "@/lib/journal/publication";
import { sitemapUrls } from "@/lib/sitemap";

/**
 * `/sitemap.xml`, which answered 404 until now.
 *
 * All of the thinking, and all of the tests, live in `lib/sitemap.ts`. This
 * file exists only because Next needs the route to be a default export here.
 *
 * The one subtraction, and it is still DERIVED rather than hand-kept: The
 * Journal has to be public for the panel to serve it — that is what
 * `PUBLIC_PATHS` decides — but while its publication gate is shut its pages
 * declare `robots: index:false`. Listing a page here and telling the crawler
 * not to index it are opposite instructions, and the sitemap is the one that
 * actively invites the visit. The filter reads the same constant the pages
 * read, so the two can never drift; there is no second list to keep.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const paths = PUBLIC_PATHS.filter((p) => p !== "/blog" || JOURNAL_PUBLISHED);
  return sitemapUrls(BRAND_URL, paths);
}
