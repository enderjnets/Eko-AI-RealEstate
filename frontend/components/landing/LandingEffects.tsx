"use client";

/**
 * The v6 scroll choreography, ported from the design's `deploy-v6/index.html`
 * (the `<script>` at the end of that file is the authoritative engine — this
 * is that engine, kept as literal as TypeScript and React mounting allow).
 *
 * It is attribute-driven and owns no markup: `Landing.tsx` carries the same
 * `data-*` attributes the design's artboards carry, and this component makes
 * them move —
 *
 *   data-pin-host           the hero: a section several viewports tall whose
 *                           sticky stage stays on screen while progress p runs
 *                           0→1 down the host
 *   data-pin-stage          that stage — viewport-tall, sticky at the top
 *   data-cap="a,b"          a caption on the stage, visible while a ≤ p ≤ b and
 *                           fading over the outer 20% of that window; while
 *                           hidden it takes no clicks, no keyboard focus and
 *                           is out of the accessibility tree (visibility)
 *   data-pin-bar            the hairline progress bar: width = p
 *   data-hero-video         the playhead follows p. Forward is real playback at
 *                           a variable rate (smooth); scrolling back is a seek.
 *                           Off screen it pauses.
 *   data-reveal="up|clip"   sections blur/slide in when they near the viewport,
 *                           staggered 120ms between siblings; inside a rail the
 *                           slide comes from the right. The blur is skipped on
 *                           a coarse pointer. Anything that has sat inside a
 *                           viewport for 4s shows regardless.
 *   data-drift="px"         headings drift against the scroll
 *   data-parallax="amt"     portrait and market cards (0.10), consult (0.24)
 *   data-rail               the markets rail: drag to scroll
 *
 * What was deliberately NOT ported from deploy-v6: its artboard-zoom
 * "responsive" block (it zooms fixed 1440/390 layouts; our page is genuinely
 * responsive), its twin-video activation (two artboards, two <video>s — this
 * page has one), its transform-aware anchor navigation (ours is native + CSS
 * smooth), and its CDN Lucide painter (we use lucide-react).
 *
 * Two deliberate departures, written down so nobody "fixes" them back:
 *
 *  1. Past the end of the host the design free-runs the clip on loop. This
 *     clip cannot loop: it ends on the house and opens inside a different
 *     room (docs/hero-video-procedencia.md), so a loop is a hard cut. The
 *     playhead simply holds on the last frame instead.
 *  2. prefers-reduced-motion: reveals are marked done, drift and parallax
 *     never move, and the video stays parked on its first frame. The captions
 *     still crossfade with the scroll — they ARE the hero's copy, and hiding
 *     three of the four would remove content, not motion — but without the
 *     26px lift. That visitor scrolls the hero over one still frame; it is
 *     the design's at-top composition, static, the same call 54ca7e7 made
 *     for v4.
 */

import { useEffect } from "react";

const EASE = "cubic-bezier(.22,.61,.36,1)";

/* The engine tracks per-element state in expando properties, exactly like the
   original. A WeakMap would be tidier; staying close to the source is worth
   more here — every behavioral diff from deploy-v6 that the header does not
   list is a bug by definition. */
type Host = HTMLElement & { __js?: boolean | null };
type El = HTMLElement & {
  __done?: number;
  __rv?: number;
  __d?: number;
  __pending?: number;
  __safe?: number;
};
type Vid = HTMLVideoElement & { __target?: number | null; __pl?: number; __rt?: number };

