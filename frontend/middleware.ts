import { NextResponse, type NextRequest } from "next/server";
import { BRAND_HOST, BRAND_URL, PANEL_HOST, PANEL_URL, isPublicPath } from "@/lib/hosts";

/**
 * Send each hostname to the half of the app it is meant to serve.
 *
 * One Next app, two audiences: `www.denverhomestory.com` is where people who
 * watched a video land, and `realtors.ekoaiautomation.com` is where Natalia and
 * Robbie log in to work. Without this, both hostnames serve both halves — the
 * brand domain would answer `/leads` with an internal login screen, and the
 * panel domain would answer `/` with the marketing page.
 *
 * Why a subdomain for the panel and not `ekoaiautomation.com/realtors`: the
 * session cookie is host-only (`auth.py`: httponly, samesite=lax, no `domain=`),
 * so a path under the sales site would share a cookie jar with a different
 * product; and Next has no `basePath` here, so serving the app under a path
 * would rewrite every asset, link and redirect in it.
 *
 * ── Inert until configured ──────────────────────────────────────────────────
 * With `NEXT_PUBLIC_BRAND_URL` / `NEXT_PUBLIC_PANEL_URL` unset — which is the
 * state today, with the domain still parked at GoDaddy — this returns
 * `next()` for everything and the app behaves exactly as it does now. That is
 * not a fallback, it is the requirement: the DNS move happens later and takes
 * hours to propagate, so a middleware that started redirecting to a hostname
 * that does not resolve yet would take production down on deploy.
 */
export function middleware(req: NextRequest) {
  // Both must be known before either redirect is safe. Knowing only the brand
  // host would mean redirecting the panel to an empty string. Testing the HOSTS
  // and not the URLs is deliberate: `hostOf("")` is `""`, so a truthy host
  // already implies a truthy URL — testing both would be dead code that reads
  // like a check.
  //
  // Equal hosts is the third way to be unconfigured, and the only one that
  // fails loudly: pointing both variables at the same name makes every panel
  // route redirect to itself, and `/` bounce to `/leads` and back. An infinite
  // redirect is worse than no redirect, and this is a plausible state to pass
  // through by hand while the DNS moves.
  if (!BRAND_HOST || !PANEL_HOST || BRAND_HOST === PANEL_HOST) {
    return NextResponse.next();
  }

  // `host` can carry a port (`example.com:3000`) in local and proxied setups,
  // and a fully-qualified name may end in a dot (`example.com.`) — which is the
  // SAME name to DNS but a different string here. Without stripping it, a
  // request for `www.denverhomestory.com.` fell through every comparison and
  // served the internal panel under the brand domain.
  const host = (req.headers.get("host") || "")
    .toLowerCase()
    .split(":")[0]
    .replace(/\.+$/, "");
  const { pathname, search } = req.nextUrl;

  // The brand domain serves the brand site only. Anything else on it is the
  // panel, and belongs on the panel's hostname — carrying the path and query
  // so a bookmarked deep link still arrives where it meant to go.
  if (host === BRAND_HOST && !isPublicPath(pathname)) {
    return NextResponse.redirect(`${PANEL_URL}${pathname}${search}`, 308);
  }

  // And the panel's front door is the work, not the marketing page.
  if (host === PANEL_HOST && pathname === "/") {
    return NextResponse.redirect(`${PANEL_URL}/leads`, 307);
  }

  // Every other public page belongs to the brand domain, and only there.
  //
  // Measured on the live site before this existed: the panel hostname answered
  // `/fall`, `/contact` and `/calculator` with the SAME bytes as the brand one
  // — one page, two addresses. The canonical tag asked Google to prefer the
  // brand, but a canonical is a hint, and the robots.txt Cloudflare serves on
  // both hostnames rewrites to `Allow: /` for every crawler, so nothing except
  // that hint kept the domain the funnel points at from competing with a copy
  // of itself.
  //
  // This replaces an earlier decision that kept `/contact` reachable here "so
  // an operator following a link from an email is not bounced across
  // hostnames". That link is not one this system sends: the only URL any
  // outgoing mail carries is `PANEL_URL/leads/<id>` (`lead_notify.py`), and no
  // panel screen links to a public path. A hand-saved bookmark still works —
  // it arrives at the same page on the address the public is meant to see.
  //
  // `/` is excluded twice over, and neither is redundant with the other: the
  // rule above returns first, AND the guard here is false for it. Belt and
  // braces, because each covers the other's failure — a reorder that moves
  // this rule up, or a guard someone deletes as "dead". No test can tell them
  // apart (removing either one alone stays green, measured), so this comment is
  // the only place that says the duplication is deliberate.
  if (host === PANEL_HOST && pathname !== "/" && isPublicPath(pathname)) {
    const res = NextResponse.redirect(`${BRAND_URL}${pathname}${search}`, 308);
    // 308 for crawlers, uncached for people. Measured before adding this: the
    // redirect went out with no `Cache-Control` at all, and a 308 with no
    // directive is cacheable by default (RFC 7538) — a browser that saw it once
    // would keep redirecting without asking again. That makes the one failure
    // that matters irreversible: point `NEXT_PUBLIC_BRAND_URL` at a hostname
    // that does not resolve, deploy, and unsetting the variable does NOT bring
    // those visitors back. Consolidation is unaffected: Google decides from the
    // status code, not from this header.
    res.headers.set("Cache-Control", "no-store");
    return res;
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Everything except Next's own assets, the API proxy and static files.
   *
   * `/api` is excluded for a concrete reason, not tidiness: the public capture
   * form posts to `/api/v1/public/leads` from the brand domain, and `/api` is
   * not in PUBLIC_PATHS, so without this exclusion every form submission from
   * the landing would be 308-redirected to the panel hostname. A redirected
   * POST is not replayed as a POST by every client, and the ones that do
   * replay it would be sending a lead's phone number across an origin the
   * page never intended. The form would appear to work and quietly lose leads.
   */
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.[\\w]+$).*)"],
};
