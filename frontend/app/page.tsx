import type { Metadata, Viewport } from "next";
import { LANDING } from "@/lib/landing";
import { Landing } from "@/components/landing/Landing";

/**
 * Root is the public marketing landing, not the dashboard. Its own metadata
 * overrides the layout's "— Dashboard" title, which is what a search result
 * and a shared link would otherwise show a prospective client.
 */
const who = [LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ");

const DESCRIPTION =
  "Advisors for buyers and sellers across Colorado — mountain-town luxury and the Denver metro. Book a 15-minute consult.";

export const metadata: Metadata = {
  title: who ? `${who} — Colorado real estate` : "Colorado real estate",
  description: DESCRIPTION,
  // A marketing page is shared as a link far more often than it is typed. With
  // no Open Graph tags the preview card is a bare URL, which reads as spam in
  // the exact channels this page is meant to arrive through.
  openGraph: {
    type: "website",
    title: who ? `${who} — Colorado real estate` : "Colorado real estate",
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
};

// The layout paints mobile browser chrome the dashboard's noir; on a cream
// marketing page that reads as a rendering fault.
export const viewport: Viewport = { themeColor: "#F4F1EA" };

export default function HomePage() {
  return <Landing />;
}
