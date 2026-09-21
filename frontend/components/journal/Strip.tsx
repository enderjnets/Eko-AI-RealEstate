"use client";

import { useEffect, useRef } from "react";

import type { Entry, Panel } from "@/lib/journal/twelveHouses";

/**
 * "At a glance": doce paneles, uno por casa, que se abren al pasar por encima y
 * hojean sus cuatro fotografias.
 *
 * Este fichero es la traduccion directa de la memoria tecnica del handoff, y
 * las tres cosas que parecen manias son las tres que ya fallaron una vez:
 *
 * **1. Los anchos se calculan en pixeles; `flex-grow` NO sirve.** Con doce
 * paneles y un `min-width` de suelo, por debajo de unos 1000px los colapsados
 * se comen todo el espacio y el activo no crece nunca. Se calcula desde el
 * ancho de la propia tira y se escribe `width` a mano, con `flex:none` y
 * `min-width:0` en todos.
 *
 * **2. El ancho se interpola en JS, no con una transicion CSS.** Una
 * `transition` sobre `width` solo avanza cuando algo fuerza un recalculo de
 * estilo. El camino del clic lo forzaba de rebote —`scrollTo`— y por eso el
 * clic animaba; el del raton no, y se quedaba congelado 1-2,5 s antes de dar
 * un salto. Se interpola en el mismo `requestAnimationFrame`.
 *
 * **3. La transicion de entrada va SEPARADA de la de interaccion.** Mientras
 * compartieron una sola declaracion, alargar la entrada alargaba tambien el
 * abrir y cerrar. Cada panel cambia a la lista corta en cuanto termina de
 * entrar.
 *
 * Todo el movimiento se apaga bajo `prefers-reduced-motion: reduce`: queda una
 * tira estatica con el primer panel abierto, que se sigue pudiendo leer y
 * navegar con el teclado.
 */

const HOVER_DELAY_MS = 90;
const FLIP_EVERY_MS = 2400;
const FADE_MS = 900;
const ENTRANCE_STEP_MS = 150;

const ENTRANCE =
  "opacity 1500ms cubic-bezier(0.16,1,0.3,1), transform 1700ms cubic-bezier(0.16,1,0.3,1)";
const INTERACT =
  "background-size 900ms cubic-bezier(0.22,1,0.36,1), border-color 400ms ease";

