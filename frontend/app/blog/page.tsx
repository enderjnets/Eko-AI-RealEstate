import type { Metadata, Viewport } from "next";

import { JournalFooter, JournalHeader } from "@/components/journal/JournalChrome";
import { CallLine } from "@/components/landing/CallLine";
import { ConsultForm } from "@/components/landing/ConsultForm";
import { LandingTracker } from "@/components/landing/LandingTracker";
import { BRAND_URL } from "@/lib/hosts";
import { INDEXED } from "@/lib/journal/publication";
import { LANDING, homeScreenName } from "@/lib/landing";
import { INDEX, PAGE, SLUG } from "@/lib/journal/twelveHouses";

/**
 * The Journal: la entrada a la seccion.
 *
 * Tiene que verse igual de bien con una pieza que con veinte. Por eso la
 * cuenta va escrita en los datos —«One piece so far»— y la rejilla de la
 * destacada es `auto-fit`: cuando haya una segunda, la fila se parte sola.
 *
 * El titulo y la fecha de la tarjeta salen del MISMO modulo que el articulo,
 * no de una copia. El prototipo los tenia escritos dos veces, que es como una
 * tarjeta acaba anunciando un titular que el articulo ya no lleva.
 */

const TITLE = "The Journal";
const DESCRIPTION =
  "What we notice in the Aspen, Roaring Fork and Denver markets, written down " +
  "— the listings worth a second look and the reasons why.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "website", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
  // Ver `lib/journal/publication.ts`: la portada ya enlaza la seccion
  // (`LINKED`), pero hasta que las ocho corredurias den el permiso por
  // escrito esto no entra en ningun indice. Enlazar se deshace; que Google
  // cachee cuarenta y ocho fotos ajenas, no.
  robots: { index: INDEXED, follow: INDEXED },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/blog" } }
    : {}),
};

export const viewport: Viewport = { themeColor: "#0F0E0C" };

const SHELL = "mx-auto max-w-[1120px] px-[clamp(22px,5vw,56px)]";
const ARTICLE_HREF = `/blog/${SLUG}`;

/**
 * La frase del diseno que hace de enlace al formulario.
 *
 * Trocear una frase para meterle un enlace dentro es feo de leer, pero la
 * alternativa era la que ya hubo: inventarme una linea entera solo para tener
 * donde colgar el `data-track`. Si el diseno cambia y la frase desaparece, el
 * test de `journal.test.ts` se pone rojo en vez de dejar un enlace vacio.
 */
const CALL_PHRASE = "tell us on the call";
const CUT = INDEX.nextDek.indexOf(CALL_PHRASE);
const NEXT_HEAD = CUT < 0 ? INDEX.nextDek : INDEX.nextDek.slice(0, CUT);
const NEXT_TAIL = CUT < 0 ? "" : INDEX.nextDek.slice(CUT + CALL_PHRASE.length);

