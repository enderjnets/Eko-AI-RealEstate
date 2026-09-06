import { describe, expect, it } from "vitest";

/**
 * The public pages must not inherit the panel's identity.
 *
 * Next MERGES metadata: a field a page does not declare falls through to
 * `app/layout.tsx`, whose title is "Eko AI Realtors — Dashboard" and whose
 * description sells the platform to real-estate offices. That is how `/contact`
 * — the page where a stranger types their phone number, and the only public
 * page with `index: true` and no declared title — ended up publishing the
 * vendor's name as its Google result and its WhatsApp preview card.
 *
 * The rule this file enforces: Eko AI Realtors is the platform BEHIND
 * denverhomestory.com, and that domain's visitors must never see it.
 *
 * These assertions fail on ABSENCE, which is the shape of the bug. Deleting
 * `title` from the contact layout makes it `undefined` and turns this red —
 * a test that only checked the declared strings would have stayed green
 * through the entire outage.
 */

const PLATFORM = /eko/i;

/** Every human-readable string reachable from a metadata object. */
function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((v) => strings(v, out));
  else if (value && typeof value === "object")
    Object.values(value as Record<string, unknown>).forEach((v) => strings(v, out));
  return out;
}

describe("public pages do not leak the platform's identity", () => {
  it("the contact page declares its own title and description", async () => {
    const { metadata } = await import("../../app/contact/layout");
    // Not "is not Eko" — DECLARED. Undefined means inherited, and what it
    // inherits is the panel's.
    expect(metadata.title).toBeTruthy();
    expect(metadata.description).toBeTruthy();
    expect(metadata.openGraph?.title).toBeTruthy();
  });

  it("nothing the contact page publishes names the platform", async () => {
    const { metadata } = await import("../../app/contact/layout");
    for (const s of strings(metadata)) expect(s).not.toMatch(PLATFORM);
  });

  it("the contact page is indexable, which is why the leak mattered", async () => {
    const { metadata } = await import("../../app/contact/layout");
    expect(metadata.robots).toMatchObject({ index: true });
  });

  it("nothing the landing publishes names the platform", async () => {
    const { metadata } = await import("../../app/page");
    for (const s of strings(metadata)) expect(s).not.toMatch(PLATFORM);
  });

  it("the fall guide declares its own title, description and preview card", async () => {
    // It is the page a reel's caption promises, so it is also the page whose
    // link gets pasted into a DM — and an undeclared openGraph title makes that
    // preview card read "Eko AI Realtors — Dashboard" to somebody who was told
    // they were getting a guide to the aspens.
    const { metadata } = await import("../../app/fall/page");
    expect(metadata.title).toBeTruthy();
    expect(metadata.description).toBeTruthy();
    expect(metadata.openGraph?.title).toBeTruthy();
    expect(metadata.appleWebApp).toBeTruthy();
  });

  it("nothing the fall guide publishes names the platform", async () => {
    const { metadata } = await import("../../app/fall/page");
    for (const s of strings(metadata)) expect(s).not.toMatch(PLATFORM);
  });

  it("the fall guide is indexable — being found is most of its job", async () => {
    // The root layout defaults to `index: false`, which is right for the panel.
    // This page exists to be searched for in September and linked to from three
    // bios; inheriting that default would be the whole point, silently undone.
    const { metadata } = await import("../../app/fall/page");
    expect(metadata.robots).toMatchObject({ index: true });
  });

  it("the calculator declares its own title, description and preview card", async () => {
    // A Short's caption promises a number; the link gets pasted into DMs.
    const { metadata } = await import("../../app/calculator/layout");
    expect(metadata.title).toBeTruthy();
    expect(metadata.description).toBeTruthy();
    expect(metadata.openGraph?.title).toBeTruthy();
    expect(metadata.appleWebApp).toBeTruthy();
  });

  it("nothing the calculator publishes names the platform", async () => {
    const { metadata } = await import("../../app/calculator/layout");
    for (const s of strings(metadata)) expect(s).not.toMatch(PLATFORM);
  });

  it("the calculator is indexable", async () => {
    const { metadata } = await import("../../app/calculator/layout");
    expect(metadata.robots).toMatchObject({ index: true });
  });

  it("both public pages set their own home-screen name", async () => {
    // The root layout's is the platform's. Metadata merges, so an undeclared
    // one is inherited and a seller's iPhone shows their agent's vendor.
    const landing = await import("../../app/page");
    const contact = await import("../../app/contact/layout");
    expect(landing.metadata.appleWebApp).toBeTruthy();
    expect(contact.metadata.appleWebApp).toBeTruthy();
  });
});
