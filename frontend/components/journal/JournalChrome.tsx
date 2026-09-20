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
        <a href={JOURNAL_HREF} className="block">
          <span className="block font-ln-serif text-[20px] font-light tracking-[0.06em] text-jr-offwhite">
            {LANDING.brand || "The Journal"}
          </span>
          {subline && (
            <span className="mt-[3px] block font-ln-sans text-[7px] uppercase tracking-[0.22em] text-jr-cream/50">
              {subline}
            </span>
          )}
        </a>

        <nav className="flex flex-wrap items-center gap-x-7 gap-y-3 font-ln-sans">
          <a
            href="/"
            className="text-[11px] uppercase tracking-[0.18em] text-jr-cream/70 hover:text-jr-cream"
          >
            Home
          </a>
          <a
            href={JOURNAL_HREF}
            className={
              current === "index"
                ? "text-[11px] uppercase tracking-[0.18em] text-jr-cream"
                : "text-[11px] uppercase tracking-[0.18em] text-jr-cream/70 hover:text-jr-cream"
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

export function JournalFooter() {
  const who = [LANDING.brand, LANDING.advisors].filter(Boolean).join(" · ");
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
    <footer className="border-t border-jr-cream/10 bg-jr-noir px-[clamp(18px,5vw,56px)] py-10">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-start justify-between gap-x-10 gap-y-6 font-ln-sans text-[11px] leading-[1.75] tracking-[0.04em] text-jr-cream/50">
        <div>
          {who && <p className="text-jr-cream/70">{who}</p>}
          {legal.length > 0 && <p className="mt-1">{legal.join(" · ")}</p>}
        </div>

        <nav className="flex flex-wrap gap-x-6 gap-y-2 uppercase tracking-[0.18em]">
          <a href="/" className="hover:text-jr-cream">
            Home
          </a>
          <a href={JOURNAL_HREF} className="hover:text-jr-cream">
            Journal
          </a>
          {LANDING.instagram && (
            <a
              href={LANDING.instagram}
              target="_blank"
              rel="noopener"
              className="hover:text-jr-cream"
            >
              Instagram
            </a>
          )}
          {LANDING.youtube && (
            <a
              href={LANDING.youtube}
              target="_blank"
              rel="noopener"
              className="hover:text-jr-cream"
            >
              YouTube
            </a>
          )}
        </nav>
      </div>
    </footer>
  );
}
