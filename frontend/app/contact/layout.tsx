import type { Metadata } from "next";
import { BRAND_URL } from "@/lib/hosts";
import { LANDING } from "@/lib/landing";

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
/** Same source the landing titles itself from, so the two never drift apart. */
const PUBLIC_NAME =
  [LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" \u00b7 ") || "Colorado real estate";

export const metadata: Metadata = {
  robots: { index: true, follow: true },
  // Same reason as the landing: the root layout's home-screen name is the
  // platform's, and this page is public.
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: PUBLIC_NAME },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/contact" } }
    : {}),
};

export default function ContactLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
