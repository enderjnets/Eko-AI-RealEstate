import type { Metadata, Viewport } from "next";

import { ConsultForm } from "@/components/landing/ConsultForm";
import { LandingTracker } from "@/components/landing/LandingTracker";
import { LANDING, homeScreenName } from "@/lib/landing";
import { BRAND_URL } from "@/lib/hosts";
import { BANDS, mapsUrl, type Spot } from "@/lib/fallGuide";

/**
 * The fall-colour guide: the page a reel's caption promises.
 *
 * The mechanic this exists for is comment-to-DM — somebody comments a keyword
 * under a scenic reel, gets a link back, and lands here. So two rules shape it:
 *
 * **The guide is not gated.** The DM already promised it. Putting it behind the
 * form after promising it is a bait-and-switch, and this is a LOCAL audience —
 * the people who recognise Maroon Bells on sight are the people who will
 * recognise being handled. The guide is the whole page; the form is underneath,
 * asking the real-estate question honestly and separately.
 *
 * **It is written for the season, not for a weekend.** A list of seven places
 * is stale eight days after it is published. Sorted by elevation band it stays
 * useful from mid-September to November, which is the difference between one
 * reel's landing page and a page worth linking in a bio.
 *
 * Content is English only, and deliberately so: this is a Denver-local guide
 * for a Denver-local audience, and the product's rule is English by default.
 * The form underneath keeps its own i18n — it is the shared component, not a
 * copy, so a Spanish-speaking visitor still gets the consent wording in the
 * language they picked.
 *
 * A server component with its own `metadata`, like `app/page.tsx` and unlike
 * `/contact`: Next merges metadata, and anything not declared here falls
 * through to the root layout — whose title names the platform and whose
 * `robots` default is `index: false`. Both are wrong for a page whose entire
 * job is to be found and read by strangers.
 */

const TITLE = "Where to see fall color near Denver";
const DESCRIPTION =
  "A season-long guide to Colorado's aspens by elevation — where to go in " +
  "mid-September, in October, and when the color finally reaches Denver itself.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { type: "article", title: TITLE, description: DESCRIPTION },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
  robots: { index: true, follow: true },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: homeScreenName },
  ...(BRAND_URL
    ? { metadataBase: new URL(BRAND_URL), alternates: { canonical: "/fall" } }
    : {}),
};

export const viewport: Viewport = { themeColor: "#F4F1EA" };

/**
 * The season as an instrument, in the first screen.
 *
 * It replaces nothing — the four bands are still written out in full below —
 * but a visitor arriving from a reel, mid-scroll, on a phone, now sees the
 * whole idea at once instead of reading 250 words to reach it. Aspens turn
 * downhill, so the ladder runs downhill; that is the entire argument for a
 * vertical rail rather than a tidier two-column grid on a wide screen.
 *
 * Deliberately NOT headings. The bands below are the `<h2>`s, and a second set
 * carrying the same text would give a page whose entire job is to be indexed
 * two competing outlines. These are links into those bands, and nothing else.
 */
