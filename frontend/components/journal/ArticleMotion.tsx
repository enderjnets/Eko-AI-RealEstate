"use client";

import { useEffect } from "react";

/**
 * Todo el movimiento del articulo, en UN solo bucle de scroll.
 *
 * No renderiza nada: se engancha a atributos `data-*` del marcado, igual que
 * `LandingEffects` hace en la portada. Asi la pagina sigue siendo un componente
 * de servidor y se prerenderiza entera; esto solo la anima despues.
 *
 * El movimiento va ligado a la POSICION del scroll, nunca al reloj, y la
 * magnitud sale del tamano del elemento:
 *
 *   const r = el.getBoundingClientRect();
 *   const t = clamp(-1, 1, (r.top + r.height / 2 - vh / 2) / vh);
 *
 * `t` vale -1 arriba de la ventana, 0 centrado y +1 abajo.
 *
 * **Las amplitudes se derivan del tamano, no se clavan en pixeles.** Lo que una
 * foto escalada puede tapar es `(escala - 1) / 2 x dimension`, y eso encoge con
 * la ventana: una amplitud fija en pixeles se pasa de largo en un movil y
 * descubre el color de fondo por detras de la foto. De ahi los factores de
 * seguridad 0,7 y 0,65, que no son adorno.
 *
 * **El aparecer no depende solo de `IntersectionObserver`.** Si la pestana esta
 * oculta al cargar, el observador no dispara nunca y el articulo se queda en
 * blanco para siempre. Se comprueba tambien en el bucle de scroll, en
 * `visibilitychange` y con un temporizador de respaldo.
 *
 * Con `prefers-reduced-motion: reduce` no se anima nada: los contadores
 * escriben su cifra final y todo lo que iba a aparecer ya esta visible.
 */

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Posicion del elemento respecto al centro de la ventana, de -1 a 1. */
function progress(el: Element, vh: number): number {
  const r = el.getBoundingClientRect();
  return clamp((r.top + r.height / 2 - vh / 2) / vh, -1, 1);
}

