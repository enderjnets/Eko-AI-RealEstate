import type { Metadata, Viewport } from "next";

import "./brief.css";

/**
 * Metadata for `/brief/[token]`, which cannot declare its own.
 *
 * `page.tsx` is a client component, and Next does not allow `export const
 * metadata` from one — the same reason `contact/layout.tsx` exists. The
 * difference is which way the default needs pushing: `/contact` had to opt
 * BACK IN to indexing, and this page has to be certain it never is.
 *
 * `robots: { index: false, follow: false }` is not belt-and-braces on top of a
 * robots.txt, it is the only control that holds. Cloudflare serves its own
 * `robots.txt` on both hostnames and prepends `Allow: /` for every crawler —
 * measured on this infrastructure — and Google honours the least restrictive
 * rule. A page carrying nine past clients' names and street addresses cannot
 * depend on a file somebody else rewrites.
 *
 * `nocache` / `noimageindex` are there for the crawlers that index a page they
 * were told not to index: what they must not do is keep a copy.
 *
 * No canonical and no `metadataBase`: a canonical announces an address, and
 * the address here is the credential.
 */
export const metadata: Metadata = {
  title: "Brief",
  // Overrides the root layout's description, which sells this platform to
  // real-estate offices. The people opening this are not a sales audience.
  description: "A private working page.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    noarchive: true,
    noimageindex: true,
    googleBot: { index: false, follow: false, noimageindex: true },
  },
  referrer: "no-referrer",
};

export default function BriefLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/** The panel's noir, which is what this page wears. */
export const viewport: Viewport = { themeColor: "#0B0B0F" };
