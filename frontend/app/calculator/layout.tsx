import type { Metadata, Viewport } from "next";
import { BRAND_URL } from "@/lib/hosts";
import { homeScreenName } from "@/lib/landing";

/**
 * Metadata for `/calculator`, which cannot declare its own: the page is a
 * client component (it computes as you type), and Next does not allow
 * `export const metadata` from one. Same shape as `/contact`, for the same
 * reasons — Next MERGES metadata, so anything not declared here falls through
 * to the root layout, whose title names the platform and whose `robots`
 * default is `index: false`. Both are wrong for the page a Short's caption
 * promises and whose link gets pasted into DMs.
 */
const TITLE = "What could your rent buy in Denver?";
const DESCRIPTION =
  "Type what you pay in rent, what you have saved and your credit range. See the " +
  "price you could buy at and what five years of owning versus renting looks like " +
  "— with every assumption in the open.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "website", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
  robots: { index: true, follow: true },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/calculator" } }
    : {}),
};

export default function CalculatorLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/** The landing's light theme, not the panel's noir. */
export const viewport: Viewport = { themeColor: "#F4F1EA" };