function ElevationLadder() {
  return (
    <nav
      aria-label="The season by elevation"
      className="border border-ln-hair bg-ln-paper px-5 py-6 sm:px-7 sm:py-7"
    >
      <p className="text-[10px] font-medium uppercase tracking-[0.3em] text-ln-muted">
        The season, top to bottom
      </p>
      <p className="mt-4 text-[10px] tracking-[0.08em] text-ln-faint">11,670 FT</p>

      <ol className="mt-2 border-l border-ln-line-strong pl-6">
        {BANDS.map((band) => (
          <li key={band.id} className="relative pb-5 last:pb-0">
            {/* The dot sits ON the rail: 8px wide, so its centre lands at the
                list's 24px padding minus half its width. The ring is the
                card's own background, punching a hole in the line. */}
            <span
              aria-hidden="true"
              className="absolute -left-[28px] top-[7px] h-2 w-2 bg-ln-gold ring-4 ring-ln-paper"
            />
            <a href={`#${band.id}`} className="group block">
              <span className="block font-ln-serif text-[21px] leading-tight text-ln-dark transition-colors group-hover:text-ln-gold">
                {band.elevation}
              </span>
              <span className="mt-1 block text-[10px] font-medium uppercase tracking-[0.16em] text-ln-gold">
                {band.when}
              </span>
              <span className="mt-1.5 block text-[13px] leading-[1.55] text-ln-muted">
                {band.note}
              </span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** A stroke pin on a 24px grid, drawn inline so it scales and takes the link's colour. */
function MapPin() {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="flex-none"
    >
      <path d="M20 10c0 4.4-8 12-8 12s-8-7.6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="2.6" />
    </svg>
  );
}

/**
 * One place, with its photograph when there is a licence-clear one of THAT
 * place.
 *
 * Seven of the twelve have none, and that is the honest state of it: a stock
 * photograph of generic aspens under the words "Kenosha Pass" is a false
 * statement about a real place, on a page advertising a licensed brokerage.
 * So the layout has to read as deliberate both ways — stacked on a phone,
 * photo beside the text from `md` up, and a spot without one simply runs the
 * full width instead of leaving a hole where a picture should be.
 */
function SpotEntry({ spot }: { spot: Spot }) {
  const photo = spot.photo;
  return (
    <li className={photo ? "md:grid md:grid-cols-[224px_1fr] md:gap-7" : undefined}>
      {photo && (
        <figure className="mb-4 md:mb-0">
          {/* eslint-disable-next-line @next/next/no-img-element -- the public
              pages use plain <img> throughout: `sharp` is not installed, so
              next/image would optimise nothing and only add a dependency. */}
          <img
            src={photo.src}
            alt={photo.alt}
            loading="lazy"
            decoding="async"
            className="aspect-[3/2] w-full bg-ln-tint object-cover"
            style={photo.position ? { objectPosition: photo.position } : undefined}
          />
          {/* Two deliberate lines rather than one that wraps wherever it
              lands. On a 224px photo column the single line broke after a
              dangling "·"; splitting it by meaning — who took it, then under
              what terms and from where — reads the same at every width. */}
          <figcaption className="mt-2 text-[10px] leading-[1.6] tracking-[0.03em] text-ln-faint">
            <span className="block">{photo.author}</span>
            <span className="block">
              <a
                href={photo.licenseUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-ln-line underline-offset-2 hover:text-ln-gold"
              >
                {photo.license}
              </a>{" "}
              ·{" "}
              <a
                href={photo.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-ln-line underline-offset-2 hover:text-ln-gold"
              >
                Wikimedia&nbsp;Commons
              </a>
            </span>
          </figcaption>
        </figure>
      )}
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="font-ln-serif text-[19px] text-ln-dark">{spot.name}</h3>
          <span className="text-[12px] uppercase tracking-[0.1em] text-ln-muted">
            {spot.drive}
          </span>
        </div>
        <p className="mt-2 text-[15px] leading-[1.7]">{spot.what}</p>

        {/* The link somebody taps once they have decided to go. Gold and
            uppercase like the page's other micro-labels, so it reads as an
            action without competing with the place's name; `py-1.5` gives the
            row a thumb-sized target on a phone without opening a gap in the
            text rhythm. `flex-wrap` because three of these entries carry more
            than one destination. */}
        <p className="mt-2.5 flex flex-wrap items-center gap-x-5 text-[11px] uppercase tracking-[0.14em] text-ln-gold">
          {spot.maps.map((place) => (
            <a
              key={place.query}
              href={mapsUrl(place.query)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 py-1.5 transition-colors hover:text-ln-bronze"
            >
              <MapPin />
              {place.label}
            </a>
          ))}
        </p>
      </div>
    </li>
  );
}

export default function FallGuidePage() {
  const brandLine = [LANDING.brand, LANDING.advisors].filter(Boolean).join(" · ");
  // The footer's two lines mirror the landing's exactly rather than inventing a
  // shorter version. This is real-estate advertising by licensed agents, and a
  // reader who checks the brokerage on one page and finds a different answer on
  // the other has found a discrepancy in a regulated disclosure.
  const footerWho = [LANDING.brand, LANDING.advisors, LANDING.brokerage]
    .filter(Boolean)
    .join(" · ");
  // "Licensed in Colorado" is a claim about a specific licence, so like the
  // landing's footer it appears only where the operator has said which
  // brokerage this is. Colorado requires advertising to identify the brokerage;
  // an unconfigured install must not invent one.
  const legal = [
    LANDING.address,
    LANDING.brokerage ? "Licensed in Colorado" : "",
    LANDING.brokerage ? "Equal Housing Opportunity" : "",
  ].filter(Boolean);

  return (
    <main className="min-h-screen bg-ln-canvas text-ln-body">
      {/* Without this the page is invisible in /analytics: `getTracker()`
          returns null, so `page_view` never fires and ConsultForm's
          `form_start` / `form_submit` / `form_error` are silent no-ops. A lead
          that converts still carries its UTM, so attribution survives — what is
          lost is the ratio the funnel exists to show: how many read the guide
          against how many filled the form. Those are opposite problems needing
          opposite fixes, and without this they look identical. */}
      <LandingTracker variant="fall" />
      {/* Below `lg` this is exactly the column it has always been. From `lg`
          the container widens and splits: the instrument moves into a sticky
          rail on the left and stays with the reader through all four bands,
          while the reading column keeps the SAME measure it has today. That is
          the point — the page was narrow on a desktop, but widening the prose
          would have pushed lines past 100 characters and made it worse. The
          width goes to structure, not to line length. */}
      <article className="mx-auto max-w-2xl px-5 py-14 sm:px-8 sm:py-20 lg:max-w-5xl">
        <header className="max-w-2xl">
        {brandLine && (
          <a
            href="/"
            className="inline-block text-[11px] uppercase tracking-[0.18em] text-ln-muted hover:text-ln-gold"
          >
            {brandLine}
          </a>
        )}

        <h1 className="mt-5 font-ln-serif text-[34px] leading-[1.15] text-ln-dark sm:text-[46px]">
          {TITLE}
        </h1>

        <p className="mt-6 text-[16px] leading-[1.7]">
          Aspens turn from the top down. So the useful question is not <em>where</em> — it
          is <em>how high, this week</em>. Here is the whole season, sorted by elevation.
        </p>
        </header>

        <div className="mt-10 lg:grid lg:grid-cols-[300px_minmax(0,1fr)] lg:items-start lg:gap-14">
          {/* The instrument and the line that says how to read it, together.
              `self-start` is what lets the sticky work at all inside a grid:
              without it the cell stretches to the row's height and there is
              nothing left for the element to stick within. */}
          <div className="lg:sticky lg:top-10 lg:self-start">
            <ElevationLadder />

            {/* The one line that makes this a guide rather than a list. It is
                also the thing a local actually says out loud, which is why it
                sits directly under the instrument it explains how to read. */}
            <p className="mt-8 border-l-2 border-ln-gold pl-5 font-ln-serif text-[19px] leading-[1.55] text-ln-dark sm:text-[21px] lg:text-[19px]">
              If the top of the pass is already bare, go lower. If the valley is still
              green, go higher.
            </p>
          </div>

          <div className="max-w-2xl">
        <p className="mt-8 bg-ln-tint px-5 py-4 text-[15px] leading-[1.7] sm:px-6 sm:py-5 lg:mt-0">
          <strong className="font-semibold text-ln-dark">2026 runs early.</strong> After a
          record-low snowpack and a dry summer, the high country is expected to peak sooner
          than average — think mid-to-late September up top rather than the end of the
          month. Drought-stressed aspens also turn earlier, read duller, and drop their
          leaves faster, so a trip you postpone by a week is a trip you may lose.
        </p>

        <div className="mt-14 space-y-14">
          {BANDS.map((band) => (
            <section key={band.id} id={band.id} className="scroll-mt-6">
              {/* Elevation and window only: the note that used to sit here now
                  leads the ladder above, and repeating it four times under an
                  index that just said it reads as padding. */}
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-ln-hair pb-4">
                <h2 className="font-ln-serif text-[26px] leading-tight text-ln-dark">
                  {band.elevation}
                </h2>
                <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ln-gold">
                  {band.when}
                </p>
              </div>

              <ul className="mt-8 space-y-10">
                {band.spots.map((spot) => (
                  <SpotEntry key={spot.name} spot={spot} />
                ))}
              </ul>
            </section>
          ))}
        </div>

        <section className="mt-14 border-t border-ln-hair pt-10">
          <h2 className="font-ln-serif text-[22px] text-ln-dark">Three things worth knowing</h2>
          <ul className="mt-5 space-y-3.5 text-[15px] leading-[1.7]">
            <li>
              <strong className="font-semibold text-ln-dark">Go early.</strong> Kenosha and
              Guanella fill their pullouts by mid-morning on a September weekend. A weekday
              at sunrise is a different mountain than a Saturday at noon.
            </li>
            <li>
              <strong className="font-semibold text-ln-dark">Check before you drive.</strong>{" "}
              A single windy night strips a pass. The bands above tell you where to go
              instead, which is the point of having them.
            </li>
            <li>
              <strong className="font-semibold text-ln-dark">Higher is not better.</strong>{" "}
              The best week of color at 7,000 ft is as good as the best week at 11,000 ft —
              it just happens three weeks later.
            </li>
          </ul>
          <p className="mt-7 text-[12px] leading-relaxed text-ln-muted">
            Elevation bands and drive distances follow Visit Denver&rsquo;s fall foliage guide;
            timing reflects this year&rsquo;s published forecasts. Conditions change weekly —
            treat every date here as a window, not an appointment.
          </p>
        </section>

        {/* Who wrote it, immediately before the ask. A stranger who has just
            read two thousand words of local knowledge should see the people
            behind them before being asked anything — and, like the footer, it
            renders only where the operator has actually named the advisors. */}
        {LANDING.advisors && (
          <div className="mt-14 flex items-center gap-4 border-t border-ln-hair pt-8">
            {/* eslint-disable-next-line @next/next/no-img-element -- see above. */}
            <img
              src="/landing/natalia-robbie.jpg"
              alt={LANDING.advisors}
              loading="lazy"
              decoding="async"
              className="h-16 w-16 flex-none bg-ln-tint object-cover [object-position:50%_16%]"
            />
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-ln-muted">Written by</p>
              <p className="mt-1 font-ln-serif text-[20px] leading-tight text-ln-dark">
                {LANDING.advisors}
              </p>
              {LANDING.brokerage && (
                <p className="mt-1 text-[12px] leading-[1.5] text-ln-muted">
                  Real estate advisors · {LANDING.brokerage}
                </p>
              )}
            </div>
          </div>
        )}
          </div>
        </div>
      </article>

      <section className="bg-ln-dark px-5 py-16 sm:px-8 sm:py-20">
        <div className="mx-auto max-w-2xl">
          <h2 className="font-ln-serif text-[28px] leading-tight text-ln-cream sm:text-[34px]">
            While you are out looking at the neighborhoods
          </h2>
          {/* The honest version of the ask. This page's visitor came for aspens,
              not for a realtor, and pretending otherwise is how a guide people
              trusted becomes an ad they resent. It says who we are, what we do,
              and leaves. */}
          <p className="mt-5 text-[15px] leading-[1.75] text-ln-canvas/75">
            Fall is when a lot of people in Denver decide whether they are moving before
            winter. If that is on your mind — buying, selling, or just wanting to know what
            your home would be worth today — we are happy to talk it through. No pressure,
            and no obligation to do anything about it this year.
          </p>

          <div className="mt-10">
            {/* The landing's form, not a copy of it: same endpoint, same
                honeypot, same Turnstile, same consent string rendered and
                stored. Only the attribution differs, so a lead from this page
                is distinguishable in the Inbox from one that came off the
                landing. */}
            <ConsultForm variant="fall" />
          </div>
        </div>
      </section>

      <footer className="border-t border-ln-hair bg-ln-canvas px-5 py-10 sm:px-8">
        <div className="mx-auto max-w-2xl text-[11px] leading-[1.75] tracking-[0.04em] text-ln-muted lg:max-w-5xl">
          {footerWho && <p>{footerWho}</p>}
          {legal.length > 0 && <p>{legal.join(" · ")}</p>}
        </div>
      </footer>
    </main>
  );
}
