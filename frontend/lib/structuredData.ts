/**
 * schema.org JSON-LD for the public pages: what a search engine or an AI
 * assistant reads to know who this site is and where each claim comes from.
 *
 * Every value is read from what the pages already print — `LANDING` (the
 * brand, the brokerage, the office address and phone, the profiles) and
 * `LEGENDS` (titles, deks, sources). Nothing is typed twice, so the markup
 * cannot say something the page does not: on a page advertising a licensed
 * brokerage, structured data that disagrees with the visible text is the same
 * false statement in a place nobody proofreads. An unset value is left out,
 * never guessed (the rule `lib/landing.ts` sets for the page itself).
 *
 * No dates: the legends do not record when they were written, and a
 * `datePublished` stamped at build time would be a claim that is not true.
 */
import { BRAND_URL } from "@/lib/hosts";
import { LANDING, dialable } from "@/lib/landing";
import type { Legend } from "@/lib/legends";

type Json = Record<string, unknown>;

/** "533 E Hopkins Ave, Ste 101, Aspen, CO 81611" → its parts; anything else → null. */
export function postalAddress(address: string): Json | null {
  const m = address.trim().match(/^(.+),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$/);
  if (!m) return null;
  return {
    "@type": "PostalAddress",
    streetAddress: m[1].trim(),
    addressLocality: m[2].trim(),
    addressRegion: m[3],
    postalCode: m[4],
    addressCountry: "US",
  };
}

function origin(base = BRAND_URL): string {
  return base.trim().replace(/\/$/, "");
}

/** The business behind the brand, with the office and the brokerage it is licensed under. */
export function agentJsonLd(base = BRAND_URL): Json | null {
  const url = origin(base);
  if (!url || !LANDING.brand) return null;
  const address = LANDING.address ? postalAddress(LANDING.address) : null;
  const agent: Json = {
    "@type": "RealEstateAgent",
    "@id": `${url}/#agent`,
    name: LANDING.brand,
    url: `${url}/`,
    // The areas the home page's own description names.
    areaServed: ["Denver metro, Colorado", "Aspen, Colorado", "Roaring Fork Valley, Colorado"],
  };
  if (LANDING.advisors) agent.description = `${LANDING.brand} is ${LANDING.advisors}.`;
  if (LANDING.portrait) agent.image = LANDING.portrait.startsWith("/") ? `${url}${LANDING.portrait}` : LANDING.portrait;
  if (LANDING.phone) agent.telephone = dialable(LANDING.phone);
  if (address) agent.address = address;
  if (LANDING.brokerage) agent.parentOrganization = { "@type": "Organization", name: LANDING.brokerage };
  const profiles = LANDING.socials.map((s) => s.url).filter(Boolean);
  if (profiles.length) agent.sameAs = profiles;
  return {
    "@context": "https://schema.org",
    "@graph": [
      agent,
      { "@type": "WebSite", "@id": `${url}/#website`, name: LANDING.brand, url: `${url}/`, publisher: { "@id": `${url}/#agent` } },
    ],
  };
}

/** The place a legend is about: the eyebrow without the series name. */
export function legendPlace(eyebrow: string): string {
  return eyebrow.replace(/^Denver, decoded\s*·\s*/, "");
}

/**
 * One legend page: an Article whose `citation` lists every source the page
 * prints, deduplicated, plus its breadcrumb. The citations are the point — a
 * page that says where each line comes from is what an assistant can quote.
 */
export function legendJsonLd(legend: Legend, base = BRAND_URL): Json | null {
  const url = origin(base);
  if (!url) return null;
  const page = `${url}/legends/${legend.slug}`;
  const seen = new Set<string>();
  const citation = legend.facts
    .flatMap((f) => f.sources)
    .filter((s) => (seen.has(s.url) ? false : (seen.add(s.url), true)))
    .map((s) => ({ "@type": "CreativeWork", name: s.name, url: s.url }));
  const article: Json = {
    "@type": "Article",
    "@id": `${page}#article`,
    headline: legend.title,
    description: legend.dek,
    url: page,
    mainEntityOfPage: page,
    image: `${url}${legend.hero.src}`,
    inLanguage: "en",
    isAccessibleForFree: true,
    about: { "@type": "Place", name: legendPlace(legend.eyebrow) },
    citation,
  };
  if (LANDING.brand) {
    article.author = { "@type": "Organization", name: LANDING.brand, url: `${url}/` };
    article.publisher = { "@type": "Organization", name: LANDING.brand, url: `${url}/` };
  }
  return {
    "@context": "https://schema.org",
    "@graph": [
      article,
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: LANDING.brand || "Home", item: `${url}/` },
          { "@type": "ListItem", position: 2, name: "Denver, decoded", item: `${url}/legends` },
          { "@type": "ListItem", position: 3, name: legend.title, item: page },
        ],
      },
    ],
  };
}

/** The index of legends, as the ordered list of its pages. */
export function legendsIndexJsonLd(legends: readonly Legend[], base = BRAND_URL): Json | null {
  const url = origin(base);
  if (!url) return null;
  return {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Denver, decoded",
    url: `${url}/legends`,
    inLanguage: "en",
    mainEntity: {
      "@type": "ItemList",
      itemListElement: legends.map((l, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `${url}/legends/${l.slug}`,
        name: l.title,
      })),
    },
  };
}

/** Serialised for a <script type="application/ld+json">: `<` escaped so no value can close the tag. */
export function jsonLdScript(data: Json): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
