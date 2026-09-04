/**
 * What the landing page reports about itself.
 *
 * Split out from the component for the same reason `capture.ts` is: these are
 * the rules that decide whether a report says "TikTok brought forty visits" or
 * says nothing at all, and getting them wrong is invisible — the page still
 * works, the form still submits, and the only symptom is a dashboard of zeroes
 * that nobody can explain.
 *
 * Nothing here identifies a person. The session key is random, lives in
 * `sessionStorage`, and dies with the tab; the server stores no IP and reduces
 * the user agent to a family before writing it. That is what makes this
 * reportable without a consent banner — and why the Global Privacy Control
 * check below is honoured rather than argued with.
 */

import { UTM_KEYS, collectAttribution, type ParamSource } from "./capture";

/** Where the session key and the first-touch attribution live for this tab. */
export const SESSION_STORAGE_KEY = "dhs.sid";
export const ATTRIBUTION_STORAGE_KEY = "dhs.attr";

/** The endpoint. Same origin, so the Next rewrite proxies it to the backend. */
export const BEACON_URL = "/api/v1/public/landing";

/** Must match `EVENTS_MAX_PER_BATCH` in `backend/app/api/v1/public.py`. */
export const MAX_PER_BATCH = 25;

/** How long a batch may sit before it is sent anyway. */
export const FLUSH_AFTER_MS = 10_000;

export type EventName =
  | "page_view"
  | "section_view"
  | "scroll"
  | "cta_click"
  | "tel_click"
  | "form_start"
  | "form_submit"
  | "form_error";

/** Sent the moment they happen: each one is a funnel step, and a visitor who
 *  taps "call" is on their way out of the page — a queued batch would never
 *  leave. The rest ride the next flush. */
const IMMEDIATE: ReadonlySet<EventName> = new Set<EventName>([
  "cta_click",
  "tel_click",
  "form_start",
  "form_submit",
  "form_error",
]);

/**
 * Whether a section counts as seen.
 *
 * Not `IntersectionObserver`'s own ratio, and that is the whole point: its
 * ratio is a fraction of the ELEMENT, so a block taller than the screen can
 * never reach it. Measured against production on an iPhone 13 (viewport
 * 664 px): `#about` is 1 249 px tall, so the most it can ever intersect is
 * **0.53** — with a 0.5 threshold it counted only when almost perfectly
 * centred, and two of the four sections were simply never reported. The
 * metric said "they did not read that far" when they had.
 *
 * The rule here is "half of whatever can fit": half the screen for a section
 * taller than the screen, half the section for one shorter than it. Both ends
 * stay reachable, which a fraction of either alone does not.
 */
export const SECTION_SEEN_RATIO = 0.5;

export function sectionWasSeen(
  visible: number,
  sectionHeight: number,
  viewportHeight: number,
): boolean {
  if (!(visible > 0) || !(sectionHeight > 0) || !(viewportHeight > 0)) return false;
  return visible >= SECTION_SEEN_RATIO * Math.min(sectionHeight, viewportHeight);
}

/** The depths worth knowing. More would be noise; fewer would not distinguish
 *  "bounced" from "read the whole thing". */
export const SCROLL_MARKS = [25, 50, 75, 100] as const;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/**
 * A 32-character hex key. Random, per tab, and deliberately not derived from
 * anything about the visitor.
 *
 * Falls back to `Math.random` when `crypto` is missing, and that fallback is
 * the point rather than an afterthought. Without it a browser with no `crypto`
 * throws here, `sessionKey`'s catch calls this again, it throws again, and the
 * exception escapes the effect and takes the page down — analytics breaking the
 * marketing page is the one failure this whole feature must not have. The key
 * only has to be unique among one agency's visits in a day; it authenticates
 * nothing and guards nothing.
 */
