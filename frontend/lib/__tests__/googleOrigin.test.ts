import { describe, expect, it } from "vitest";

import { googleCanSignInFrom } from "../googleOrigin";

/**
 * The bug this exists for: the dashboard was opened at http://10.0.0.240:3004,
 * the Google button rendered as normal, and clicking it landed on Google's
 * "Access blocked: this app's request is invalid" page with
 * `Error 400: redirect_uri_mismatch`. That origin can never work — Google
 * refuses raw IP addresses on Web clients — so no console change would have
 * fixed it, and the page had no way to say so.
 */
describe("googleCanSignInFrom", () => {
  it("refuses an IP address, which Google will never accept", () => {
    expect(googleCanSignInFrom({ protocol: "http:", hostname: "10.0.0.240" })).toBe(
      false,
    );
    // The Tailscale address is the same problem wearing a different number.
    expect(googleCanSignInFrom({ protocol: "http:", hostname: "100.88.47.99" })).toBe(
      false,
    );
    // And over TLS it is still an IP.
    expect(googleCanSignInFrom({ protocol: "https:", hostname: "10.0.0.240" })).toBe(
      false,
    );
  });

  it("accepts localhost, which Google allows over plain http", () => {
    for (const hostname of ["localhost", "127.0.0.1", "[::1]"]) {
      expect(googleCanSignInFrom({ protocol: "http:", hostname })).toBe(true);
    }
  });

  it("accepts the dashboard's own domain over TLS", () => {
    expect(
      googleCanSignInFrom({
        protocol: "https:",
        hostname: "inmo-demo.ekoaiautomation.com",
      }),
    ).toBe(true);
  });

  it("refuses a real domain served without TLS", () => {
    // Google requires https for anything that is not localhost, so offering the
    // button here would be another dead end.
    expect(
      googleCanSignInFrom({ protocol: "http:", hostname: "inmo.example.com" }),
    ).toBe(false);
  });

  it("refuses an intranet name with no registrable domain", () => {
    expect(googleCanSignInFrom({ protocol: "https:", hostname: "rog" })).toBe(false);
  });

  it("refuses an IPv6 literal", () => {
    expect(
      googleCanSignInFrom({ protocol: "https:", hostname: "[2001:db8::1]" }),
    ).toBe(false);
  });

  it("refuses an empty host rather than assuming", () => {
    expect(googleCanSignInFrom({ protocol: "https:", hostname: "" })).toBe(false);
  });
});
