import type { Metadata, Viewport } from "next";

import { Start, type StartSearchParams } from "@/components/landing/Start";
import { BRAND_URL } from "@/lib/hosts";
import { homeScreenName, publicTitle } from "@/lib/landing";

const TITLE = `Start here · Empieza aquí | ${publicTitle}`;
const DESCRIPTION =
  "Buy, sell, value a home, or speak with a Colorado real estate advisor. " +
  "Compra, vende, conoce el valor de una casa o habla con un asesor inmobiliario en Colorado.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "website", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
  robots: { index: false, follow: true },
  alternates: { canonical: "/start" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL ? { metadataBase: new URL(BRAND_URL) } : {}),
};

export const viewport: Viewport = { themeColor: "#F4F1EA" };

export default function StartPage({
  searchParams = {},
}: {
  searchParams?: StartSearchParams;
}) {
  return <Start searchParams={searchParams} />;
}