export function ArticleMotion() {
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const bar = document.querySelector<HTMLElement>("[data-progress]");
    const leads = Array.from(document.querySelectorAll<HTMLElement>("[data-lead]"));
    const thumbs = Array.from(document.querySelectorAll<HTMLElement>("[data-thumb]"));
    const drifts = Array.from(document.querySelectorAll<HTMLElement>("[data-drift], [data-count]"));
    const counters = Array.from(document.querySelectorAll<HTMLElement>("[data-count]"));

    // Lo que aparece: los hijos de cada ficha, escalonados por su posicion, mas
    // cualquier cosa marcada a mano.
    const revealables: Array<[HTMLElement, number]> = [];
    document.querySelectorAll<HTMLElement>("article[id]").forEach((a) => {
      Array.from(a.children).forEach((child, i) => {
        revealables.push([child as HTMLElement, Math.min(i, 5) * 70]);
      });
    });
    document
      .querySelectorAll<HTMLElement>("[data-reveal]")
      .forEach((el) => revealables.push([el, 0]));

    if (reduce) {
      for (const el of counters) el.textContent = el.dataset.count || "";
      for (const [el] of revealables) {
        el.style.opacity = "1";
        el.style.transform = "none";
      }
      return;
    }

    for (const [el] of revealables) {
      el.style.opacity = "0";
      el.style.transform = "translateY(20px)";
      el.style.transition =
        "opacity 850ms cubic-bezier(0.22,1,0.36,1), transform 850ms cubic-bezier(0.22,1,0.36,1)";
    }

    const skyline = document.querySelector<HTMLElement>("[data-skyline]");
    if (skyline) {
      skyline.style.opacity = "0";
      skyline.style.transform = "translateY(72px)";
      skyline.style.transition = "opacity 900ms cubic-bezier(0.16,1,0.3,1), transform 1100ms cubic-bezier(0.16,1,0.3,1)";
      revealables.push([skyline, 0]);
    }
    let pending = revealables.slice();
    const fired = new Set<HTMLElement>();

    const timers = new Set<number>();
    const countFrames = new Set<number>();
    const show = (el: HTMLElement, delay: number) => {
      if (fired.has(el)) return;
      fired.add(el);
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        el.style.opacity = "1";
        el.style.transform = "none";
      }, delay);
      timers.add(timer);
    };

    /** Cuenta desde cero con una salida cubica. */
    const countUp = (el: HTMLElement) => {
      const target = Number(el.dataset.count || "0");
      el.style.fontVariantNumeric = "tabular-nums";
      const duration = 1100 + target * 2;
      const started = performance.now();
      const step = (now: number) => {
        const p = clamp((now - started) / duration, 0, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = String(Math.round(target * eased));
        if (p < 1) queueCount();
      };
      const queueCount = () => {
        const id = requestAnimationFrame((now) => { countFrames.delete(id); step(now); });
        countFrames.add(id);
      };
      queueCount();
    };

    // El raton sobre la foto principal: se acerca hacia +0,04 fotograma a
    // fotograma, dentro del mismo bucle. Un `transition` aqui competiria con la
    // transformada que ya escribe el parallax.
    const hover = new WeakMap<HTMLElement, number>();
    const hoverCleanups: Array<() => void> = [];
    for (const lead of leads) {
      hover.set(lead, 0);
      const on = () => { hover.set(lead, 1); schedule(); };
      const off = () => { hover.set(lead, 0); schedule(); };
      lead.addEventListener("mouseenter", on);
      lead.addEventListener("mouseleave", off);
      hoverCleanups.push(() => {
        lead.removeEventListener("mouseenter", on);
        lead.removeEventListener("mouseleave", off);
      });
    }
    const eased = new WeakMap<HTMLElement, number>();

    let raf = 0;
    const frame = () => {
      raf = 0;
      if (document.hidden) return;
      let busy = false;
      const vh = window.innerHeight;

      if (bar) {
        const doc = document.documentElement;
        const total = doc.scrollHeight - vh;
        bar.style.transform = `scaleX(${total > 0 ? clamp(doc.scrollTop / total, 0, 1) : 0})`;
      }

      for (const lead of leads) {
        const img = lead.firstElementChild as HTMLElement | null;
        if (!img) continue;
        const t = progress(lead, vh);
        // (1,12 - 1) / 2 x alto x 0,7. El 0,7 es el margen que evita descubrir
        // el borde de la foto en una ventana estrecha.
        const amp = (0.12 / 2) * lead.offsetHeight * 0.7;
        const want = hover.get(lead) ? 0.04 : 0;
        const previous = eased.get(lead) ?? 0;
        const now = Math.abs(want - previous) < 0.00008 ? want : previous + (want - previous) * 0.12;
        if (now !== want) busy = true;
        eased.set(lead, now);
        img.style.transform = `translateY(${(-t * amp).toFixed(2)}px) scale(${(1.12 + now).toFixed(3)})`;
      }

      for (const wrap of thumbs) {
        const img = wrap.firstElementChild as HTMLElement | null;
        if (!img) continue;
        const t = progress(wrap, vh);
        const amp = (0.14 / 2) * wrap.offsetWidth * 0.65;
        // La del medio va al reves que las dos de fuera: sin eso las tres se
        // mueven en bloque y parece que se ha desplazado la rejilla entera.
        const dir = wrap.dataset.thumb === "1" ? -1 : 1;
        img.style.transform = `translateX(${(-t * amp * dir).toFixed(2)}px) scale(1.14)`;
      }

      drifts.forEach((el, i) => {
        const t = progress(el, vh);
        // Una onda suave a lo ancho de cada fila, no un bloque rigido.
        const amp = 5 + (Number(el.dataset.drift ?? i) % 4) * 2.5;
        el.style.transform = `translateY(${(-t * amp).toFixed(2)}px)`;
      });

      if (pending.length) {
        pending = pending.filter(([el, delay]) => {
          const r = el.getBoundingClientRect();
          if (r.top < vh * (el === skyline ? 0.88 : 0.92) && r.bottom > 0) {
            show(el, delay);
            return false;
          }
          return true;
        });
      }

      for (const el of counters) {
        if (el.dataset.counted) continue;
        const r = el.getBoundingClientRect();
        if (r.top < vh * 0.92 && r.bottom > 0) {
          el.dataset.counted = "1";
          countUp(el);
        }
      }
      if (busy) schedule();
    };

    const schedule = () => {
      if (!document.hidden && !raf) raf = requestAnimationFrame(frame);
    };

    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    document.addEventListener("load", schedule, true);
    document.addEventListener("visibilitychange", schedule);
    // Respaldo: si nada de lo anterior llega a dispararse —pestana en segundo
    // plano durante toda la carga— esto ensena el articulo de todos modos.
    const fallback = window.setTimeout(() => {
      for (const [el, delay] of pending) show(el, delay);
      for (const el of counters) {
        if (!el.dataset.counted) {
          el.dataset.counted = "1";
          el.textContent = el.dataset.count || "";
        }
      }
    }, 3000);

    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("load", schedule, true);
      for (const timer of timers) window.clearTimeout(timer);
      for (const id of countFrames) cancelAnimationFrame(id);
      document.removeEventListener("visibilitychange", schedule);
      window.clearTimeout(fallback);
      if (raf) cancelAnimationFrame(raf);
      for (const c of hoverCleanups) c();
    };
  }, []);

  return null;
}
