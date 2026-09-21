import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "../../app/blog/[...asset]/route";
import { middleware } from "../../middleware";
const req = (path: string, authorization?: string) => new NextRequest(`https://www.denverhomestory.com${path}`, { headers: authorization ? { authorization } : {} });
const auth = (password: string) => `Basic ${btoa(`journal:${password}`)}`;
afterEach(() => vi.unstubAllEnvs());
describe("private Journal", () => {
  it.each(["/blog", "/blog/twelve-houses-worth-the-detour", "/blog/img/richmond-0.jpg", "/blog/denver-skyline.jpg"])("challenges anonymous access to %s even with host split unset", async (path) => {
    const res = await middleware(req(path));
    expect(res.status).toBe(401);
    expect(res.headers.get("www-authenticate")).toContain("Basic");
    expect(res.headers.get("cache-control")).toContain("no-store");
  });
  it("fails closed when no password is configured", async () => {
    vi.stubEnv("JOURNAL_PREVIEW_PASSWORD", "");
    expect((await middleware(req("/blog", auth("")))).status).toBe(401);
  });
  it("rejects wrong passwords and malformed credentials", async () => {
    vi.stubEnv("JOURNAL_PREVIEW_PASSWORD", "a-long-example-password-for-test");
    for (const value of [auth("wrong"), "Basic !!!", "Bearer test"]) {
      expect((await middleware(req("/blog", value))).status).toBe(401);
    }
  });
  it("accepts valid credentials with private cache headers", async () => {
    vi.stubEnv("JOURNAL_PREVIEW_PASSWORD", "a-long-example-password-for-test");
    const res = await middleware(req("/blog", auth("a-long-example-password-for-test")));
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toContain("no-store");
    expect(res.headers.get("x-robots-tag")).toContain("noindex");
  });
  it("does not gate the calculator", async () => {
    expect((await middleware(req("/calculator"))).status).toBe(200);
  });
});


describe("private media route independent of middleware", () => {
  it("denies a direct route call without credentials", async () => {
    const response = await GET(req("/blog/img/richmond-0.jpg"), { params: { asset: ["img", "richmond-0.jpg"] } });
    expect(response.status).toBe(401);
  });
  it("rejects traversal even with valid credentials", async () => {
    vi.stubEnv("JOURNAL_PREVIEW_PASSWORD", "a-long-example-password-for-test");
    for (const asset of [["..", "..", ".env"], ["img", "../../.env"], ["img", "%2e%2e", ".env"]]) {
      const response = await GET(req("/blog/img/x.jpg", auth("a-long-example-password-for-test")), { params: { asset } });
      expect(response.status).toBe(404);
    }
  });
  it("serves an authorized image without allowing caching", async () => {
    vi.stubEnv("JOURNAL_PREVIEW_PASSWORD", "a-long-example-password-for-test");
    const response = await GET(req("/blog/denver-skyline.jpg", auth("a-long-example-password-for-test")), { params: { asset: ["denver-skyline.jpg"] } });
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("content-type")).toBe("image/jpeg");
    expect((await response.arrayBuffer()).byteLength).toBeGreaterThan(1000);
  });
});
