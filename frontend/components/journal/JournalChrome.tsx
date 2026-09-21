import { LANDING } from "@/lib/landing";
import { SLUG } from "@/lib/journal/twelveHouses";

/**
 * La cabecera y el pie de The Journal.
 *
 * Son componentes de servidor a proposito: no tienen ni un hook, la cabecera se
 * pega con CSS y nada mas, y asi las dos paginas del Journal siguen siendo
 * componentes de servidor y se prerenderizan estaticas. Un `"use client"` aqui
 * arrastraria las dos paginas enteras al cliente sin ganar nada.
 *
 * **Nada de esto escribe el nombre de la correduria a mano.** El prototipo lo
 * traia literal en la cabecera, junto al logo de la marca en el pie; aqui sale
 * de `LANDING.brokerage`, que es la unica pieza autorizada a saber cual es. Un
 * test lo vigila, y no es celo: la Regla 6.10.A.2 de Colorado exige el nombre
 * tal y como consta en los registros de la Comision, y 6.10.A.4 exige que TODO
 * anuncio vaya claramente a nombre de la correduria propia. Un literal
 * sobrevive a una instalacion que aun no ha configurado ninguna, y entonces la
 * pagina afirma algo que nadie ha comprobado.
 *
 * (Este comentario nombraba la marca como ejemplo. El test lo tumbo, que es
 * exactamente su trabajo: la guarda mira el fichero entero, no solo el JSX.)
 *
 * Tampoco hay logo. El oficial es para fondo claro y la variante en crema del
 * handoff es un recoloreado no oficial; y un logo no sustituye al nombre
 * registrado, que es lo que la regla pide.
 */

const JOURNAL_HREF = "/blog";
const ARTICLE_HREF = `/blog/${SLUG}`;

export function JournalHeader({ current }: { current: "index" | "article" }) {
  const subline = [LANDING.advisors, LANDING.brokerage]
    .filter(Boolean)
    .join(" · ");

  return (
    <header className="sticky top-0 z-40 border-b border-jr-cream/10 bg-jr-noir/[0.92] backdrop-blur-[10px]">
      <div className="mx-auto flex min-h-[66px] max-w-[1120px] flex-wrap items-center justify-between gap-x-8 gap-y-3 px-[clamp(18px,5vw,56px)] py-3">
        <a href={JOURNAL_HREF} className="flex min-h-[44px] flex-col justify-center">
          <span className="block font-ln-serif text-[20px] font-light tracking-[0.06em] text-jr-offwhite">
            {LANDING.brand || "The Journal"}
          </span>
          {subline && (
            <span className="mt-[3px] block font-ln-sans text-[7px] uppercase tracking-[0.22em] text-jr-cream/50">
              {subline}
            </span>
          )}
        </a>

        {/*
          `min-h-[44px]` en los dos enlaces de texto, y no es adorno: medido a
          390 px, el rectangulo tactil de «Home» y «Journal» era de **17 px de
          alto** —la altura de la letra—, mientras el wordmark y la pildora ya
          daban 44. En un movil eso es un enlace que se falla al tocarlo, y es
          justo el sitio donde se pulsa con el pulgar y a una mano. La altura
          visual no cambia: el texto sigue en su sitio, lo que crece es la zona
          que responde.
        */}
        <nav className="flex flex-wrap items-center gap-x-7 font-ln-sans">
          <a
            href="/"
            className="flex min-h-[44px] items-center text-[11px] uppercase tracking-[0.18em] text-jr-cream/70 hover:text-jr-cream"
          >
            Home
          </a>
          <a
            href={JOURNAL_HREF}
            aria-current={current === "index" ? "page" : undefined}
            className={
              current === "index"
                ? "flex min-h-[44px] items-center text-[11px] uppercase tracking-[0.18em] text-jr-cream"
                : "flex min-h-[44px] items-center text-[11px] uppercase tracking-[0.18em] text-jr-cream/70 hover:text-jr-cream"
            }
          >
            Journal
          </a>
          {/*
            El prototipo apuntaba esta pildora a `#talk`. Aqui es `#consult`, y
            no es cosmetica: `LandingTracker` solo cuenta un `cta_click` cuando
            el `href` es exactamente `#consult`. Con `#talk` el boton seguiria
            funcionando y la analitica diria que nadie lo toca nunca — que es el
            fallo mas caro de todos, porque no se parece a un fallo.
          */}
          <a
            href={current === "article" ? "#consult" : ARTICLE_HREF + "#consult"}
            data-track="journal-header"
            className="flex min-h-[44px] items-center justify-center rounded-full bg-jr-cream px-5 py-[11px] text-[10px] font-semibold uppercase tracking-[0.22em] text-jr-ink hover:bg-jr-offwhite"
          >
            Book a call
          </a>
        </nav>
      </div>
    </header>
  );
}

const FOOT_LINK = "inline-flex min-h-[44px] items-center hover:text-jr-cream";

export function JournalFooter() {
  // Mismo criterio que el pie de `/fall`: la correduria y «Licensed in
  // Colorado» solo aparecen donde el operador ha dicho cual es. Una instalacion
  // sin configurar no se inventa una licencia.
  const legal = [
    LANDING.brokerage,
    LANDING.address,
    LANDING.brokerage ? "Licensed in Colorado" : "",
    LANDING.brokerage ? "Equal Housing Opportunity" : "",
  ].filter(Boolean);

  return (
    <footer className="border-t border-jr-cream/10 bg-jr-noir py-[clamp(34px,5vw,50px)]">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-5 px-[clamp(22px,5vw,56px)] font-ln-sans text-[11px] leading-[1.75] tracking-[0.04em] text-jr-cream/50">
        <div className="flex flex-wrap items-center gap-[clamp(16px,3vw,26px)]">
          <div>
            {LANDING.brand && <p className="font-ln-serif text-[18px] font-light leading-none tracking-[0.05em] text-jr-offwhite">{LANDING.brand}</p>}
            {LANDING.advisors && <p className="mt-1.5 text-[7px] uppercase tracking-[0.26em]">{LANDING.advisors}</p>}
          </div>
          {legal.length > 0 && <p className="max-w-[370px] border-l border-jr-cream/20 pl-[clamp(16px,3vw,26px)]">{legal.join(" · ")}</p>}
        </div>

        {/* Mismo suelo tactil de 44 px que la cabecera, por el mismo motivo. */}
        <nav className="flex flex-wrap gap-x-[22px] text-[10px] uppercase tracking-[0.20em]">
          <a href="/" className={FOOT_LINK}>
            Home
          </a>
          <a href={JOURNAL_HREF} className={FOOT_LINK}>
            Journal
          </a>
          {LANDING.instagram && (
            <a
              href={LANDING.instagram}
              target="_blank"
              rel="noopener"
              className={FOOT_LINK}
            >
              Instagram
            </a>
          )}
          {LANDING.youtube && (
            <a
              href={LANDING.youtube}
              target="_blank"
              rel="noopener"
              className={FOOT_LINK}
            >
              YouTube
            </a>
          )}
        </nav>
      </div>
    </footer>
  );
}
