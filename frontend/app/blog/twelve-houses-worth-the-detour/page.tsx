import { requireJournalAccess } from "@/lib/journal/requireAccess";
import type { Metadata, Viewport } from "next";

import { ArticleMotion } from "@/components/journal/ArticleMotion";
import { JournalFooter, JournalHeader } from "@/components/journal/JournalChrome";
import { Strip } from "@/components/journal/Strip";
import { CallLine } from "@/components/landing/CallLine";
import { ConsultForm } from "@/components/landing/ConsultForm";
import { BRAND_URL } from "@/lib/hosts";
import { INDEXED } from "@/lib/journal/publication";
import { LANDING, homeScreenName } from "@/lib/landing";
import {
  ENTRIES,
  PAGE,
  PASSED,
  SLUG,
  type Segment,
} from "@/lib/journal/twelveHouses";

/**
 * "Twelve houses worth the detour" — la primera pieza de The Journal.
 *
 * Un componente de servidor con sus propios `metadata`, como `/fall`: Next
 * fusiona los metadatos y lo que no se declare aqui cae al layout raiz, cuyo
 * titulo nombra la plataforma y cuyo `robots` por defecto es `index: false`.
 * Las dos cosas estan mal en una pagina cuyo trabajo entero es que la
 * encuentren y la lean desconocidos.
 *
 * El movimiento vive en `<Strip>` y `<ArticleMotion>`, que son los unicos
 * trozos de cliente. La pagina se prerenderiza entera y se lee sin JavaScript.
 *
 * **Ninguna de estas casas es nuestra.** Cada ficha acredita a la correduria
 * que la tiene y enlaza a su registro —Regla 6.10.F.1.b de Colorado— y la
 * seccion cierra con el aviso de derechos. El permiso escrito de la letra `a`
 * se lleva por ficha en `permission`, y mientras alguna siga en «pending» esto
 * no sale a publico. Lo vigila `lib/__tests__/journal.test.ts`.
 *
 * Contenido en ingles solo, igual que `/fall` y por el mismo motivo: es una
 * pieza local para un publico local. El formulario de abajo mantiene su propio
 * idioma porque es el componente compartido, no una copia.
 */

const TITLE = "Twelve houses worth the detour";
const DESCRIPTION =
  "We read every active Colorado listing above $11.7 million, one at a time, " +
  "and looked at the photographs rather than the asking price. These are the " +
  "twelve we would drive to see.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "article", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
  // Ver `lib/journal/publication.ts`: la portada ya enlaza la seccion
  // (`LINKED`), pero hasta que las ocho corredurias den el permiso por
  // escrito esto no entra en ningun indice. Enlazar se deshace; que Google
  // cachee cuarenta y ocho fotos ajenas, no.
  robots: { index: INDEXED, follow: INDEXED },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: `/blog/${SLUG}` } }
    : {}),
};

export const viewport: Viewport = { themeColor: "#0F0E0C" };

/** Los datos no llevan HTML crudo: la italica viene marcada por segmento. */
function Rich({ parts }: { parts: readonly Segment[] }) {
  return (
    <>
      {parts.map((p, i) => (p.em ? <em key={i}>{p.t}</em> : <span key={i}>{p.t}</span>))}
    </>
  );
}

const SHELL = "mx-auto max-w-[1120px] px-[clamp(22px,5vw,56px)]";

