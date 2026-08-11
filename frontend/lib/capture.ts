/**
 * Attribution collected on the landing page.
 *
 * Extracted from the form component so it can be tested: this is the code that
 * decides which video gets credited for a lead, and getting it wrong is
 * invisible — the form still works, the lead still arrives, and the only
 * symptom is that months later nobody can tell which content produced clients.
 */

// Mirrors the backend whitelist in app/services/capture.py. Kept in sync by
// the test below, which fails if this list and the documented one diverge.
export const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
  "gclid",
  "fbclid",
  "landing_variant",
  "tier",
] as const;

export interface ParamSource {
  get(key: string): string | null;
}

/**
 * Whitelisted attribution from the query string, plus the referrer.
 *
 * The referrer is included because several in-app browsers (Instagram's, and
 * TikTok's on some versions) strip query parameters when opening a link, and
 * without it those visits arrive with no attribution at all — which reads in
 * the analytics as "organic search brought them", the one conclusion that is
 * certainly wrong.
 */
export function collectAttribution(
  params: ParamSource,
  referrer?: string | null,
): Record<string, string> {
  const found: Record<string, string> = {};
  for (const key of UTM_KEYS) {
    const value = params.get(key);
    // Trimmed, and empty values dropped rather than sent: `?utm_source=` is
    // noise, and storing "" makes every later "did this lead have a source"
    // query answer yes.
    const cleaned = (value ?? "").trim();
    if (cleaned) found[key] = cleaned;
  }
  const ref = (referrer ?? "").trim();
  if (ref) found.referrer = ref;
  return found;
}
