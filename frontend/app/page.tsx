import type { Metadata } from "next";
import { LANDING } from "@/lib/landing";
import { Landing } from "@/components/landing/Landing";

/**
 * Root is the public marketing landing, not the dashboard. Its own metadata
 * overrides the layout's "— Dashboard" title, which is what a search result
 * and a shared link would otherwise show a prospective client.
 */
const who = [LANDING.advisors, LANDING.brokerage].filter(Boolean).join(" · ");

export const metadata: Metadata = {
  title: who ? `${who} — Colorado real estate` : "Colorado real estate",
  description:
    "Advisors for buyers and sellers across Colorado — mountain-town luxury and the Denver metro. Book a 15-minute consult.",
};

export default function HomePage() {
  return <Landing />;
}
