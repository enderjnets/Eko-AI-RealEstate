import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";

import { Legend, type LegendSearchParams } from "@/components/landing/Legend";
import { BRAND_URL } from "@/lib/hosts";
import { publicTitle } from "@/lib/landing";
import { LEGENDS, legendBySlug } from "@/lib/legends";

export function generateStaticParams() {
  return LEGENDS.map((l) => ({ slug: l.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const legend = legendBySlug(params.slug);
  if (!legend) return {};
  const title = `${legend.title} | ${publicTitle}`;
  return {
    title,
    description: legend.dek,
    openGraph: { type: "article", title, description: legend.dek, images: [legend.hero.src] },
    twitter: { card: "summary_large_image", title, description: legend.dek },
    // Out of every index for now (the Journal's rule: linking is reversible,
    // indexing is not). The pages exist for the people who typed the address
    // from a video; being found by search is a separate decision.
    robots: { index: false, follow: true },
    alternates: { canonical: `/legends/${legend.slug}` },
    ...(BRAND_URL ? { metadataBase: new URL(BRAND_URL) } : {}),
  };
}

export const viewport: Viewport = { themeColor: "#F4F1EA" };

export default function LegendPage({
  params,
  searchParams = {},
}: {
  params: { slug: string };
  searchParams?: LegendSearchParams;
}) {
  const legend = legendBySlug(params.slug);
  if (!legend) notFound();
  return <Legend legend={legend} searchParams={searchParams} />;
}
