/**
 * Whether Google sign-in can work at all from a given origin.
 *
 * The button builds its redirect target from `window.location.origin`, so on an
 * origin Google does not know about it sends the user to a Google error page
 * reading "Access blocked: this app's request is invalid" — which a customer in
 * their first week reads as the platform being broken.
 *
 * The important case is not a forgotten console entry. Google refuses raw IP
 * addresses as origins and redirect URIs on Web clients, accepting only
 * `localhost` and public domains, so an install reached at `http://10.0.0.240:3004`
 * can *never* offer Google no matter what is registered. Detecting that and
 * saying where to go instead is the only honest thing the page can do.
 */

/** An IPv4 literal, e.g. `10.0.0.240`. */
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

/** Localhost in the forms a browser reports it. */
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

export interface OriginParts {
  /** `http:` or `https:`, as `window.location.protocol` gives it. */
  protocol: string;
  /** `window.location.hostname` — no port, brackets kept for IPv6. */
  hostname: string;
}

/**
 * True when Google will accept this origin's redirect URI.
 *
 * Deliberately conservative in one direction only: anything it is unsure about
 * counts as unusable, because showing the button when it cannot work costs the
 * user a dead end, while hiding it when it would have worked costs one line of
 * text and the password login still sits above it.
 */
export function googleCanSignInFrom({ protocol, hostname }: OriginParts): boolean {
  // No explicit empty-host guard: an empty host falls through to the final
  // "must contain a dot" test and is refused there. Mutation testing showed the
  // guard could be deleted without any test noticing, which is the definition
  // of code that is not doing anything.
  const host = (hostname || "").toLowerCase();
  if (LOCAL_HOSTS.has(host)) return true;
  // An IPv4 literal, or any IPv6 literal (always bracketed in a URL host).
  if (IPV4.test(host) || host.startsWith("[") || host.includes(":")) return false;
  // A public domain, which Google requires to be served over TLS. Plain http on
  // a real hostname is rejected too, so there is no point offering it.
  if (protocol !== "https:") return false;
  // A bare hostname with no dot is an intranet name, not a registrable domain.
  return host.includes(".");
}

/** The same question, asked of the browser the code is running in. */
export function googleCanSignInHere(): boolean {
  if (typeof window === "undefined") return false;
  return googleCanSignInFrom({
    protocol: window.location.protocol,
    hostname: window.location.hostname,
  });
}