export function LandingEffects() {
  useEffect(() => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    // deploy-v6 skips the reveal blur on touch: a filter over a full-width
    // section is the most expensive thing on this page, and on a phone held
    // at arm's length nobody sees the 9px it saves.
    const coarse = matchMedia("(pointer: coarse)").matches;
    let disposed = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    // ---------- Video: prime (decode frame 0), then let the scroll drive it ----------
    const kick = () => {
      document.querySelectorAll<Vid>("video[data-hero-video]").forEach((v) => {
        v.muted = true;
        v.defaultMuted = true;
        v.playsInline = true;
        v.preload = "auto";
        const p = v.play();
        if (p && p.then) p.then(() => v.pause()).catch(() => {});
        else v.pause();
      });
    };
    kick();
    timers.push(setTimeout(kick, 400), setTimeout(kick, 1600));
    document.addEventListener("pointerdown", kick, { once: true });
    document.addEventListener("touchstart", kick, { once: true, passive: true });

    // Forward motion is real playback at a variable rate (smooth); only
    // scrolling back falls back to a seek.
    let scrubRaf = 0;
    const ease = () => {
      if (disposed) return;
      scrubRaf = requestAnimationFrame(ease);
      document.querySelectorAll<Vid>("video[data-hero-video]").forEach((v) => {
        if (!v.duration || v.seeking || v.__target == null) return;
        const cur = v.currentTime || 0;
        const d = v.__target - cur;
        if (d > 0.06) {
          // Two speeds, and a 400ms hold between changes — deploy-v6's, not a
          // continuous rate. A playbackRate recomputed every frame makes the
          // decoder re-plan constantly and the picture judders under the scroll.
          const now = performance.now();
          const want = d > 1.6 ? 2 : d < 0.9 ? 1 : v.playbackRate;
          if (v.playbackRate !== want && (!v.__rt || now - v.__rt > 400)) {
            v.playbackRate = want;
            v.__rt = now;
          }
          if (v.paused && !v.__pl) {
            v.__pl = 1;
            const p = v.play();
            if (p && p.then) p.then(() => { v.__pl = 0; }).catch(() => { v.__pl = 0; });
            else v.__pl = 0;
          }
        } else if (d < -0.35) {
          if (!v.paused) v.pause();
          v.currentTime = v.__target;
        } else if (d <= 0.01) {
          if (!v.paused) v.pause();
        }
      });
    };
    ease();

    // ---------- Scroll choreography ----------
    const show = (el: El, animate: boolean) => {
      el.__done = 1;
      if (animate) {
        const slow = el.getAttribute("data-reveal") === "clip";
        el.style.transition = slow
          ? `opacity 1100ms ${EASE}, transform 2600ms ${EASE}, clip-path 2600ms ${EASE}, filter 1800ms ${EASE}`
          : `opacity 900ms ${EASE}, transform 1400ms ${EASE}, clip-path 1400ms ${EASE}, filter 1000ms ${EASE}`;
      }
      el.style.opacity = "1";
      el.style.transform = "none";
      el.style.clipPath = "inset(0 0 0 0)";
      el.style.filter = "none";
    };

    const arm = (el: El) => {
      el.__rv = 1;
      const sibs = Array.prototype.filter.call(
        el.parentElement?.children ?? [],
        (c: Element) => c.hasAttribute && c.hasAttribute("data-reveal"),
      );
      const i = sibs.indexOf(el);
      el.__d =
        (parseInt(el.getAttribute("data-reveal-delay") || "0", 10) || 0) +
        (sibs.length > 1 ? i * 120 : 0);
      el.style.willChange = "opacity, transform, filter";
      el.style.opacity = "0";
      if (el.getAttribute("data-reveal") === "clip") {
        el.style.clipPath = "inset(34% 0 0 0)";
        el.style.transform = "scale(1.14)";
      } else if (el.closest("[data-rail]")) {
        el.style.transform = "translate3d(130px,0,0) scale(0.94)";
        if (!coarse) el.style.filter = "blur(12px)";
      } else {
        el.style.transform = "translate3d(0,64px,0) scale(0.98)";
        if (!coarse) el.style.filter = "blur(9px)";
      }
    };

    if (reduce) {
      document.querySelectorAll<El>("[data-reveal]").forEach((el) => {
        el.__done = 1;
      });
    }

    let rafId = 0;
    const tick = () => {
      rafId = 0;
      if (disposed) return;
      const vh = innerHeight || 1;

      if (!reduce)
        document.querySelectorAll<El>("[data-reveal]").forEach((el) => {
          if (el.__done || el.__pending) return;
          if (el.offsetParent === null) return; // hidden — leave as authored
          const r = el.getBoundingClientRect();
          const m = el.getAttribute("data-reveal") === "clip" ? 1.0 : 0.82;
          const near = r.top < vh * m || r.bottom < vh;
          if (!el.__rv) {
            // First sighting. Already on screen = shown without ceremony:
            // nothing on the first viewport may blink into place after load.
            if (r.top < vh * 1.02 || r.bottom < vh) el.__done = 1;
            else arm(el);
            return;
          }
          if (r.bottom < 0) {
            show(el, false);
            return;
          }
          // Belt and braces: a section that has sat inside a viewport for 4s
          // shows anyway, so a missed event can never leave one invisible.
          if (!el.__safe && r.top < vh) {
            el.__safe = 1;
            timers.push(setTimeout(() => { if (!el.__done) show(el, true); }, 4000));
          }
          if (near) {
            el.__pending = 1;
            timers.push(setTimeout(() => show(el, true), el.__d || 0));
          }
        });

      // Scroll-locked hero: sticky stage, progress drives playhead + captions.
      document.querySelectorAll<Host>("[data-pin-host]").forEach((host) => {
        const stage = host.querySelector<HTMLElement>("[data-pin-stage]");
        if (!stage || host.offsetParent === null) return;
        const r = host.getBoundingClientRect();
        const sr = stage.getBoundingClientRect();
        const p = Math.max(0, Math.min(1, -r.top / Math.max(1, r.height - sr.height)));
        /* Once, well inside the host, ask whether `position: sticky` actually
           stuck. It silently does not when any ancestor has a non-visible
           overflow — the exact bug `globals.css` had to fix for this page — and
           the failure mode is the whole film scrolling past in one screen. If
           the stage is not at the top when it should be, drive it by hand.
           `sc` is 1 here (nothing scales the page); it is the design's, kept so
           an ancestor transform some day cannot silently halve the travel. */
        if (host.__js == null && r.top < -40 && r.bottom > sr.height + 40) {
          host.__js = Math.abs(sr.top) > 3;
          if (host.__js) {
            stage.style.position = "absolute";
            stage.style.left = "0";
            stage.style.right = "0";
            stage.style.willChange = "transform";
          }
        }
        if (host.__js) {
          const sc = r.height / (host.offsetHeight || 1) || 1;
          const travel = Math.max(1, host.offsetHeight - stage.offsetHeight);
          const y = Math.max(0, Math.min(1, -r.top / (travel * sc))) * travel;
          stage.style.transform = `translate3d(0,${y.toFixed(1)}px,0)`;
        }
        host.querySelectorAll<HTMLElement>("[data-cap]").forEach((c) => {
          const ab = (c.getAttribute("data-cap") || "0,1").split(",").map(Number);
          const a = ab[0];
          const b = ab[1];
          const f = Math.max(0.01, 0.2 * (b - a));
          let o = 0;
          if (p >= a && p <= b) {
            const fi = a <= 0 ? 1 : Math.min(1, (p - a) / f);
            const fo = b >= 1 ? 1 : Math.min(1, (b - p) / f);
            o = Math.min(fi, fo);
          }
          c.style.opacity = o.toFixed(3);
          c.style.transform = reduce ? "none" : `translate3d(0,${((1 - o) * 26).toFixed(1)}px,0)`;
          c.style.pointerEvents = o > 0.5 ? "auto" : "none";
          // Not in the design: opacity 0 leaves the caption's buttons in the
          // Tab order and in the accessibility tree, so a keyboard user would
          // land on an invisible "Book a consult". visibility drops them out.
          c.style.visibility = o > 0 ? "visible" : "hidden";
        });
        const bar = host.querySelector<HTMLElement>("[data-pin-bar]");
        if (bar) bar.style.width = `${(p * 100).toFixed(2)}%`;
        const v = host.querySelector<Vid>("video[data-hero-video]");
        if (!v || !v.duration || isNaN(v.duration)) return;
        if (reduce || r.bottom < -60 || r.top > vh + 60) {
          if (!v.paused) v.pause();
          v.__target = null;
          return;
        }
        // Clamped, never free-running: departure 1 in the header.
        v.__target = Math.min(v.duration - 0.05, p * v.duration);
      });

      if (!reduce) {
        document.querySelectorAll<El>("[data-drift]").forEach((el) => {
          if (el.hasAttribute("data-reveal") && !el.__done) return;
          const r = el.getBoundingClientRect();
          if (!r.height || r.bottom < -240 || r.top > vh + 240) return;
          const amt = parseFloat(el.getAttribute("data-drift") || "") || 40;
          const prog = (r.top + r.height / 2 - vh / 2) / vh;
          const y = -Math.max(-1.4, Math.min(1.4, prog)) * amt;
          el.style.willChange = "transform";
          el.style.transform = `translate3d(0,${y.toFixed(1)}px,0)`;
        });

        document.querySelectorAll<HTMLElement>("[data-parallax]").forEach((p) => {
          const r = p.getBoundingClientRect();
          if (!r.height || r.bottom < -300 || r.top > vh + 300) return;
          const amt = parseFloat(p.getAttribute("data-parallax") || "") || 0.14;
          const prog = (r.top + r.height / 2 - vh / 2) / vh;
          const y = -Math.max(-1.6, Math.min(1.6, prog)) * r.height * amt;
          p.style.willChange = "transform";
          p.style.transform = `translate3d(0,${y.toFixed(1)}px,0) scale(${(
            1 + amt * 1.1
          ).toFixed(3)})`;
        });
      }
    };

    const onScroll = () => {
      if (!rafId) rafId = requestAnimationFrame(tick);
    };
    const onWake = () => {
      rafId = 0;
      tick();
    };
    addEventListener("scroll", onScroll, { passive: true, capture: true });
    addEventListener("resize", onScroll, { passive: true });
    addEventListener("wheel", onScroll, { passive: true });
    addEventListener("touchmove", onScroll, { passive: true });
    addEventListener("visibilitychange", onWake);
    addEventListener("pageshow", onWake);
    // v6 also polls: the video's `duration` lands whenever its metadata does,
    // and neither the playhead nor a caption should wait for the next scroll.
    const poll = setInterval(onWake, 250);
    tick();

    // ---------- Markets rail: drag to scroll ----------
    const railCleanups: (() => void)[] = [];
    document.querySelectorAll<HTMLElement>("[data-rail]").forEach((rail) => {
      rail.style.cursor = "grab";
      let down = false;
      let sx = 0;
      let sl = 0;
      const onDown = (e: PointerEvent) => {
        down = true;
        sx = e.clientX;
        sl = rail.scrollLeft;
        rail.style.cursor = "grabbing";
      };
      const onMove = (e: PointerEvent) => {
        if (!down) return;
        e.preventDefault();
        rail.scrollLeft = sl - (e.clientX - sx);
      };
      const up = () => {
        down = false;
        rail.style.cursor = "grab";
      };
      rail.addEventListener("pointerdown", onDown);
      rail.addEventListener("pointermove", onMove);
      rail.addEventListener("pointerup", up);
      rail.addEventListener("pointerleave", up);
      // Not in the original, and its absence bites hybrid devices: a touch
      // scroll cancels mid-gesture, `down` stays true, and the next mouse
      // hover drags the rail with no button held.
      rail.addEventListener("pointercancel", up);
      railCleanups.push(() => {
        rail.removeEventListener("pointerdown", onDown);
        rail.removeEventListener("pointermove", onMove);
        rail.removeEventListener("pointerup", up);
        rail.removeEventListener("pointerleave", up);
        rail.removeEventListener("pointercancel", up);
      });
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(scrubRaf);
      if (rafId) cancelAnimationFrame(rafId);
      clearInterval(poll);
      timers.forEach(clearTimeout);
      removeEventListener("scroll", onScroll, { capture: true } as EventListenerOptions);
      removeEventListener("resize", onScroll);
      removeEventListener("wheel", onScroll);
      removeEventListener("touchmove", onScroll);
      removeEventListener("visibilitychange", onWake);
      removeEventListener("pageshow", onWake);
      document.removeEventListener("pointerdown", kick);
      document.removeEventListener("touchstart", kick);
      railCleanups.forEach((fn) => fn());
    };
  }, []);

  return null;
}
