import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * `/contact` names the brokerage in the HTML the server sends.
 *
 * On 13-oct-2026 the served page read, in full, "Contact Denver Home Story ·
 * Natalia & Robbie, Engel & Völkers · Or just call us: (720) 824-9313 · en":
 * the brokerage only in the <title>, because everything else on the page
 * renders inside the Suspense boundary that `useSearchParams` needs, and Next
 * bakes only the fallback spinner into the static HTML. Colorado's Rule 6.10
 * asks for the brokerage on every page of the broker's own site, and a page
 * that names it only after JavaScript runs does not name it to a crawler, a
 * link preview, or a visitor whose script failed.
 */

const read = (...parts: string[]) =>
  readFileSync(join(__dirname, "..", "..", ...parts), "utf8");

const contact = read("app", "contact", "page.tsx");
const landing = read("components", "landing", "Landing.tsx");

describe("the brokerage on /contact", () => {
  it("is rendered after the Suspense boundary, so it is in the served HTML", () => {
    const closed = contact.indexOf("</Suspense>");
    const rendered = contact.indexOf("<ContactBrokerage />");
    expect(closed, "the boundary moved; re-check what is static").toBeGreaterThan(-1);
    expect(rendered, "the brokerage is not rendered").toBeGreaterThan(closed);
  });

  it("comes from the same lines as the landing's footer", () => {
    // Two derivations of "who is advertising" drift the day one is edited.
    for (const [name, source] of [
      ["contact", contact],
      ["landing", landing],
    ] as const) {
      expect(source, `${name} does not use brokerageLines`).toMatch(/brokerageLines\(t\)/);
    }
  });
});