export function Strip({ entries: ENTRIES, panels: STRIP }: {
  entries: readonly Entry[];
  panels: readonly Panel[];
}) {
  const stripRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function photosOf(slug: string): string[] {
      const entry = ENTRIES.find((e) => e.slug === slug);
      return entry ? entry.photos.map((p) => `/blog/img/${p}`) : [];
    }

    const strip = stripRef.current;
    if (!strip) return;

    const panels = Array.from(
      strip.querySelectorAll<HTMLDivElement>("[data-sel]"),
    );
    if (panels.length === 0) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Estado por panel. `current` es el ancho pintado ahora mismo y `target` el
    // que deberia tener; la diferencia es lo que interpola el bucle.
    const state = panels.map((el) => ({ el, current: 0, target: 0 }));
    let active = -1;
    let hoverAfter = 0;
    let raf = 0;
    let hoverTimer: number | undefined;
    let flipTimer: number | undefined;
    let fadeTimer: number | undefined;
    let flipRaf = 0;
    const entranceTimers = new Set<number>();
    const later = (fn: () => void, delay: number) => {
      const id = window.setTimeout(() => { entranceTimers.delete(id); fn(); }, delay);
      entranceTimers.add(id);
    };

    const tick = () => {
      raf = 0;
      let busy = false;
      for (const p of state) {
        const d = p.target - p.current;
        if (Math.abs(d) < 0.5) {
          p.current = p.target;
        } else {
          p.current += d * 0.18;
          busy = true;
        }
        p.el.style.width = `${p.current.toFixed(1)}px`;
      }
      if (busy) raf = requestAnimationFrame(tick);
    };

    const layout = (i: number, snap: boolean) => {
      const cw = strip.clientWidth;
      // Del handoff, verificado: activo 261px a 375, 324 a 768, 417 a 1024.
      // Siempre mas estrecho que la ventana, para que el siguiente asome.
      const activeW = Math.max(
        260,
        Math.min(420, Math.round(cw * 0.42), cw - 52),
      );
      const colW = Math.max(26, Math.floor((cw - activeW) / (panels.length - 1)));
      state.forEach((p, j) => {
        p.target = j === i ? activeW : colW;
        if (snap) {
          p.current = p.target;
          p.el.style.width = `${p.target}px`;
        }
      });
      if (!snap && !raf) raf = requestAnimationFrame(tick);
    };

    const stopFlip = () => {
      if (flipRaf) cancelAnimationFrame(flipRaf);
      flipRaf = 0;
      window.clearInterval(flipTimer);
      window.clearTimeout(fadeTimer);
      for (const p of panels) {
        const overlay = p.querySelector<HTMLElement>("[data-photo-overlay]");
        if (overlay) {
          overlay.style.transition = "none";
          overlay.style.opacity = "0";
        }
      }
    };

    /** Hojea las cuatro fotos del panel abierto, una cada 2400ms. */
    const startFlip = (panel: HTMLElement) => {
      stopFlip();
      if (reduce || document.hidden) return;
      const slug = panel.dataset.slug || "";
      const photos = photosOf(slug);
      if (photos.length < 2) return;
      // Precargadas al abrir: sin esto el primer cruce muestra el hueco.
      for (const src of photos) {
        const im = new Image();
        im.src = src;
      }
      const overlay = panel.querySelector<HTMLElement>("[data-photo-overlay]");
      if (!overlay) return;
      let at = 0;
      flipTimer = window.setInterval(() => {
        at = (at + 1) % photos.length;
        const next = photos[at];
        overlay.style.transition = "none";
        overlay.style.opacity = "0";
        overlay.style.backgroundImage = `url("${next}")`;
        // Un fotograma de margen para que el navegador acepte el cambio de
        // `transition` antes de disparar la opacidad.
        flipRaf = requestAnimationFrame(() => {
          flipRaf = 0;
          overlay.style.transition = `opacity ${FADE_MS}ms ease`;
          overlay.style.opacity = "1";
        });
        fadeTimer = window.setTimeout(() => {
          // Ya fundida: se pasa al fondo del propio panel y la capa se reinicia,
          // para que el siguiente cruce parta de cero.
          panel.style.backgroundImage = `url("${next}")`;
          overlay.style.transition = "none";
          overlay.style.opacity = "0";
        }, FADE_MS);
      }, FLIP_EVERY_MS);
    };

    const setActive = (i: number, scroll: boolean) => {
      if (scroll) {
        hoverAfter = performance.now() + 800;
        window.clearTimeout(hoverTimer);
      }
      const changed = active !== i;
      active = i;
      layout(i, reduce);
      panels.forEach((p, j) => {
        const open = j === i;
        p.style.backgroundSize = open ? "auto 100%" : "auto 118%";
        p.style.borderColor = open ? "rgba(244,241,234,0.85)" : "#2A2621";
        p.style.zIndex = open ? "2" : "1";
        p.setAttribute("aria-current", open ? "true" : "false");
        const label = p.querySelector<HTMLElement>("[data-lab]");
        if (label) {
          label.style.opacity = open ? "1" : "0";
          if (reduce) label.style.transition = "none";
          label.style.transform = reduce || open ? "translateX(0)" : "translateX(22px)";
          label.style.pointerEvents = open ? "auto" : "none";
          const link = label.querySelector("a");
          if (link) link.tabIndex = open ? 0 : -1;
        }
        if (!open) p.style.backgroundImage = `url("${photosOf(p.dataset.slug || "")[0]}")`;
      });
      if (changed) startFlip(panels[i]);
      if (scroll) {
        strip.scrollTo({ left: Math.max(0, panels[i].offsetLeft - 30), behavior: reduce ? "auto" : "smooth" });
      }
    };

    // Primera colocacion: se ajusta de golpe, sin animar nada al cargar.
    layout(0, true);
    setActive(0, false);

    const onResize = () => layout(active, true);
    window.addEventListener("resize", onResize);

    const onVisibility = () => {
      if (document.hidden) stopFlip();
      else startFlip(panels[active]);
    };
    document.addEventListener("visibilitychange", onVisibility);
    const cleanups: Array<() => void> = [() => document.removeEventListener("visibilitychange", onVisibility)];
    panels.forEach((p, i) => {
      const onClick = (e: MouseEvent) => {
        if (!(e.target as Element).closest("a")) setActive(i, true);
      };
      const onKey = (e: KeyboardEvent) => {
        if ((e.target as Element).closest("a")) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setActive(i, true);
        }
      };
      const onFocus = () => {
        if (p.matches(":focus-visible")) setActive(i, true);
      };
      const onEnter = () => {
        if (performance.now() < hoverAfter) return;
        window.clearTimeout(hoverTimer);
        // El retardo evita que cruzar la tira de lado a lado abra los doce.
        hoverTimer = window.setTimeout(() => setActive(i, false), HOVER_DELAY_MS);
      };
      const onLeave = () => window.clearTimeout(hoverTimer);
      p.addEventListener("click", onClick);
      p.addEventListener("keydown", onKey);
      p.addEventListener("focus", onFocus);
      p.addEventListener("mouseenter", onEnter);
      p.addEventListener("mouseleave", onLeave);
      cleanups.push(() => {
        p.removeEventListener("click", onClick);
        p.removeEventListener("keydown", onKey);
        p.removeEventListener("focus", onFocus);
        p.removeEventListener("mouseenter", onEnter);
        p.removeEventListener("mouseleave", onLeave);
      });
    });

    // Entrada escalonada. Se arma aqui y no en el marcado para que una pestana
    // que nunca llega a verse no deje la tira invisible: si el observador no
    // dispara, el temporizador de respaldo la ensena igual.
    let entered = false;
    const enter = () => {
      if (entered) return;
      entered = true;
      panels.forEach((p, i) => {
        later(() => {
          p.style.opacity = "1";
          p.style.transform = "none";
          // En cuanto termina de entrar, se cambia a la lista corta: mientras
          // compartieron una sola declaracion, la entrada larga arrastraba al
          // abrir y cerrar.
          later(() => {
            p.style.transition = INTERACT;
          }, 1800);
        }, i * ENTRANCE_STEP_MS);
      });
    };

    if (reduce) {
      for (const p of panels) {
        p.style.opacity = "1";
        p.style.transform = "none";
        p.style.transition = "none";
      }
      entered = true;
    } else {
      for (const p of panels) {
        p.style.opacity = "0";
        p.style.transform = "translateX(-64px)";
        p.style.transition = ENTRANCE;
      }
      const io = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (e.isIntersecting) {
              io.disconnect();
              enter();
            }
          }
        },
        { threshold: 0.05 },
      );
      io.observe(strip);
      cleanups.push(() => io.disconnect());

      const onVisible = () => {
        if (document.visibilityState === "visible") enter();
      };
      document.addEventListener("visibilitychange", onVisible);
      const fallback = window.setTimeout(enter, 2500);
      cleanups.push(() => {
        document.removeEventListener("visibilitychange", onVisible);
        window.clearTimeout(fallback);
      });
    }

    return () => {
      window.removeEventListener("resize", onResize);
      window.clearTimeout(hoverTimer);
      stopFlip();
      for (const id of entranceTimers) window.clearTimeout(id);
      if (raf) cancelAnimationFrame(raf);
      for (const c of cleanups) c();
    };
  }, [ENTRIES]);

  return (
    <>
      <div
        ref={stripRef}
        data-strip="1"
        className="flex h-[clamp(300px,44vw,440px)] w-full overflow-x-auto bg-jr-noir"
      >
        {STRIP.map((panel, i) => {
          const entry = ENTRIES.find((e) => e.n === panel.n);
          const lead = entry ? `/blog/img/${entry.photos[0]}` : "";
          return (
            <div
              key={panel.n}
              data-sel={i}
              data-slug={entry?.slug}
              tabIndex={0}
              role="button"
              aria-label={`${panel.name}, ${panel.where}`}
              style={{
                flex: "none",
                minWidth: 0,
                backgroundImage: `url("${lead}")`,
                backgroundSize: "auto 118%",
                backgroundPosition: "center",
                backgroundColor: "#181613",
                borderColor: "#2A2621",
              }}
              className="relative h-full cursor-pointer overflow-hidden border border-r-0 border-solid outline-offset-[-2px]"
            >
              {/* La capa del fundido va DEBAJO del degradado: si fuera encima,
                  cada cruce de foto blanquearia el texto durante 900ms. */}
              <span
                data-photo-overlay="1"
                aria-hidden="true"
                style={{
                  position: "absolute",
                  inset: 0,
                  zIndex: 0,
                  opacity: 0,
                  backgroundSize: "auto 100%",
                  backgroundPosition: "center",
                }}
              />
              <span
                aria-hidden="true"
                style={{
                  position: "absolute",
                  insetInline: 0,
                  bottom: 0,
                  height: "62%",
                  zIndex: 1,
                  background:
                    "linear-gradient(to top, rgba(10,9,8,0.90), rgba(10,9,8,0))",
                }}
              />
              <span
                className="absolute inset-x-0 bottom-0 z-[2] flex items-center gap-[14px] px-4 py-[18px]"
                style={{ fontFamily: "inherit" }}
              >
                <span className="block shrink-0 font-ln-serif text-[16px] italic text-jr-brass-light">
                  {panel.label}
                </span>
                <span
                  data-lab="1"
                  style={{ opacity: 0, transform: "translateX(22px)", pointerEvents: "none", transition: "opacity 700ms ease, transform 700ms cubic-bezier(0.22,1,0.36,1)" }}
                  className="block min-w-0 whitespace-nowrap"
                >
                  <span className="block font-ln-serif text-[23px] leading-[1.1] text-jr-offwhite">
                    {panel.name}
                  </span>
                  <span className="mt-[6px] block font-ln-sans text-[10px] uppercase tracking-[0.20em] text-jr-cream/[0.72]">
                    {panel.where}
                  </span>
                  <a
                    href={`#n${panel.n}`}
                    className="mt-3 inline-block font-ln-sans text-[10px] font-medium uppercase tracking-[0.20em] text-jr-brass-light hover:text-jr-offwhite"
                  >
                    Read the entry &rarr;
                  </a>
                </span>
              </span>
            </div>
          );
        })}
      </div>
      <p className="mx-auto max-w-[1120px] px-[clamp(22px,5vw,56px)] pt-4 font-ln-sans text-[11px] leading-[1.6] uppercase tracking-[0.14em] text-jr-cream/45">
        Hover a panel to leaf through its photographs &middot; tap on a phone
      </p>
    </>
  );
}
