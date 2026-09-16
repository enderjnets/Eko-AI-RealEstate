import type { MetadataRoute } from "next";

import { BRAND_URL, PUBLIC_PATHS } from "@/lib/hosts";
import { sitemapUrls } from "@/lib/sitemap";

/**
 * `/sitemap.xml`, which answered 404 until now.
 *
 * All of the thinking, and all of the tests, live in `lib/sitemap.ts`. This
 * file exists only because Next needs the route to be a default export here.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  return sitemapUrls(BRAND_URL, PUBLIC_PATHS);
}
