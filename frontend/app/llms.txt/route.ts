import { BRAND_URL } from "@/lib/hosts";
import { LANDING, publicName } from "@/lib/landing";
import { LEGENDS, LEGENDS_INDEXED } from "@/lib/legends";

/**
 * `/llms.txt` (llmstxt.org): a plain-text map of the site for AI assistants.
 * Derived like the sitemap: the same public pages, the legends only while
 * `LEGENDS_INDEXED` is on, and nothing at all without a brand domain.
 */
export const dynamic = "force-static";

export function GET() {
  const url = BRAND_URL.trim().replace(/\/$/, "");
  if (!url) return new Response("", { status: 404 });
  const lines = [
    `# ${LANDING.brand || publicName || "Colorado real estate"}`,
    "",
    `> ${[publicName, "Real estate advisors buying and selling across Colorado: Aspen, the Roaring Fork Valley and the Denver metro."].filter(Boolean).join(". ")}`,
    "",
    "## Pages",
    `- [Home](${url}/): who we are, the areas we work and how to reach us`,
    `- [What could your rent buy in Denver?](${url}/calculator): a rent-versus-buy calculator`,
    `- [Where to see fall color near Denver](${url}/fall): a guide to fall outings by elevation`,
    `- [Contact](${url}/contact): tell us what you are looking for`,
  ];
  if (LEGENDS_INDEXED) {
    lines.push("", "## Denver, decoded", `- [All the legends](${url}/legends): Denver stories checked against the records, with sources`);
    for (const l of LEGENDS) lines.push(`- [${l.title}](${url}/legends/${l.slug}): ${l.dek}`);
  }
  if (LANDING.brokerage) lines.push("", `${LANDING.brokerage}. Each office independently owned and operated.`);
  return new Response(lines.join("\n") + "\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