export default function JournalIndexPage() {
  return (
    <main className="min-h-screen bg-jr-cream font-ln-sans text-jr-body">
      <LandingTracker variant="journal-index" />

      <JournalHeader current="index" />

      <section className="bg-jr-noir pb-[clamp(52px,8vw,100px)] pt-[clamp(62px,10vw,120px)]">
        <div className={SHELL}>
          <p className="text-[10px] font-medium uppercase tracking-[0.30em] text-jr-cream/[0.62]">
            The Journal
          </p>
          <h1 className="mt-6 max-w-[18ch] font-ln-serif text-[clamp(42px,7.4vw,96px)] font-light leading-[0.94] tracking-[-0.025em] text-jr-offwhite">
            {INDEX.h1.lead}{" "}
            <span className="italic text-jr-brass-light">{INDEX.h1.accent}</span>
          </h1>
          <p className="mt-7 max-w-[600px] text-[clamp(16px,1.6vw,18px)] leading-[1.8] text-jr-cream/[0.82]">
            {INDEX.dek}
          </p>
        </div>
      </section>

      <section className="bg-jr-cream py-[clamp(52px,8vw,100px)]">
        <div className={SHELL}>
          <div className="flex flex-wrap items-baseline justify-between gap-4 border-t border-jr-rule pt-5">
            <span className="text-[10px] font-medium uppercase tracking-[0.30em] text-jr-faint">
              {INDEX.latestLabel}
            </span>
            <span className="font-ln-serif text-[18px] italic text-jr-brass">
              {INDEX.latestCount}
            </span>
          </div>

          {/* La tarjeta entera es un solo enlace: un titular que se puede tocar
              y una foto que no seria dos destinos para la misma intencion. */}
          <a
            href={ARTICLE_HREF}
            className="group mt-12 grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] items-start gap-[clamp(26px,4vw,56px)]"
          >
            <span className="block overflow-hidden bg-jr-photo" style={{ aspectRatio: "4 / 3" }}>
              {/* eslint-disable-next-line @next/next/no-img-element -- the public pages use plain <img> throughout: `sharp` is not installed, so next/image would optimise nothing and only add a dependency. */}
              <img
                src={`/blog/img/${INDEX.cardPhoto}`}
                alt={INDEX.cardAlt}
                loading="lazy"
                className="block h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.03]"
              />
            </span>

            <span className="block">
              <span className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[10px] uppercase tracking-[0.18em] text-jr-faint">
                <span className="text-jr-brass">{INDEX.cardCategory}</span>
                <span aria-hidden="true" className="inline-block h-1 w-1 rounded-full bg-jr-rule-strong" />
                <span>{INDEX.cardDate}</span>
                <span aria-hidden="true" className="inline-block h-1 w-1 rounded-full bg-jr-rule-strong" />
                <span>{INDEX.cardReadTime}</span>
              </span>

              <span className="mt-4 block font-ln-serif text-[clamp(30px,3.6vw,44px)] font-light leading-[1.06] tracking-[-0.015em] text-jr-ink">
                {PAGE.h1.lead}{" "}
                <span className="italic text-jr-brass">{PAGE.h1.accent}</span>
              </span>

              <span className="mt-5 block max-w-[560px] text-[16px] leading-[1.8] text-jr-body-muted">
                {INDEX.cardDek}
              </span>

              <span className="mt-6 inline-block border-b border-jr-brass/40 pb-1 text-[11px] font-medium uppercase tracking-[0.22em] text-jr-brass group-hover:border-jr-ink group-hover:text-jr-ink">
                {INDEX.cardCta}
              </span>
            </span>
          </a>
        </div>
      </section>

      <section className="bg-jr-warm py-[clamp(52px,8vw,100px)]">
        <div className={SHELL}>
          {/* En el diseno el titular y este parrafo son DOS columnas de la
              misma rejilla. El parrafo faltaba, y el fallo no saltaba a la
              vista porque un h2 solo tambien se ve bien.

              La ultima frase — «tell us on the call» — es el enlace etiquetado
              hacia el formulario. Antes eso era una linea que me invente y
              puse suelta bajo «Latest», donde no pintaba nada; aqui el enlace
              va dentro de una frase que escribio el diseno. */}
          <div className="mb-[clamp(36px,5vw,56px)] grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] items-start gap-[clamp(28px,5vw,64px)]">
            <h2 className="font-ln-serif text-[clamp(34px,4.4vw,56px)] font-light leading-[1.04] tracking-[-0.015em] text-jr-body">
              What lands here <span className="italic text-jr-brass">next.</span>
            </h2>
            <p className="max-w-[480px] text-[15px] leading-[1.8] text-jr-secondary">
              {NEXT_HEAD}
              <a
                href="#consult"
                data-track="journal-index-next"
                className="border-b border-jr-brass/40 pb-0.5 font-medium text-jr-ink hover:border-jr-ink"
              >
                {CALL_PHRASE}
              </a>
              {NEXT_TAIL}
            </p>
          </div>

          <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-[clamp(26px,4vw,56px)]">
            {INDEX.next.map((col, i) => (
              <div key={col.title} className="border-t border-jr-rule-strong pt-6">
                <span className="font-ln-serif text-[16px] italic text-jr-brass">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-3 font-ln-serif text-[25px] leading-[1.2] text-jr-ink">
                  {col.title}
                </h3>
                <p className="mt-3 text-[14px] leading-[1.75] text-jr-secondary">{col.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="consult" className="scroll-mt-10 bg-jr-noir py-[clamp(52px,8vw,100px)]">
        <div className={`${SHELL} grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] items-start gap-[clamp(28px,4vw,56px)]`}>
          <div>
            <h2 className="font-ln-serif text-[clamp(38px,5.6vw,72px)] font-light leading-none tracking-[-0.02em] text-jr-offwhite">
              {PAGE.talkHeading.lead}{" "}
              <span className="italic text-jr-brass-light">{PAGE.talkHeading.accent}</span>
            </h2>
            <p className="mt-6 max-w-[440px] text-[16px] leading-[1.8] text-jr-cream/[0.82]">
              {PAGE.talkDek}
            </p>

            {LANDING.phone && (
              <div className="mt-10 border-t border-jr-cream/20 pt-8">
                <CallLine where="journal-index" tone="dark" />
              </div>
            )}
          </div>

          <div className="border border-jr-cream/[0.14] bg-jr-cream/[0.045] p-[clamp(26px,3.5vw,38px)]">
            <ConsultForm variant="journal-index" />
          </div>
        </div>
      </section>

      <JournalFooter />
    </main>
  );
}
