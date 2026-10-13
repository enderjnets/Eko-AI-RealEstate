import type { Metadata, Viewport } from "next";

import { LegendsIndex } from "@/components/landing/LegendsIndex";
import { BRAND_URL } from "@/lib/hosts";
import { publicTitle } from "@/lib/landing";
import { LEGENDS } from "@/lib/legends";

const TITLE = `Denver, decoded | ${publicTitle}`;
const DESCRIPTION =
  "The Denver stories everyone repeats, checked against the records: each with its sources, its archive photographs and the 3D flyover from its video.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "website", title: TITLE, description: DESCRIPTION, images: LEGENDS[0] ? [LEGENDS[0].hero.src] : [] },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
  // Same rule as each legend page: linked from the home, kept out of every
  // index until being found by search is decided on its own.
  robots: { index: false, follow: true },
  alternates: { canonical: "/legends" },
  ...(BRAND_URL ? { metadataBase: new URL(BRAND_URL) } : {}),
};

export const viewport: Viewport = { themeColor: "#F4F1EA" };

export default function LegendsIndexPage() {
  return <LegendsIndex />;
}
