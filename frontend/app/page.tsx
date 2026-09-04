import type { Metadata, Viewport } from "next";
import { LANDING, homeScreenName, publicTitle } from "@/lib/landing";
import { BRAND_URL } from "@/lib/hosts";
import { Landing } from "@/components/landing/Landing";

/**
 * Root is the public marketing landing, not the dashboard. Its own metadata
 * overrides the layout's "— Dashboard" title, which is what a search result
 * and a shared link would otherwise show a prospective client.
 */
/* A visitor arrives here from a video the BRAND posted, so the brand is what
   the tab, the shared-link card and the home-screen label have to say first.
   Both strings are derived in lib/landing.ts, and both fall back to exactly
   what this page shipped with when no brand is configured. */
const DESCRIPTION = [
  LANDING.brand && LANDING.advisors ? `${LANDING.brand} is ${LANDING.advisors}.` : "",
  "Real estate advisors buying and selling across Colorado — Aspen, the Roaring Fork Valley, and the Denver metro. Book a 15-minute consult.",
]
  .filter(Boolean)
  .join(" ");

export const metadata: Metadata = {
  title: publicTitle,
  description: DESCRIPTION,
  // A marketing page is shared as a link far more often than it is typed. With
  // no Open Graph tags the preview card is a bare URL, which reads as spam in
  // the exact channels this page is meant to arrive through.
  openGraph: {
    type: "website",
    title: publicTitle,
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
  /**
   * The home-screen name, overridden because the root layout's is "Eko AI
   * Realtors" — the platform behind this site, which its public must never see.
   * Metadata is merged, not replaced, so without this the brand page would sit
   * on a seller's iPhone home screen labelled with their agent's vendor.
   */
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  /**
   * One address for this page, whatever hostname served it.
   *
   * The same landing is reachable on `inmo-demo.ekoaiautomation.com` and — once
   * DNS moves — on `www.denverhomestory.com`. Indexed under both, the domain
   * the whole funnel points at would be competing against a copy of itself, and
   * Google picks the winner, not us.
   *
   * Only declared when `NEXT_PUBLIC_BRAND_URL` is set. A canonical pointing at
   * a domain that does not resolve yet is worse than none: it would ask Google
   * to drop the page that IS live today in favour of one that answers nothing.
   */
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/" } }
    : {}),
};

// The layout paints mobile browser chrome the dashboard's noir; on a cream
// marketing page that reads as a rendering fault.
export const viewport: Viewport = { themeColor: "#0F0E0C" };

export default function HomePage() {
  return <Landing />;
}
