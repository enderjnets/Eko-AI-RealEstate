/**
 * Where the visitor was going before the login got in the way.
 *
 * The new-lead notice now carries a link straight to the lead
 * (`<PANEL_URL>/leads/<id>`). Natalia opens it from her phone, usually with no
 * session in that browser, and until now the guard sent her to `/login` and the
 * three sign-in flows all landed on `/leads` — the list, not the lead the mail
 * was about. The link worked and still lost the thing it pointed at.
 *
 * Two reasons this is `sessionStorage` and not a cookie or a query string the
 * backend echoes back:
 *
 * * The Google flow is `ux_mode=redirect`, so the browser POSTs the credential
 *   from `accounts.google.com` to our callback. That is a CROSS-SITE POST: a
 *   `SameSite=Lax` cookie is not sent with it, and the backend answers with a
 *   303 to `/leads` that carries no state of ours. `sessionStorage` survives
 *   the round trip because it is the same tab and the same origin.
 * * The value never leaves the browser, so it cannot be used to make our own
 *   server redirect somewhere; the only thing that reads it is the code below.
 *
 * `isSafeNext` is the whole security surface. An unvalidated `next` is an open
 * redirect: `//evil.example` is a protocol-relative URL that browsers treat as
 * another origin, and a redirect back to `/login` is an infinite bounce. Both
 * are rejected here rather than at the two call sites, so a third call site
 * cannot forget.
 */

const KEY = "eko.next";

/** Longer than any route this app has; a guard against a padded value. */
const MAX_LENGTH = 512;

/** Paths that must never be a destination: landing on them re-triggers the redirect. */
const NEVER = new Set(["/login", "/register"]);

/**
 * The route a `next` value actually lands on, with `.` and `..` folded away and
 * the query and hash dropped — or null if it would leave this origin.
 *
 * The string is NOT the route: `/leads/../login` and `/./leads` are `/login`
 * and `/leads` once the browser is done with them. A check that compares the
 * raw string sees three different values where the router sees one, which is
 * how `/leads/../login` slipped past the "never land on the login" rule.
 */
export function nextPathname(value: string): string | null {
  // A base is required to resolve a relative path and is irrelevant to the
  // answer: the origin check below is against this same base, so a value that
  // escapes it is rejected wherever the page happens to be served from. The
  // fallback matters in tests and during SSR, where there is no location.
  const base = "https://panel.invalid";
  try {
    const url = new URL(value, base);
    if (url.origin !== base) return null;
    return url.pathname;
  } catch {
    return null;
  }
}

/**
 * True when `value` is a path this app may navigate to after a login.
 *
 * Same-origin and relative ONLY. Anything that could name another host — a
 * scheme, a protocol-relative `//host`, a backslash Windows browsers fold into
 * `/` — is refused, and so is any whitespace, which is how a control character
 * gets smuggled past a naive prefix check.
 */
export function isSafeNext(value: string | null | undefined): value is string {
  if (typeof value !== "string") return false;
  if (value.length === 0 || value.length > MAX_LENGTH) return false;
  // Not trimmed first, on purpose: a value this module wrote has no surrounding
  // space, so whitespace anywhere is evidence it came from somewhere else.
  if (/\s/.test(value)) return false;
  if (!value.startsWith("/")) return false;
  if (value.startsWith("//") || value.startsWith("/\\")) return false;
  const path = nextPathname(value);
  if (path === null) return false;
  // Resolved and case-folded. Next routes case-sensitively, so `/LOGIN` is a
  // 404 rather than the login page — but a destination that 404s is still not
  // a destination, and listing one spelling of a rule invites the others.
  if (NEVER.has(path.toLowerCase().replace(/\/+$/, "") || "/")) return false;
  return true;
}

/**
 * Whether navigating to `next` from `pathname` will change the ROUTE.
 *
 * The guard needs this and a string comparison cannot answer it. `usePathname`
 * carries no query and no hash, so `/leads?utm_source=mail` is a different
 * string from `/leads` and the same route: `router.replace` fires, the pathname
 * does not change, the effect keyed on it never runs again, and the panel sits
 * behind "Checking session…" until somebody reloads. That is reachable without
 * an attacker — an agent opening any tracked link to the panel while signed
 * out is enough.
 */
export function navigationChangesRoute(next: string, pathname: string): boolean {
  const target = nextPathname(next);
  return target !== null && target !== pathname;
}

/**
 * `sessionStorage`, or null. Reading the property itself throws in a browser
 * configured to block site data — not just the calls on it — so even the
 * lookup is guarded.
 */
function storage(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

/** Remember where to go after the login. Unsafe or unstorable values are dropped. */
export function rememberNext(value: string | null | undefined): void {
  if (!isSafeNext(value)) return;
  try {
    storage()?.setItem(KEY, value);
  } catch {
    // Private browsing, quota, a disabled store: the login still works, it just
    // lands on /leads. Losing the destination is not worth a broken sign-in.
  }
}

/**
 * The remembered destination, ONCE. Reading clears it, so a later navigation
 * cannot be hijacked by a value left over from an abandoned login.
 */
export function takeNext(): string | null {
  const s = storage();
  if (!s) return null;
  let value: string | null = null;
  try {
    value = s.getItem(KEY);
    s.removeItem(KEY);
  } catch {
    return null;
  }
  return isSafeNext(value) ? value : null;
}

/**
 * The current location as a `next` value: path + query + hash, never the host.
 *
 * The hash is here because the notice links to a lead and the panel uses
 * anchors inside one; bouncing through a login and landing at the top of a long
 * thread loses the thing the mail was pointing at.
 */
export function currentNext(pathname: string): string {
  let tail = "";
  try {
    const loc = globalThis.location;
    tail = `${loc?.search ?? ""}${loc?.hash ?? ""}`;
  } catch {
    tail = "";
  }
  return `${pathname}${tail}`;
}
