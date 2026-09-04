"use client";

/**
 * Wires the page to the tracker. All the rules live in `lib/track.ts`; this is
 * only the browser plumbing, which is why it holds no logic worth testing and
 * `track.ts` holds nothing that needs a DOM.
 *
 * Mounted as a sibling of <main>, like the mobile menu, and for a related
 * reason: it attaches document-level listeners, and living inside the pinned
 * hero — which is `position: sticky` with `overflow: hidden` and acquires
 * `will-change: transform` when the sticky fallback fires — is where components
 * on this page acquire surprising containing blocks.
 *
 * Renders nothing.
 */

import { useEffect } from "react";
import {
  Tracker,
  beaconSender,
  persistAttribution,
  sessionKey,
  setTracker,
  trackingAllowed,
} from "@/lib/track";
import { useI18n } from "@/lib/i18n";

const FORM_KEY = process.env.NEXT_PUBLIC_CAPTURE_FORM_KEY || undefined;

/** Marks the visit as having come from this page, exactly as the form does. */
const LANDING_VARIANT = "landing";

/** The sections an IntersectionObserver reports. Must match `LANDING_SECTIONS`
 *  in `backend/app/models/landing.py`: the server drops anything else. */
const SECTIONS = ["about", "how", "markets", "consult"] as const;

export function LandingTracker() {
  const { lang } = useI18n();

  useEffect(() => {
    if (typeof window === "undefined") return;

    // `window.location.search` rather than `useSearchParams`: that hook opts
    // the whole page out of static rendering unless it is wrapped in a
    // Suspense boundary — the build fails outright otherwise — and this
    // component renders nothing and reads the query once, after mount, when
    // `window.location` is the authority anyway. `ConsultForm` uses the hook
    // because its value drives what it renders; this one does not.
    const params = new URLSearchParams(window.location.search);

    const storage = (() => {
      try {
        return window.sessionStorage;
      } catch {
        // Blocked site data, or a privacy mode that throws on access rather
        // than returning null. The tracker degrades to one session per load.
        return null;
      }
    })();

    const collected = persistAttribution(params, document.referrer, storage);
    const tracker = new Tracker({
      form: FORM_KEY,
      session: sessionKey(storage),
      path: window.location.pathname,
      lang: lang === "es" ? "es" : "en",
      screenW: window.innerWidth,
      utm: { landing_variant: LANDING_VARIANT, ...collected },
      referrer: document.referrer || null,
      allowed: trackingAllowed(navigator),
      send: beaconSender(),
    });
    setTracker(tracker);
    tracker.record("page_view");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && entry.target.id) tracker.section(entry.target.id);
        }
      },
      { threshold: 0.5 },
    );
    for (const id of SECTIONS) {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    }

    const onScroll = () => {
      const doc = document.documentElement;
      const scrollable = doc.scrollHeight - window.innerHeight;
      // A page shorter than the viewport has been read in full by definition;
      // reporting 0% there would make every such visit look like a bounce.
      tracker.scrolled(scrollable <= 0 ? 100 : (window.scrollY / scrollable) * 100);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // Delegated rather than per-anchor: the mobile menu's links do not exist
    // until it opens, so anything bound at mount would miss them.
    const onClick = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      const where = anchor.dataset.track || "unknown";
      const href = anchor.getAttribute("href") || "";
      if (href.startsWith("tel:")) tracker.record("tel_click", { where });
      else if (href === "#consult") tracker.record("cta_click", { where });
    };
    document.addEventListener("click", onClick, true);

    const onHide = () => {
      if (document.visibilityState === "hidden") tracker.flush();
    };
    document.addEventListener("visibilitychange", onHide);
    // Bound to a name, not an inline arrow: an arrow cannot be removed, so the
    // listener would outlive the effect holding a tracker that is already torn
    // down — and every remount would add another.
    const onPageHide = () => tracker.flush();
    window.addEventListener("pagehide", onPageHide);

    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
      tracker.flush();
      tracker.stop();
      setTracker(null);
    };
    // Deliberately once per mount. Re-running on a language switch would mint
    // a second page view for the same visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
