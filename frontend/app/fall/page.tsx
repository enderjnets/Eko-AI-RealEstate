import type { Metadata, Viewport } from "next";

import { ConsultForm } from "@/components/landing/ConsultForm";
import { LandingTracker } from "@/components/landing/LandingTracker";
import { LANDING, homeScreenName } from "@/lib/landing";
import { BRAND_URL } from "@/lib/hosts";

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
 * The bands, and why the guide is built out of them rather than out of a
 * ranked list of places.
 *
 * Aspens turn from the top down. A page that names "the seven best spots" is
 * wrong twice in one season: too early for the low valleys in September, and
 * pointing at bare passes in October. Elevation is the axis that keeps the
 * advice true the whole time, and it is also the single most useful thing a
 * local knows that a visitor does not.
 */
type Spot = { name: string; drive: string; what: string };
type Band = { elevation: string; when: string; note: string; spots: Spot[] };

const BANDS: Band[] = [
  {
    elevation: "Above 9,500 ft",
    when: "Mid to late September",
    note: "The high passes go first, and they go fast — a windy week can end it.",
    spots: [
      {
        name: "Guanella Pass Scenic Byway",
        drive: "40 miles",
        what:
          "Twenty-two miles of byway between Georgetown and Grant, topping out at " +
          "11,670 ft under Mount Blue Sky and Mount Bierstadt, with thick aspen " +
          "stands on both sides near the summit.",
      },
      {
        name: "Kenosha Pass",
        drive: "60 miles, US 285",
        what:
          "The classic Denver leaf drive. At about 10,000 ft the highway tops out " +
          "and the whole South Park basin opens up in gold. The lots on both sides " +
          "of the road fill early — this is a sunrise trip, not a lunchtime one.",
      },
      {
        name: "Peak to Peak Byway",
        drive: "CO 72 and CO 7",
        what:
          "Black Hawk up to Estes Park, with high aspen groves most of the way. " +
          "The long option: it works as a loop rather than an out-and-back.",
      },
    ],
  },
  {
    elevation: "7,000 – 9,000 ft",
    when: "Late September to mid October",
    note: "The widest window of the season, and the one that survives a bad forecast.",
    spots: [
      {
        name: "Georgetown Loop Railroad",
        drive: "40 miles",
        what:
          "A vintage steam locomotive between Georgetown and Silver Plume, " +
          "surrounded by aspen. The one on this list that works with small " +
          "children and with anyone who would rather not hike.",
      },
      {
        name: "Mighty Argo Cable Car, Idaho Springs",
        drive: "33 miles",
        what:
          "Gondolas climbing from 7,550 ft to 8,800 ft at Miners Point. Height " +
          "without a trailhead, and the shortest drive of any real overlook here.",
      },
      {
        name: "Dillon Reservoir — Frisco and Silverthorne",
        drive: "69 miles",
        what:
          "An 18-mile paved path circles the lake, so you can take as much or as " +
          "little of it as the afternoon allows.",
      },
    ],
  },
  {
    elevation: "6,000 – 8,000 ft",
    when: "Most of October",
    note: "When the passes are bare and everyone assumes it is over, this is where it is.",
    spots: [
      {
        name: "Golden Gate Canyon State Park",
        drive: "Northwest of Golden",
        what:
          "Lower-elevation aspen groves with the mountain vistas behind them. " +
          "Close enough to go after work.",
      },
      {
        name: "Evergreen",
        drive: "CO 74, the Lariat Loop",
        what:
          "Maxwell Falls and Alderfer/Three Sisters Park for walking, and the " +
          "Lariat Loop Scenic Byway through Bergen Park and back down to Golden " +
          "for driving.",
      },
      {
        name: "Central City",
        drive: "Oh My God Road to Idaho Springs",
        what:
          "Aspen around the old cemeteries above town, and a slow unpaved road " +
          "down to Idaho Springs that is worth the hour it takes.",
      },
    ],
  },
  {
    elevation: "Denver itself, 5,280 ft",
    when: "October into November",
    note: "The part people forget: the last three weeks of color happen at home.",
    spots: [
      {
        name: "High Line Canal Trail",
        drive: "City-wide",
        what: "More than 70 miles of cottonwoods threading the whole metro area.",
      },
      {
        name: "Cherry Creek and South Platte trails",
        drive: "From downtown",
        what:
          "Forty-plus miles each — downtown out to Cherry Creek State Park, and " +
          "the river down to Chatfield and Waterton Canyon.",
      },
      {
        name: "Washington Park, City Park, Sloan's Lake",
        drive: "In town",
        what:
          "The three that hold their color longest, and the ones you can walk " +
          "to from a Denver neighborhood.",
      },
    ],
  },
];

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
      <article className="mx-auto max-w-2xl px-5 py-14 sm:px-8 sm:py-20">
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

        <p className="mt-6 text-[16px] leading-[1.75]">
          Most fall-color lists give you seven places and go stale in eight days. Aspens
          turn from the top down, so the useful question is not <em>where</em> — it is{" "}
          <em>how high, this week</em>. Here is the whole season, sorted by elevation.
        </p>

        {/* The one line that makes this a guide rather than a list. It is also
            the thing a local actually says out loud, which is why it leads. */}
        <p className="mt-7 border-l-2 border-ln-gold pl-5 font-ln-serif text-[19px] leading-[1.55] text-ln-dark">
          If the top of the pass is already bare, go lower. If the valley is still green,
          go higher.
        </p>

        <p className="mt-7 text-[15px] leading-[1.75]">
          <strong className="font-semibold text-ln-dark">2026 runs early.</strong> After a
          record-low snowpack and a dry summer, the high country is expected to peak sooner
          than average — think mid-to-late September up top rather than the end of the
          month. Drought-stressed aspens also turn earlier, read duller, and drop their
          leaves faster, so a trip you postpone by a week is a trip you may lose.
        </p>

        <div className="mt-14 space-y-14">
          {BANDS.map((band) => (
            <section key={band.elevation}>
              <div className="border-b border-ln-hair pb-4">
                <h2 className="font-ln-serif text-[26px] leading-tight text-ln-dark">
                  {band.elevation}
                </h2>
                <p className="mt-1.5 text-[13px] uppercase tracking-[0.14em] text-ln-gold">
                  {band.when}
                </p>
                <p className="mt-2.5 text-[14px] leading-relaxed text-ln-muted">{band.note}</p>
              </div>

              <ul className="mt-7 space-y-7">
                {band.spots.map((spot) => (
                  <li key={spot.name}>
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h3 className="font-ln-serif text-[19px] text-ln-dark">{spot.name}</h3>
                      <span className="text-[12px] uppercase tracking-[0.1em] text-ln-muted">
                        {spot.drive}
                      </span>
                    </div>
                    <p className="mt-2 text-[15px] leading-[1.7]">{spot.what}</p>
                  </li>
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
        <div className="mx-auto max-w-2xl text-[11px] leading-[1.75] tracking-[0.04em] text-ln-muted">
          {footerWho && <p>{footerWho}</p>}
          {legal.length > 0 && <p>{legal.join(" · ")}</p>}
        </div>
      </footer>
    </main>
  );
}
