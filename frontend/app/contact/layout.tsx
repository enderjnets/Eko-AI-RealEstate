import type { Metadata, Viewport } from "next";
import { BRAND_URL } from "@/lib/hosts";
import { LANDING, homeScreenName, publicName } from "@/lib/landing";

/**
 * Metadata for `/contact`, which cannot declare its own.
 *
 * `contact/page.tsx` is a client component ("use client") and Next does not
 * allow `export const metadata` from one — so without this file the page would
 * silently inherit the root layout's new `robots: { index: false }` default and
 * drop out of the index. That default is right for the panel and wrong here:
 * this is the page a stranger who watched a video is meant to reach, and it was
 * indexable before the default existed. Changing that as a side effect of
 * tightening the panel would have been an SEO regression nobody asked for and
 * nobody would have noticed until traffic went missing.
 *
 * The canonical is the same conditional as the landing's: declared only once
 * `NEXT_PUBLIC_BRAND_URL` is set, because pointing at a domain that does not
 * resolve yet is worse than not pointing at all.
 */
/* Imported, not rebuilt: this comment used to say "same source the landing
   titles itself from, so the two never drift apart" over a second copy of the
   landing's expression. `lib/landing.ts` is now that single source. */
const PUBLIC_NAME = publicName || "Colorado real estate";

const DESCRIPTION =
  "Tell us what you are looking for and we will get back to you. Advisors for buyers and sellers across Colorado.";

export const metadata: Metadata = {
  /**
   * Title and description are declared here, not inherited, and that is the
   * whole reason this block exists.
   *
   * Next MERGES metadata, so a field this file does not set falls through to
   * `app/layout.tsx` — whose title is "Eko AI Realtors — Dashboard" and whose
   * description sells the platform to real-estate offices. Combined with the
   * `index: true` below, the page where a stranger types their phone number was
   * publishing our vendor name as its Google result and as its WhatsApp preview
   * card. The platform is what runs this site; the people who reach it are the
   * agency's clients and must never see it.
   *
   * `openGraph` and `twitter` are declared for the same reason a link to this
   * page is shared: without them the preview card falls back to the `<title>`.
   */
  title: `Contact ${PUBLIC_NAME}`,
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    title: `Contact ${PUBLIC_NAME}`,
    description: DESCRIPTION,
  },
  twitter: { card: "summary", title: `Contact ${PUBLIC_NAME}`, description: DESCRIPTION },
  robots: { index: true, follow: true },
  // Same reason as the landing: the root layout's home-screen name is the
  // platform's, and this page is public.
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/contact" } }
    : {}),
};

export default function ContactLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/**
 * The landing's light theme, not the panel's noir. Inherited, the browser chrome
 * around a public page was painted with the internal palette.
 */
export const viewport: Viewport = { themeColor: "#F4F1EA" };
