"use client";

/**
 * The v4 scroll choreography, ported from the design's `deploy-v4/index.html`
 * (the `<script>` at the end of that file is the authoritative engine — this
 * is that engine, kept as literal as TypeScript and React mounting allow).
 *
 * It is attribute-driven and owns no markup: `Landing.tsx` carries the same
 * `data-*` attributes the design's artboards carry, and this component makes
 * them move —
 *
 *   data-rise-host          the hero section; scroll progress is measured on it
 *   data-rise="s0,s1,y"     the house plate: scale s0→s1, translate to y px
 *   data-fade-out           hero copy fades and lifts as the hero scrolls away
 *   data-hero-video         SCRUBS with scroll over the hero's first 30%,
 *                           then free-runs on loop
 *   data-reveal="up|clip"   sections blur/slide in when they near the viewport,
 *                           staggered 70ms between siblings; inside a rail the
 *                           slide comes from the right
 *   data-drift="px"         headings drift against the scroll
 *   data-parallax="amt"     portrait (0.14) and consult background (0.24)
 *   data-rail               the markets rail: drag to scroll
 *
 * What was deliberately NOT ported from deploy-v4: its artboard-scaling
 * "responsive" block (it transforms fixed 1440/390 layouts; our page is
 * genuinely responsive), its transform-aware anchor navigation (ours is
 * native + CSS smooth), and its CDN Lucide painter (we use lucide-react).
 *
 * prefers-reduced-motion: reveals are marked done, rise/fade/drift/parallax
 * never move, and the hero video is parked on its poster frame — the page is
 * the design's at-top composition, static.
 */

import { useEffect } from "react";

const EASE = "cubic-bezier(.22,.61,.36,1)";

/* The engine tracks per-element state in expando properties, exactly like the
   original. A WeakMap would be tidier; staying close to the source is worth
   more here — every behavioral diff from deploy-v4 is a bug by definition. */
type El = HTMLElement & {
  __done?: number;
  __rv?: number;
  __d?: number;
  __pending?: number;
};
type Vid = HTMLVideoElement & { __free?: boolean; __target?: number | null };

export function LandingEffects() {
  useEffect(() => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let disposed = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    // ---------- Video: prime for scrubbing ----------
    const kick = () => {
      document.querySelectorAll<Vid>("video[data-hero-video]").forEach((v) => {
        v.muted = true;
        v.defaultMuted = true;
        v.playsInline = true;
        v.preload = "auto";
        if (v.__free) return;
        const p = v.play();
        if (p && p.then) p.then(() => { if (!v.__free) v.pause(); }).catch(() => {});
        else v.pause();
      });
    };
    kick();
    timers.push(setTimeout(kick, 400), setTimeout(kick, 1600));
    document.addEventListener("pointerdown", kick, { once: true });
    document.addEventListener("touchstart", kick, { once: true, passive: true });

    // Smooth-scrub loop: currentTime eases toward the scroll target.
    let scrubRaf = 0;
    const easeLoop = () => {
      if (disposed) return;
      scrubRaf = requestAnimationFrame(easeLoop);
      document.querySelectorAll<Vid>("video[data-hero-video]").forEach((v) => {
        if (v.__free || !v.duration || v.seeking || v.__target == null) return;
        const cur = v.currentTime || 0;
        const d = v.__target - cur;
        if (Math.abs(d) < 0.02) return;
        v.currentTime = cur + d * 0.24;
      });
    };
    easeLoop();

    // ---------- Scroll choreography ----------
    const show = (el: El, animate: boolean) => {
      el.__done = 1;
      if (animate) {
        const slow = el.getAttribute("data-reveal") === "clip";
        el.style.transition = slow
          ? `opacity 1100ms ${EASE}, transform 2600ms ${EASE}, clip-path 2600ms ${EASE}, filter 1800ms ${EASE}`
          : `opacity 600ms ${EASE}, transform 1000ms ${EASE}, clip-path 1000ms ${EASE}, filter 800ms ${EASE}`;
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
        (sibs.length > 1 ? i * 70 : 0);
      el.style.willChange = "opacity, transform, filter";
      el.style.opacity = "0";
      if (el.getAttribute("data-reveal") === "clip") {
        el.style.clipPath = "inset(34% 0 0 0)";
        el.style.transform = "scale(1.14)";
      } else if (el.closest("[data-rail]")) {
        el.style.transform = "translate3d(130px,0,0) scale(0.94)";
        el.style.filter = "blur(12px)";
      } else {
        el.style.transform = "translate3d(0,78px,0) scale(0.972)";
        el.style.filter = "blur(9px)";
      }
    };

    if (reduce) {
      document.querySelectorAll<El>("[data-reveal]").forEach((el) => {
        el.__done = 1;
      });
    }

    const progressOf = (el: HTMLElement) => {
      const host =
        (el.closest("[data-rise-host]") as HTMLElement | null) || el.parentElement!;
      const r = host.getBoundingClientRect();
      return Math.max(0, Math.min(1, -r.top / (r.height || 1)));
    };

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
          const m = el.getAttribute("data-reveal") === "clip" ? 1.35 : 1.02;
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
          if (near) {
            el.__pending = 1;
            timers.push(setTimeout(() => show(el, true), el.__d || 0));
          }
        });

      document.querySelectorAll<HTMLElement>("[data-rise]").forEach((el) => {
        if (reduce) return;
        const p = progressOf(el);
        const c = (el.getAttribute("data-rise") || "").split(",").map(Number);
        const s0 = c[0] || 0.86;
        const s1 = c[1] || 1.2;
        const y1 = c[2] || -150;
        el.style.willChange = "transform";
        el.style.transform = `translate3d(0,${(p * y1).toFixed(1)}px,0) scale(${(
          s0 + (s1 - s0) * p
        ).toFixed(4)})`;
      });

      // Hero video scrubs with scroll over the first 30% of the hero span,
      // then free-runs in loop.
      document.querySelectorAll<Vid>("video[data-hero-video]").forEach((v) => {
        // reduced-motion: the markup's autoPlay may have started it before
        // this ran — park it on its poster frame and leave it parked.
        if (reduce) {
          if (!v.paused) v.pause();
          return;
        }
        if (!v.duration || isNaN(v.duration)) return;
        const host =
          (v.closest("[data-rise-host]") as HTMLElement | null) || v.parentElement!;
        const hr = host.getBoundingClientRect();
        if (hr.bottom < -60 || hr.top > vh + 60) {
          if (!v.paused) v.pause();
          v.__target = null;
          return;
        }
        const SPAN = 0.3;
        const p = Math.min(1, Math.max(0, -hr.top / (hr.height || 1)) / SPAN);
        if (p < 1 && !reduce) {
          if (!v.paused) v.pause();
          v.__free = false;
          v.__target = Math.min(v.duration - 0.05, p * v.duration);
        } else if (!v.__free || v.paused) {
          v.__free = true;
          v.loop = true;
          const pl = v.play();
          if (pl && pl.catch) pl.catch(() => {});
        }
      });

      if (!reduce) {
        document.querySelectorAll<HTMLElement>("[data-fade-out]").forEach((el) => {
          const p = progressOf(el);
          el.style.willChange = "opacity, transform";
          el.style.opacity = (1 - Math.min(1, p * 2.6)).toFixed(3);
          el.style.transform = `translate3d(0,${(-p * 160).toFixed(1)}px,0)`;
        });

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
