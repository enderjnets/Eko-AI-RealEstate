import { jsonLdScript } from "@/lib/structuredData";

/** schema.org data for crawlers and assistants (`lib/structuredData.ts`); renders nothing when there is none. */
export function JsonLd({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return null;
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(data) }} />;
}
