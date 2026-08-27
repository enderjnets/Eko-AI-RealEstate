import { describe, expect, it, beforeEach, vi } from "vitest";

/**
 * The host split, exercised by calling the middleware — not by reading it.
 *
 * `lib/hosts.ts` reads `process.env` at module load, which is exactly how Next
 * inlines NEXT_PUBLIC_ values at build time. So each case sets the environment,
 * resets the module registry, and imports fresh. A test that imported once and
 * mutated `process.env` afterwards would be testing nothing: the constants are
 * already frozen by then.
 *
 * The case that matters most is the FIRST one. The domain is still parked at
 * GoDaddy and the nameserver move happens later, so this code ships to
 * production with both variables empty. If it redirected anyway, the panel
 * would bounce every request to a hostname that does not resolve — the whole
 * product, down, on deploy.
 */

const BRAND = "https://www.denverhomestory.com";
const PANEL = "https://realtors.ekoaiautomation.com";

async function load(brand: string, panel: string) {
  vi.resetModules();
  process.env.NEXT_PUBLIC_BRAND_URL = brand;
  process.env.NEXT_PUBLIC_PANEL_URL = panel;
  return {
    ...(await import("../../middleware")),
    hosts: await import("../hosts"),
  };
}

function req(host: string, path: string, search = "") {
  return {
    headers: { get: (k: string) => (k.toLowerCase() === "host" ? host : null) },
    nextUrl: { pathname: path, search },
  } as never;
}

/** Next signals "carry on" with no Location; a redirect carries one. */
const location = (res: { headers: { get(k: string): string | null } }) =>
  res.headers.get("location");

describe("host routing", () => {
  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_BRAND_URL;
    delete process.env.NEXT_PUBLIC_PANEL_URL;
  });

  it("does nothing at all while the hostnames are unconfigured", async () => {
    const { middleware } = await load("", "");
    // A panel path on the hostname production actually uses today.
    expect(location(middleware(req("inmo-demo.ekoaiautomation.com", "/leads")))).toBeNull();
    expect(location(middleware(req("inmo-demo.ekoaiautomation.com", "/")))).toBeNull();
  });

  it("does nothing when only one of the two is set", async () => {
    // Half-configured is a real state: someone fills in the brand URL, deploys,
    // and finishes later. Redirecting the panel to an empty string would take
    // the app down between those two moments.
    const { middleware } = await load(BRAND, "");
    expect(location(middleware(req("www.denverhomestory.com", "/leads")))).toBeNull();
  });

  it("sends panel routes on the brand domain to the panel, keeping path and query", async () => {
    const { middleware } = await load(BRAND, PANEL);
    const res = middleware(req("www.denverhomestory.com", "/leads", "?status=new"));
    expect(location(res)).toBe(`${PANEL}/leads?status=new`);
    expect(res.status).toBe(308);
  });

  it("leaves the public pages alone on the brand domain", async () => {
    const { middleware } = await load(BRAND, PANEL);
    for (const p of ["/", "/contact"]) {
      expect(location(middleware(req("www.denverhomestory.com", p)))).toBeNull();
    }
  });

  it("does not serve the platform's own sales page on the brand domain", async () => {
    // `/about` pitches THIS PLATFORM to real-estate agencies. The people who
    // reach the brand domain are sellers who watched a video; serving them the
    // sales deck we show their agent's competitors is the worst page available.
    // It was in PUBLIC_PATHS and this is the assertion that keeps it out.
    const { middleware } = await load(BRAND, PANEL);
    const res = middleware(req("www.denverhomestory.com", "/about"));
    expect(location(res)).toBe(`${PANEL}/about`);
    expect(res.status).toBe(308);
  });

  it("treats a fully-qualified host ending in a dot as the same host", async () => {
    // `www.denverhomestory.com.` is the SAME name to DNS and a different string
    // to `===`. Unstripped, it fell through every comparison and served the
    // internal panel, crawlable, under the brand domain.
    const { middleware } = await load(BRAND, PANEL);
    const res = middleware(req("www.denverhomestory.com.", "/leads"));
    expect(location(res)).toBe(`${PANEL}/leads`);
    expect(res.status).toBe(308);
  });

  it("stays inert when both hostnames are the same, instead of looping forever", async () => {
    // Reachable by hand mid-migration. Redirecting a host to itself is an
    // infinite redirect, which is strictly worse than not redirecting at all.
    const { middleware } = await load(BRAND, BRAND);
    expect(location(middleware(req("www.denverhomestory.com", "/leads")))).toBeNull();
    expect(location(middleware(req("www.denverhomestory.com", "/")))).toBeNull();
  });

  it("sends the panel's front door to the work, not the marketing page", async () => {
    const { middleware } = await load(BRAND, PANEL);
    const front = middleware(req("realtors.ekoaiautomation.com", "/"));
    expect(location(front)).toBe(`${PANEL}/leads`);
    // 307, not 308: the panel's front door is a convenience, not a statement
    // that `/` has permanently moved. Asserted because the destination alone
    // left the status free to change without a single test going red.
    expect(front.status).toBe(307);
  });

  it("leaves any other hostname untouched", async () => {
    // inmo-demo keeps working through the transition; nothing here assumes the
    // old hostname is retired on the same day the new one arrives.
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("inmo-demo.ekoaiautomation.com", "/leads")))).toBeNull();
  });

  it("ignores the port in the host header", async () => {
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("www.denverhomestory.com:3000", "/leads")))).toBe(
      `${PANEL}/leads`,
    );
  });

  it("treats a malformed URL as unset instead of throwing", async () => {
    // A typo in .env must not 500 every request on the site.
    const { middleware } = await load("not a url", PANEL);
    expect(() => middleware(req("www.denverhomestory.com", "/leads"))).not.toThrow();
    expect(location(middleware(req("www.denverhomestory.com", "/leads")))).toBeNull();
  });

  it("does not treat a lookalike path as public", async () => {
    const { hosts } = await load(BRAND, PANEL);
    expect(hosts.isPublicPath("/contact")).toBe(true);
    expect(hosts.isPublicPath("/contact/thanks")).toBe(true);
    expect(hosts.isPublicPath("/contactos")).toBe(false);
    expect(hosts.isPublicPath("/leads")).toBe(false);
  });

  it("never redirects the API, or the capture form would lose its POST", async () => {
    // `/api` is not a public path, so without the matcher exclusion a lead
    // submitted from the brand domain would be 308'd to the panel hostname —
    // and a redirected POST is not replayed as a POST by every client. The form
    // would look fine and quietly drop leads.
    const { config } = await load(BRAND, PANEL);
    // Anchored, because Next matches a `matcher` against the WHOLE path. The
    // anchor is not a detail: unanchored, this same string reports that `/api`
    // IS matched — the regex simply restarts at `/v1/...`, where the negative
    // lookahead passes. The first draft of this test omitted the anchors and
    // failed, which for ten minutes looked like a bug in the middleware.
    // The prefix exclusions only mean anything anchored, which is also why
    // Next's own `_next/static` idiom works at all.
    const re = new RegExp(`^${config.matcher[0]}$`);
    expect(re.test("/api/v1/public/leads")).toBe(false);
    expect(re.test("/leads")).toBe(true);
    expect(re.test("/")).toBe(true);
    expect(re.test("/_next/static/chunk.js")).toBe(false);
  });
});
