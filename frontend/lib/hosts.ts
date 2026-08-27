/**
 * Which hostname serves the brand page, and which serves the panel.
 *
 * One Next app serves both: the public landing at `/` and the operator panel at
 * `/leads`, `/inbox`, `/settings`… Until now that was fine, because there was
 * one hostname. With `www.denverhomestory.com` pointing at the same app,
 * `www.denverhomestory.com/leads` would serve the internal login — and, worse,
 * `page.tsx` declares `robots: index, follow`, so the same marketing page would
 * be indexed under every hostname that reaches it and the domain the funnel
 * depends on would compete against itself.
 *
 * The fix is NOT a robots.txt: Cloudflare prepends its own `Allow: /` and
 * Google honours the least restrictive rule — that has already happened on this
 * infrastructure. It has to be redirects and canonical tags, which is what
 * `middleware.ts` and the page metadata do with the values below.
 *
 * ── Everything here is inert until configured, and that is deliberate ────────
 * The domain is still parked at GoDaddy; the nameserver move to Cloudflare
 * happens later and takes hours to propagate. A middleware that redirected the
 * panel to a hostname that does not resolve yet would take production down, and
 * a canonical tag pointing at a dead domain would deindex the page that is
 * live today. So an unset variable means "do nothing", never "guess".
 */

/** Public brand site, e.g. `https://www.denverhomestory.com`. Empty until DNS moves. */
export const BRAND_URL = (process.env.NEXT_PUBLIC_BRAND_URL || "").trim().replace(/\/$/, "");

/** Operator panel, e.g. `https://realtors.ekoaiautomation.com`. Empty until DNS moves. */
export const PANEL_URL = (process.env.NEXT_PUBLIC_PANEL_URL || "").trim().replace(/\/$/, "");

/** Hostname only, lowercased, no port — what a request's `host` header compares against. */
function hostOf(url: string): string {
  if (!url) return "";
  try {
    // Trailing dot stripped for the same reason the middleware strips it from
    // the request: `example.com.` and `example.com` are one name to DNS and two
    // strings to `===`. Normalising both sides is what makes the comparison mean
    // "same host".
    return new URL(url).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    // A malformed value must not throw inside middleware, which would 500 every
    // request on the site. Treating it as unset degrades to today's behaviour.
    return "";
  }
}

export const BRAND_HOST = hostOf(BRAND_URL);
export const PANEL_HOST = hostOf(PANEL_URL);

/**
 * Routes that belong to the public brand site. Everything else in the app is
 * the panel.
 *
 * An allow-list, not a block-list of panel routes: a new page added next month
 * is far more likely to be another panel screen than another marketing page, so
 * the failure mode of forgetting to update this list is "an internal page is
 * not reachable on the brand domain" — which is the safe direction. A
 * block-list would silently publish it instead.
 *
 * `/about` is deliberately NOT here, and the reason is the whole point of the
 * split. That page sells THIS PLATFORM to real-estate agencies — "the AI agent
 * that handles your WhatsApp 24/7… your own office hardware". The people who
 * reach the brand domain are Denver home sellers who watched a video; showing
 * them the pitch we make to their agent's competitors is the single worst page
 * we could serve there. It stays reachable internally.
 */
export const PUBLIC_PATHS = ["/", "/contact"];

/** `/contact` and `/contact/anything` both count; `/contactos` does not. */
export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || (p !== "/" && pathname.startsWith(`${p}/`)),
  );
}