export default function TwelveHousesPage() {
  requireJournalAccess();
  return (
    <main className="min-h-screen bg-jr-cream font-ln-sans text-jr-body">
      {/* La barra de lectura. `transform-origin` a la izquierda o crece desde
          el centro hacia los dos lados. */}
      <div
        data-progress="1"
        aria-hidden="true"
        className="fixed inset-x-0 top-0 z-50 h-[2px] bg-jr-brass"
        style={{ transformOrigin: "0 0", transform: "scaleX(0)" }}
      />

      <JournalHeader current="article" />

      <section className="bg-jr-noir pb-0 pt-[clamp(56px,9vw,104px)]">
        <div className={SHELL}>
          <p className="flex flex-wrap items-center gap-3 font-ln-sans text-[10px] font-medium uppercase tracking-[0.30em] text-jr-cream/50">
            <a href="/blog" className="hover:text-jr-cream">
              Journal
            </a>
            <span aria-hidden="true" className="inline-block h-px w-6 bg-jr-cream/25" />
            <span>{PAGE.breadcrumb}</span>
          </p>

          <h1 className="mt-[clamp(26px,4vw,40px)] max-w-[15ch] font-ln-serif text-[clamp(44px,8.4vw,104px)] font-light leading-[0.94] tracking-[-0.025em] text-jr-offwhite">
            {PAGE.h1.lead}{" "}
            <span className="italic text-jr-brass-light">{PAGE.h1.accent}</span>
          </h1>

          <p className="mt-[clamp(22px,3vw,30px)] max-w-[620px] text-[clamp(16px,1.6vw,18px)] leading-[1.8] text-jr-cream/[0.82]">
            {PAGE.dek}
          </p>

          {/* La via deliberada hacia el formulario, dentro de la propia pagina.
              `data-track` es lo que hace que el rastreador cuente UNA eleccion
              de CTA; los enlaces normales del articulo siguen sin contarse. */}
          <p className="mt-7 text-[15px]">
            <a
              href="#consult"
              data-track="journal-hero"
              className="border-b border-jr-brass-light/50 pb-0.5 font-medium text-jr-brass-light hover:border-jr-offwhite hover:text-jr-offwhite"
            >
              Looking at one of these? Tell us which
            </a>
          </p>

          <p className="mt-[clamp(28px,4vw,40px)] flex flex-wrap items-center gap-x-[18px] gap-y-[10px] pb-[clamp(34px,5vw,52px)] text-[11px] uppercase tracking-[0.14em] text-jr-cream/[0.62]">
            {[PAGE.byline, PAGE.date, PAGE.readTime, PAGE.markets].map((bit, i) => (
              <span key={bit} className="flex items-center gap-3">
                {i > 0 && (
                  <span aria-hidden="true" className="inline-block h-1 w-1 rounded-full bg-jr-cream/30" />
                )}
                {bit}
              </span>
            ))}
          </p>
        </div>
      </section>

      <section className="bg-jr-noir pb-[clamp(40px,6vw,72px)]">
        <Strip />
      </section>

      <section className="bg-jr-cream pt-[clamp(56px,8vw,100px)] pb-[clamp(48px,7vw,82px)]">
        <div className={SHELL}>
          <dl className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-6 border-y border-jr-rule py-[26px]">
            {PAGE.stats.map((stat, i) => (
              <div key={stat.label}>
                <dt className="font-ln-sans text-[9px] uppercase tracking-[0.22em] text-jr-faint">
                  {stat.label}
                </dt>
                <dd
                  data-count={stat.value}
                  className={
                    "mt-[9px] font-ln-serif text-[40px] font-light leading-none " +
                    (i === PAGE.stats.length - 1 ? "text-jr-brass" : "text-jr-ink")
                  }
                >
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="bg-jr-cream pb-[clamp(56px,8vw,100px)]">
        <div className={`${SHELL} grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] items-start gap-[clamp(30px,5vw,70px)]`}>
          <div data-reveal="1">
            <h2 className="font-ln-serif text-[clamp(34px,4.4vw,56px)] font-light leading-[1.04] tracking-[-0.015em] text-jr-body">
              {PAGE.method.heading.lead}{" "}
              <span className="italic text-jr-brass">{PAGE.method.heading.accent}</span>
            </h2>
            <figure data-skyline="1" className="m-0 mt-[clamp(28px,4vw,44px)]">
              <span data-lead="1" className="block overflow-hidden bg-jr-photo" style={{ aspectRatio: "16 / 10" }}>
                {/* eslint-disable-next-line @next/next/no-img-element -- the public pages use plain <img> throughout: `sharp` is not installed, so next/image would optimise nothing and only add a dependency. */}
                <img
                  src="/blog/denver-skyline.jpg"
                  alt="Denver at dusk, seen from the west with the downtown towers against the plains"
                  loading="lazy"
                  className="block h-full w-full object-cover"
                />
              </span>
              <figcaption className="mt-3 text-[11px] leading-[1.6] tracking-[0.04em] text-jr-faint">
                {PAGE.method.skylineCaption}
              </figcaption>
            </figure>
          </div>

          <div data-reveal="1" className="max-w-[620px]">
            {PAGE.method.paragraphs.map((p) => (
              <p key={p.slice(0, 40)} className="mb-5 text-[16px] leading-[1.85] text-jr-body-muted last:mb-0">
                {p}
              </p>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-jr-warm pt-[clamp(52px,7vw,90px)] pb-[clamp(20px,4vw,40px)]">
        <div className={SHELL}>
          <h2
            data-reveal="1"
            className="font-ln-serif text-[clamp(34px,4.4vw,56px)] font-light leading-[1.04] tracking-[-0.015em] text-jr-body"
          >
            {PAGE.twelveHeading.lead}
          </h2>
          <p data-reveal="1" className="mt-[14px] mb-[clamp(10px,2vw,20px)] max-w-[540px] text-[15px] leading-[1.75] text-jr-secondary">
            {PAGE.twelveDek}
          </p>

          {ENTRIES.map((entry) => (
            <article
              key={entry.n}
              id={`n${entry.n}`}
              className="scroll-mt-20 border-t border-jr-rule py-[clamp(40px,6vw,72px)] last:border-b"
            >
              <div className="mb-5 flex items-baseline gap-[18px]">
                <span className="font-ln-serif text-[16px] italic text-jr-brass">
                  {entry.indexLabel}
                </span>
                <span className="text-[10px] font-medium uppercase tracking-[0.30em] text-jr-faint">
                  {entry.eyebrow}
                </span>
              </div>

              <h3 className="mb-3.5 max-w-[24ch] font-ln-serif text-[clamp(28px,3.8vw,46px)] font-light leading-[1.06] tracking-[-0.015em] text-jr-ink">
                {entry.headline}
              </h3>

              <p className="mb-[clamp(26px,4vw,38px)] text-[11px] uppercase tracking-[0.18em] text-jr-faint">
                {entry.address}
              </p>

              <figure className="m-0 mb-[clamp(26px,4vw,36px)]">
                <span
                  data-lead="1"
                  className="block overflow-hidden bg-jr-photo"
                  style={{ aspectRatio: "3 / 2" }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- the public pages use plain <img> throughout: `sharp` is not installed, so next/image would optimise nothing and only add a dependency. */}
                  <img
                    src={`/blog/img/${entry.photos[0]}`}
                    alt={entry.alts[0]}
                    loading="lazy"
                    className="block h-full w-full object-cover"
                  />
                </span>

                {/* Cada miniatura en SU PROPIO envoltorio de recorte. Son fotos
                    3:2 en cajas 3:2: no sobra nada que desplazar, asi que
                    `object-position` no puede moverlas. La imagen se escala
                    dentro del envoltorio y se mueve con `transform`. */}
                <div className="mt-[clamp(6px,1vw,12px)] grid grid-cols-3 gap-[clamp(6px,1vw,12px)]">
                  {entry.photos.slice(1).map((photo, i) => (
                    <span
                      key={photo}
                      data-thumb={i}
                      className="block overflow-hidden bg-jr-photo"
                      style={{ aspectRatio: "3 / 2" }}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element -- the public pages use plain <img> throughout: `sharp` is not installed, so next/image would optimise nothing and only add a dependency. */}
                      <img
                        src={`/blog/img/${photo}`}
                        alt={entry.alts[i + 1]}
                        loading="lazy"
                        className="block h-full w-full object-cover"
                      />
                    </span>
                  ))}
                </div>

                <figcaption className="mt-3 text-[11px] leading-[1.6] tracking-[0.04em] text-jr-faint">
                  {entry.caption}
                </figcaption>
              </figure>

              <p className="mb-[clamp(24px,3.5vw,34px)] max-w-[700px] text-[17px] leading-[1.8] text-jr-body-muted">
                {entry.body}
              </p>

              <dl className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-x-[18px] gap-y-[22px] border-y border-jr-rule py-[22px]">
                {entry.facts.map((fact, i) => (
                  <div key={fact.label}>
                    <dt className="mb-[7px] text-[9px] uppercase tracking-[0.22em] text-jr-faint">
                      {fact.label}
                    </dt>
                    <dd data-drift={i} className="m-0 font-ln-serif text-[21px] text-jr-ink">{fact.value}</dd>
                  </div>
                ))}
              </dl>

              <p className="mb-6 max-w-[640px] text-[14px] leading-[1.75] text-jr-secondary">
                <span className="mb-2 block text-[9px] font-semibold uppercase tracking-[0.24em] text-jr-brass">
                  {entry.noteLabel}
                </span>
                <Rich parts={entry.note} />
              </p>

              <a
                href={entry.listingUrl}
                target="_blank"
                rel="noopener"
                className="inline-block border-b border-jr-brass/40 pb-1 text-[11px] font-medium uppercase tracking-[0.22em] text-jr-brass hover:border-jr-ink hover:text-jr-ink"
              >
                See the full listing &rarr;
              </a>
            </article>
          ))}
        </div>
      </section>

      <section className="bg-jr-cream py-[clamp(56px,8vw,100px)]">
        <div className={SHELL}>
          <h2
            data-reveal="1"
            className="font-ln-serif text-[clamp(34px,4.4vw,56px)] font-light leading-[1.04] tracking-[-0.015em] text-jr-body"
          >
            {PAGE.passedHeading.lead}{" "}
            <span className="italic text-jr-brass">{PAGE.passedHeading.accent}</span>
          </h2>
          <p data-reveal="1" className="mt-3.5 max-w-[560px] text-[15px] leading-[1.75] text-jr-secondary">
            {PAGE.passedDek}
          </p>

          <div className="mt-[clamp(32px,5vw,50px)] flex flex-col">
            {PASSED.map((row) => (
              <div
                key={row.street}
                data-reveal="1"
                className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-x-8 gap-y-3.5 border-t border-jr-rule py-[26px]"
              >
                <div>
                  <div data-drift="1" className="font-ln-serif text-[22px] text-jr-ink">
                    {row.price}
                  </div>
                  <div className="mt-1.5 text-[10px] uppercase tracking-[0.18em] text-jr-faint">
                    {row.city}
                  </div>
                </div>
                <div>
                  <div className="mb-[7px] text-[14px] font-semibold text-jr-ink">{row.street}</div>
                  <p className="m-0 max-w-[560px] text-[14px] leading-[1.7] text-jr-secondary">
                    <Rich parts={row.reason} />
                  </p>
                </div>
              </div>
            ))}
          </div>

          {/* Se queda, y no es formalismo: junto al credito de cada figcaption
              es lo que cumple la letra `b` de la Regla 6.10.F.1. */}
          <p className="mt-[clamp(32px,4vw,44px)] max-w-[700px] text-[12px] leading-[1.75] text-jr-faint">
            {PAGE.rights}
          </p>
        </div>
      </section>

      {/* `id` y `scroll-mt` en la seccion, como en /fall y /calculator: sin el
          id, la lista de secciones del rastreador no encuentra que observar y
          la unica parte de la pagina que puede producir un lead es justo la
          que nadie mide. */}
      <section id="consult" className="scroll-mt-10 bg-jr-noir py-[clamp(64px,9vw,112px)]">
        <div className={`${SHELL} grid grid-cols-[repeat(auto-fit,minmax(min(100%,280px),1fr))] items-start gap-[clamp(32px,5vw,70px)]`}>
          <div>
            <h2 className="font-ln-serif text-[clamp(38px,5.6vw,72px)] font-light leading-none tracking-[-0.02em] text-jr-offwhite">
              {PAGE.talkHeading.lead}<br />
              <span className="italic text-jr-brass-light">{PAGE.talkHeading.accent}</span>
            </h2>
            {/* El diseno usa LA MISMA frase aqui y en el indice. Yo habia
                escrito una distinta en cada pagina, sin anotarlo en ninguna
                parte: eso es copia del cliente reescrita en silencio. Ahora
                sale del modulo generado, asi que las dos dicen lo mismo y lo
                que dicen es lo que el diseno dice. */}
            <p className="mt-5 max-w-[440px] text-[16px] leading-[1.8] text-jr-cream/[0.82]">
              {PAGE.talkDek}
            </p>

            {LANDING.phone && (
              <div className="mt-10 border-t border-jr-cream/20 pt-8">
                <CallLine where="journal" tone="dark" />
              </div>
            )}
          </div>

          {/* El formulario de la portada, no una copia: mismo endpoint, mismo
              senuelo, mismo Turnstile y la misma frase de consentimiento
              renderizada y guardada. Solo cambia la atribucion, asi que un lead
              de esta pieza se distingue en la bandeja de uno de la portada. */}
          <div className="border border-jr-cream/[0.14] bg-jr-cream/[0.045] p-[clamp(26px,3.5vw,38px)]">
            <ConsultForm variant="journal" />
          </div>
        </div>
      </section>

      <JournalFooter />
      <ArticleMotion />
    </main>
  );
}