export function newSessionKey(random?: (a: Uint8Array) => Uint8Array): string {
  const fill =
    random ??
    ((a: Uint8Array) => {
      const source = globalThis.crypto;
      if (source?.getRandomValues) {
        source.getRandomValues(a);
        return a;
      }
      for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256);
      return a;
    });
  const bytes = fill(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * This tab's session key, created on first use.
 *
 * Every access is guarded: Instagram's and TikTok's embedded browsers, and any
 * browser set to block site data, throw on `sessionStorage` rather than
 * returning null. Those are exactly the visitors this page most needs to count,
 * so a throw falls back to a key held in memory — one session per page load
 * instead of per visit, which undercounts rather than crashes.
 */
export function sessionKey(storage: StorageLike | null | undefined): string {
  try {
    const existing = storage?.getItem(SESSION_STORAGE_KEY);
    if (existing && /^[0-9a-f]{32}$/.test(existing)) return existing;
    const fresh = newSessionKey();
    storage?.setItem(SESSION_STORAGE_KEY, fresh);
    return fresh;
  } catch {
    return newSessionKey();
  }
}

/**
 * Remember the attribution this visit arrived with. First touch wins.
 *
 * Without this the attribution is read from the URL when the form mounts, so a
 * visitor who lands on `/?utm_source=tiktok`, reads three sections and then
 * scrolls to the form has already lost it — the query string is still in the
 * address bar, but a client-side navigation would not be. Same rule the server
 * applies to a lead's first touch, applied one layer earlier.
 */
export function persistAttribution(
  params: ParamSource,
  referrer: string | null | undefined,
  storage: StorageLike | null | undefined,
): Record<string, string> {
  const stored = storedAttribution(storage);
  if (Object.keys(stored).length > 0) return stored;

  const collected = collectAttribution(params, referrer);
  if (Object.keys(collected).length === 0) return {};
  try {
    storage?.setItem(ATTRIBUTION_STORAGE_KEY, JSON.stringify(collected));
  } catch {
    // Unwritable storage costs the memory of the first touch, nothing else.
  }
  return collected;
}

/** What was remembered earlier this visit, filtered to the same whitelist the
 *  backend enforces — storage is writable by anything else on the origin. */
export function storedAttribution(
  storage: StorageLike | null | undefined,
): Record<string, string> {
  try {
    const raw = storage?.getItem(ATTRIBUTION_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const allowed = new Set<string>([...UTM_KEYS, "referrer"]);
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (allowed.has(key) && typeof value === "string" && value.trim()) {
        out[key] = value.trim().slice(0, 200);
      }
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * Whether this visitor has asked not to be measured.
 *
 * Colorado — where this agency and most of its visitors are — requires that a
 * universal opt-out signal be honoured, and Global Privacy Control is the one
 * browsers send. Cheap to respect and not ours to argue with: with it set, the
 * tracker sends nothing at all rather than sending something anonymised.
 */
export function trackingAllowed(nav: unknown): boolean {
  const gpc = (nav as { globalPrivacyControl?: unknown } | null | undefined)
    ?.globalPrivacyControl;
  return gpc !== true;
}

export interface TrackerOptions {
  form?: string;
  session: string;
  path: string;
  lang?: "en" | "es";
  screenW?: number;
  utm?: Record<string, string>;
  referrer?: string | null;
  allowed?: boolean;
  /** Returns false when the send could not be handed off, so the caller can
   *  decide; the tracker itself does not retry — a dropped beacon is a dropped
   *  measurement, never a dropped lead. */
  send: (body: string) => boolean;
}

interface QueuedEvent {
  t: EventName;
  meta?: Record<string, string | number>;
}

export class Tracker {
  private readonly opts: TrackerOptions;
  private queue: QueuedEvent[] = [];
  private readonly sections = new Set<string>();
  private readonly marks = new Set<number>();
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: TrackerOptions) {
    this.opts = opts;
  }

  get allowed(): boolean {
    return this.opts.allowed !== false;
  }

  /** Record an event. Deduplication happens here rather than at the server so
   *  a page that scrolls past 50% four times costs one event, not four. */
  record(name: EventName, meta?: Record<string, string | number>): void {
    if (!this.allowed) return;
    this.queue.push(meta && Object.keys(meta).length > 0 ? { t: name, meta } : { t: name });
    if (IMMEDIATE.has(name) || this.queue.length >= MAX_PER_BATCH) {
      this.flush();
      return;
    }
    this.arm();
  }

  section(name: string): void {
    if (this.sections.has(name)) return;
    this.sections.add(name);
    this.record("section_view", { section: name });
  }

  /** Report crossing a depth mark, once each. Takes the raw percentage. */
  scrolled(pct: number): void {
    if (!Number.isFinite(pct)) return;
    for (const mark of SCROLL_MARKS) {
      if (pct >= mark && !this.marks.has(mark)) {
        this.marks.add(mark);
        this.record("scroll", { pct: mark });
      }
    }
  }

  flush(): void {
    this.disarm();
    if (!this.allowed || this.queue.length === 0) return;
    const events = this.queue.slice(0, MAX_PER_BATCH);
    this.queue = this.queue.slice(MAX_PER_BATCH);
    const body: Record<string, unknown> = { session: this.opts.session, events };
    if (this.opts.form) body.form = this.opts.form;
    if (this.opts.path) body.path = this.opts.path;
    if (this.opts.lang) body.lang = this.opts.lang;
    if (typeof this.opts.screenW === "number") body.screen_w = this.opts.screenW;
    if (this.opts.utm && Object.keys(this.opts.utm).length > 0) body.utm = this.opts.utm;
    if (this.opts.referrer) body.referrer = this.opts.referrer;
    this.opts.send(JSON.stringify(body));
    // Anything past the batch cap goes out next; the loop is bounded because
    // `slice` always shortens the queue.
    if (this.queue.length > 0) this.flush();
  }

  private arm(): void {
    if (this.timer !== null) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush();
    }, FLUSH_AFTER_MS);
  }

  private disarm(): void {
    if (this.timer === null) return;
    clearTimeout(this.timer);
    this.timer = null;
  }

  stop(): void {
    this.disarm();
  }
}

/**
 * A sender built on `navigator.sendBeacon`, falling back to `fetch`.
 *
 * `text/plain` rather than `application/json`: a beacon carrying a JSON Blob is
 * refused outright by Chromium in some contexts, and the backend parses the
 * body by hand for exactly this reason. `keepalive` on the fallback so a send
 * fired from `pagehide` survives the navigation that triggered it.
 */
export function beaconSender(
  url: string = BEACON_URL,
  nav: Navigator | undefined = typeof navigator === "undefined" ? undefined : navigator,
  fetcher: typeof fetch | undefined = typeof fetch === "undefined" ? undefined : fetch,
): (body: string) => boolean {
  return (body: string) => {
    try {
      if (nav?.sendBeacon) {
        const blob = new Blob([body], { type: "text/plain" });
        if (nav.sendBeacon(url, blob)) return true;
      }
    } catch {
      // Fall through: a beacon that throws is a beacon that did not send.
    }
    try {
      void fetcher?.(url, {
        method: "POST",
        body,
        keepalive: true,
        headers: { "Content-Type": "text/plain" },
        cache: "no-store",
      })?.catch(() => undefined);
      return true;
    } catch {
      return false;
    }
  };
}

let current: Tracker | null = null;

/** The page's tracker, for the form to reach without prop-drilling through
 *  every section between it and the root. Null before the page mounts. */
export function getTracker(): Tracker | null {
  return current;
}

export function setTracker(tracker: Tracker | null): void {
  current = tracker;
}
