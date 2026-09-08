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
 * The FIRST case guards the unconfigured install: with both variables empty
 * nothing redirects, so a fresh clone and a half-finished deployment behave
 * exactly as a single-hostname app. It was written when that WAS production —
 * the domain parked at GoDaddy — and said so; production has set both since
 * v0.64.0, and every other case in this file describes what is live.
 */

const BRAND = "https://www.denverhomestory.com";
/**
 * The panel hostname production actually uses. It was `realtors.…` here while
 * that name was the plan; the `.env` on the VPS says `inmo-demo.…` and has
 * since v0.89.0. The literal matters: with the old value this file read
 * "realtors is the panel, redirected; inmo-demo is untouched", which is the
 * exact inverse of production — and the next person auditing "does /contact
 * still work on the panel?" would have read it and concluded yes.
 */
const PANEL = "https://inmo-demo.ekoaiautomation.com";

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
    for (const p of ["/", "/contact", "/fall", "/calculator"]) {
      expect(location(middleware(req("www.denverhomestory.com", p)))).toBeNull();
    }
  });

  it("serves the fall guide on the brand domain, which is the only place it is read", async () => {
    // Named separately from the loop above because this one has a failure mode
    // the loop's message would not explain. `/fall` is what a reel's caption
    // promises: somebody comments a keyword, gets the link in a DM and taps it.
    // Dropped from PUBLIC_PATHS it answers 308 to the panel, and the visitor —
    // exactly the person the campaign was built to reach — lands on a login
    // screen for an internal tool. Nothing in the product reports that; it
    // reads as "the campaign did not convert".
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("www.denverhomestory.com", "/fall")))).toBeNull();
    // And with a UTM query, which is how every real visit to it arrives.
    expect(
      location(middleware(req("www.denverhomestory.com", "/fall", "?utm_source=instagram"))),
    ).toBeNull();
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

  it("normalises the dot on the CONFIGURED side too, not just the request", async () => {
    // The other half of "normalised on both sides". Without the strip in
    // `hostOf`, a BRAND_URL someone pasted with a trailing dot yields a
    // BRAND_HOST no request can ever equal, and the split silently stops
    // working — every panel route served under the brand domain. The request
    // side had a test; this side had none.
    const { middleware } = await load("https://www.denverhomestory.com.", PANEL);
    const res = middleware(req("www.denverhomestory.com", "/leads"));
    expect(location(res)).toBe(`${PANEL}/leads`);
  });

  it("strips every trailing dot, not just one", async () => {
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("www.denverhomestory.com..", "/leads")))).toBe(
      `${PANEL}/leads`,
    );
  });

  it("keeps the platform's sales page reachable on the panel's own hostname", async () => {
    // The other half of the rule. Taking `/about` out of PUBLIC_PATHS must hide
    // it from CLIENTS, not delete it: it is still how the product is explained
    // internally. Nothing asserted this, so deleting the page would have passed.
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("inmo-demo.ekoaiautomation.com", "/about")))).toBeNull();
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
    const front = middleware(req("inmo-demo.ekoaiautomation.com", "/"));
    expect(location(front)).toBe(`${PANEL}/leads`);
    // 307, not 308: the panel's front door is a convenience, not a statement
    // that `/` has permanently moved. Asserted because the destination alone
    // left the status free to change without a single test going red.
    expect(front.status).toBe(307);
  });

  it("sends the public pages on the panel domain to the brand, keeping the query", async () => {
    // The other direction of the split, and the reason it was added: measured
    // on the live site, the panel hostname answered `/fall` and `/calculator`
    // with the same bytes as the brand one. One page, two addresses, and only
    // a canonical tag — a hint, not a rule — asking Google which to keep.
    const { middleware } = await load(BRAND, PANEL);
    for (const p of ["/fall", "/calculator"]) {
      const res = middleware(req("inmo-demo.ekoaiautomation.com", p));
      expect(location(res)).toBe(`${BRAND}${p}`);
      expect(res.status).toBe(308);
    }
    // With the query, which is how every real visit to `/fall` arrives.
    expect(
      location(middleware(req("inmo-demo.ekoaiautomation.com", "/fall", "?utm_source=instagram"))),
    ).toBe(`${BRAND}/fall?utm_source=instagram`);
  });

  it("does not let a browser cache the redirect, so a bad brand host is reversible", async () => {
    // A 308 with no `Cache-Control` is cacheable by default, and that was what
    // this sent until it was measured (`curl -I` against a local build: status
    // 308, no cache header). The failure it guards against is concrete: set
    // `NEXT_PUBLIC_BRAND_URL` to a hostname that does not resolve yet, deploy,
    // and every visitor who touched a landing has the redirect pinned —
    // unsetting the variable does not reach them. The crawler still reads 308.
    const { middleware } = await load(BRAND, PANEL);
    const res = middleware(req("inmo-demo.ekoaiautomation.com", "/calculator"));
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("sends `/contact` on the panel domain to the brand too, reversing an earlier decision", async () => {
    // Named on its own because it is a CHANGE, not a consequence. The rule it
    // replaced kept `/contact` reachable on the panel host "so an operator
    // following a link from an email is not bounced across hostnames", and
    // nothing asserted it — so flipping the behaviour would have gone green
    // and silent. It was flipped deliberately: no mail this system sends
    // carries a `/contact` URL (the only one is `PANEL_URL/leads/<id>`), and a
    // saved bookmark still lands on the same page, on the public address.
    // If that decision is ever revisited, this is the test that has to change
    // with it.
    const { middleware } = await load(BRAND, PANEL);
    const res = middleware(req("inmo-demo.ekoaiautomation.com", "/contact"));
    expect(location(res)).toBe(`${BRAND}/contact`);
    expect(res.status).toBe(308);
    // Sub-paths travel with it: `isPublicPath` matches `/contact/thanks`.
    expect(location(middleware(req("inmo-demo.ekoaiautomation.com", "/contact/thanks")))).toBe(
      `${BRAND}/contact/thanks`,
    );
  });

  it("does not touch the public pages on the panel host while unconfigured", async () => {
    // The first test in this file covers `/leads` and `/` unconfigured; the
    // rule that redirects public pages was covered by neither. NOT the state
    // production is in — the VPS sets both, and has since v0.64.0; an earlier
    // version of this comment said the opposite and was wrong. It is the state
    // of a fresh clone and of a half-finished install, and a refactor that
    // hoisted the rule above the guard would 308 every landing there to an
    // empty string.
    const { middleware } = await load("", "");
    for (const p of ["/fall", "/contact", "/calculator"]) {
      expect(location(middleware(req("inmo-demo.ekoaiautomation.com", p)))).toBeNull();
    }
  });

  it("leaves a hostname that is neither brand nor panel untouched", async () => {
    // A third name reaches this app during a migration — the old tunnel
    // hostname, a preview deployment, an IP. It is neither half of the split,
    // so it keeps serving whatever it served: bouncing it would take down a
    // route nobody has finished moving yet.
    //
    // This used to use `inmo-demo…` as the stranger. That name IS the panel in
    // production, so the assertion read as "the panel is untouched" — the
    // opposite of what this file now enforces.
    const { middleware } = await load(BRAND, PANEL);
    expect(location(middleware(req("old-tunnel.ekoaiautomation.com", "/leads")))).toBeNull();
    expect(location(middleware(req("old-tunnel.ekoaiautomation.com", "/fall")))).toBeNull();
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
    expect(hosts.isPublicPath("/fall")).toBe(true);
    expect(hosts.isPublicPath("/fallback")).toBe(false);
    expect(hosts.isPublicPath("/calculator")).toBe(true);
    expect(hosts.isPublicPath("/calculators")).toBe(false);
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

/**
 * The footer's staff link. Measured on the live site before this existed: a
 * `next/link` to `/login` on the brand host made Next prefetch a route the
 * middleware answers with a 308 to another origin, so every visitor's console
 * carried two blocked-fetch errors per page load.
 */
describe("the staff login link", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("points straight at the panel when the two hosts are configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_BRAND_URL", "https://www.denverhomestory.com");
    vi.stubEnv("NEXT_PUBLIC_PANEL_URL", "https://inmo-demo.ekoaiautomation.com");
    const { STAFF_LOGIN_HREF } = await import("../hosts");
    expect(STAFF_LOGIN_HREF).toBe("https://inmo-demo.ekoaiautomation.com/login");
  });

  it("stays relative on a single-hostname install", async () => {
    vi.stubEnv("NEXT_PUBLIC_BRAND_URL", "");
    vi.stubEnv("NEXT_PUBLIC_PANEL_URL", "");
    const { STAFF_LOGIN_HREF } = await import("../hosts");
    expect(STAFF_LOGIN_HREF).toBe("/login");
  });
});

/**
 * The second allow-list, and the bug that made this file exist.
 *
 * `/fall` was added to `lib/hosts.ts`, the middleware served it on the brand
 * domain, and every test above went green — while `AuthGuard` bounced the
 * visitor to `/login`, because it kept its OWN hand-written copy of "which
 * routes are public". Two lists, one tested. The prerendered HTML proved it:
 * `fall.html` shipped a "Checking session…" spinner and no `<main>`, on a page
 * declaring `robots: index`.
 *
 * The fix was to derive rather than copy, so these assert the derivation holds
 * — not that two lists happen to agree today.
 */
describe("the auth guard cannot fall behind the public list", () => {
  it("never gates a route the brand site publishes", async () => {
    const hosts = await import("../hosts");
    const { isUngatedForTest } = await import("../../components/ui/AuthGuard");
    for (const p of hosts.PUBLIC_PATHS) {
      expect(isUngatedForTest(p)).toBe(true);
    }
    // Sub-paths too: /contact/thanks is public for the same reason /contact is,
    // and the hand-written Set gated it.
    expect(isUngatedForTest("/contact/thanks")).toBe(true);
  });

  it("still lets a stranger reach the two screens that create a session", async () => {
    const { isUngatedForTest } = await import("../../components/ui/AuthGuard");
    // Ungated by the guard, and deliberately NOT in the brand site's list:
    // that list publishes what it contains, and these are panel screens.
    const hosts = await import("../hosts");
    for (const p of ["/login", "/register"]) {
      expect(isUngatedForTest(p)).toBe(true);
      expect(hosts.PUBLIC_PATHS).not.toContain(p);
    }
  });

  it("still gates the panel", async () => {
    const { isUngatedForTest } = await import("../../components/ui/AuthGuard");
    for (const p of ["/leads", "/inbox", "/settings", "/analytics", "/about"]) {
      expect(isUngatedForTest(p)).toBe(false);
    }
  });
});
