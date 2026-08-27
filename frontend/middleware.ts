import { NextResponse, type NextRequest } from "next/server";
import { BRAND_HOST, PANEL_HOST, PANEL_URL, BRAND_URL, isPublicPath } from "@/lib/hosts";

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
  // host would mean redirecting the panel to an empty string.
  if (!BRAND_HOST || !PANEL_HOST || !PANEL_URL || !BRAND_URL) return NextResponse.next();

  // `host` can carry a port (`example.com:3000`) in local and proxied setups.
  const host = (req.headers.get("host") || "").toLowerCase().split(":")[0];
  const { pathname, search } = req.nextUrl;

  // The brand domain serves the brand site only. Anything else on it is the
  // panel, and belongs on the panel's hostname — carrying the path and query
  // so a bookmarked deep link still arrives where it meant to go.
  if (host === BRAND_HOST && !isPublicPath(pathname)) {
    return NextResponse.redirect(`${PANEL_URL}${pathname}${search}`, 308);
  }

  // And the panel's front door is the work, not the marketing page. Only `/`
  // moves: `/contact` stays reachable there so an operator following a link
  // from an email is not bounced across hostnames.
  if (host === PANEL_HOST && pathname === "/") {
    return NextResponse.redirect(`${PANEL_URL}/leads`, 307);
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
