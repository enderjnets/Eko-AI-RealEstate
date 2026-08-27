"use client";

/**
 * The public landing. Root is deliberately the marketing page and not the
 * dashboard: this is the address a stranger arrives at from an ad or a video.
 * Staff sign in at /login, which still lands on /leads.
 *
 * Everything factual on this page — the advisors' names, the brokerage, the
 * office address, phone numbers, years in business, client quotes — is read
 * from lib/landing.ts and rendered only when it has actually been configured.
 * A real-estate advertisement that invents any of those is not a placeholder,
 * it is a false statement to a consumer.
 *
 * Every section below lives at module scope, NOT nested inside `Landing`.
 * Nested component functions get a new identity on each render, so React tears
 * down and rebuilds the whole subtree — and since `useI18n` re-renders every
 * consumer when the language changes, switching to Spanish mid-form would have
 * wiped the visitor's name, phone, consent tick and Turnstile token on the one
 * page whose entire purpose is that form.
 */

import Link from "next/link";
import { LANDING, dialable } from "@/lib/landing";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ConsultForm } from "@/components/landing/ConsultForm";

/**
 * An operator-supplied URL is rendered into `href`, and `javascript:` in an
 * href executes on click. Only http(s) survives; anything else falls back to
 * the on-page form, which works regardless.
 */
function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function BookLink({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const external = LANDING.bookingUrl ? safeHttpUrl(LANDING.bookingUrl) : null;
  if (external) {
    return (
      <a href={external} target="_blank" rel="noreferrer" className={className}>
        {children}
      </a>
    );
  }
  return (
    <a href="#consult" className={className}>
      {children}
    </a>
  );
}

function LandingNav() {
  const { t } = useI18n();
  return (
    <header className="border-b border-ln-line bg-ln-paper">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <div className="min-w-0">
          {LANDING.advisors && (
            <p className="truncate font-ln-serif text-lg leading-tight text-ln-ink">
              {LANDING.advisors}
            </p>
          )}
          {LANDING.brokerage && (
            <p className="truncate text-[10px] uppercase tracking-[0.18em] text-ln-body">
              {LANDING.brokerage}
            </p>
          )}
        </div>
        <nav className="flex items-center gap-5">
          <a
            href="#how"
            className="hidden text-[13px] text-ln-ink-soft hover:text-ln-bronze sm:inline"
          >
            {t("landing.how.eyebrow")}
          </a>
          {/* Only when the section it points at exists. With no phone, SMS or
              mailbox configured "Reach us" renders nothing, and the link
              became a nav item that does nothing when clicked. */}
          {LANDING.hasAnyChannel && (
            <a
              href="#reach"
              className="hidden text-[13px] text-ln-ink-soft hover:text-ln-bronze sm:inline"
            >
              {t("landing.reach.eyebrow")}
            </a>
          )}
          <BookLink className="bg-ln-ink px-4 py-2.5 text-[11px] uppercase tracking-[0.08em] text-ln-paper hover:opacity-90">
            {t("landing.nav.book")}
          </BookLink>
          {/* The switcher is styled for the dark dashboard; on cream it needs
              ink colours or the control that makes the page bilingual is
              invisible on it (1.4:1 against #FBFAF7). */}
          <span className="[&_button]:text-ln-body [&_button:hover]:text-ln-ink">
            <LanguageSwitcher />
          </span>
        </nav>
      </div>
    </header>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-ln-paper px-5 py-7 sm:px-8">
      <p className="font-ln-serif text-4xl text-ln-ink">{value}</p>
      <p className="mt-2 text-[11px] leading-[1.5] tracking-[0.04em] text-ln-body">{label}</p>
    </div>
  );
}

function Hero() {
  const { t } = useI18n();
  const portrait = LANDING.portrait ? safeHttpUrl(LANDING.portrait) ?? LANDING.portrait : "";
  return (
    <section className="border-b border-ln-line bg-ln-paper">
      {/* Without a portrait the two-column grid leaves half the hero blank, so
          the layout collapses to one column rather than framing a hole. */}
      <div
        className={`mx-auto grid max-w-6xl gap-10 px-5 py-14 sm:px-8 sm:py-20 lg:gap-16 ${
          portrait ? "lg:grid-cols-[1.1fr_0.9fr] lg:items-center" : ""
        }`}
      >
        <div>
          <p className="text-[10px] uppercase tracking-[0.22em] text-ln-body">
            {t("landing.hero.kicker")}
          </p>
          {/* Capped so the headline keeps an editorial measure instead of
              stretching across the full width when there is no portrait. */}
          <h1 className="mt-5 max-w-[15ch] font-ln-serif text-[38px] leading-[1.08] tracking-[-0.01em] text-ln-ink sm:text-[52px] lg:text-[62px]">
            {t("landing.hero.title")}
          </h1>
          <p className="mt-6 max-w-xl text-[15px] leading-[1.75] text-ln-body">
            {t("landing.hero.body")}
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
            <BookLink className="bg-ln-bronze px-7 py-4 text-center text-[12px] uppercase tracking-[0.10em] text-ln-paper hover:opacity-90">
              {t("landing.hero.cta")}
            </BookLink>
            {LANDING.phone && (
              <a
                href={`tel:${dialable(LANDING.phone)}`}
                className="px-1 py-2 text-center text-[13px] text-ln-ink-soft underline decoration-ln-line-strong underline-offset-4 hover:text-ln-bronze"
              >
                {t("landing.hero.callUs")} · {LANDING.phone}
              </a>
            )}
          </div>
        </div>

        {portrait && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={portrait}
            alt={LANDING.advisors || ""}
            className="h-full max-h-[520px] w-full object-cover"
          />
        )}
      </div>

      {LANDING.hasStats && (
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-px border-t border-ln-line bg-ln-line sm:grid-cols-2">
          <Stat value={LANDING.years} label={t("landing.stats.years")} />
          <Stat value={LANDING.markets} label={t("landing.stats.markets")} />
        </div>
      )}
    </section>
  );
}

function HowWeWork() {
  const { t } = useI18n();
  const cards = [
    { title: t("landing.how.oneFile.title"), body: t("landing.how.oneFile.body") },
    { title: t("landing.how.price.title"), body: t("landing.how.price.body") },
    { title: t("landing.how.network.title"), body: t("landing.how.network.body") },
    { title: t("landing.how.answered.title"), body: t("landing.how.answered.body") },
  ];
  return (
    <section id="how" className="scroll-mt-20 border-b border-ln-line">
      <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <p className="text-[10px] uppercase tracking-[0.22em] text-ln-body">
          {t("landing.how.eyebrow")}
        </p>
        <h2 className="mt-5 max-w-2xl font-ln-serif text-[30px] leading-[1.15] text-ln-ink sm:text-[40px]">
          {t("landing.how.title")}
        </h2>
        <div className="mt-10 grid gap-px bg-ln-line sm:grid-cols-2">
          {cards.map((c) => (
            <article key={c.title} className="bg-ln-paper p-6 sm:p-8">
              <h3 className="font-ln-serif text-[21px] text-ln-ink">{c.title}</h3>
              <p className="mt-3 text-sm leading-[1.7] text-ln-body">{c.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * The three markets, with a photograph of each.
 *
 * The one section of the v4 design that was never built — the copy for every
 * other section already lives in `i18n.tsx`, this one had nothing. It is also
 * the only place on the page that answers "do these people actually work where
 * I am looking?", which is the question a Denver viewer arrives with after
 * watching a video, so its absence cost the funnel more than it looks.
 *
 * The images are served from `public/landing/`, not from the CDN the design
 * references (`photos.prod.cirrussystem.net`). That host belongs to the design
 * tool, not to us: hotlinking it would put the brand page's hero imagery behind
 * somebody else's uptime and referrer policy, and it would break silently — the
 * layout would still render, with holes. They were downscaled on the way in
 * (3000px originals to 1200px, 2.4 MB to 1.5 MB across the set) because this
 * page is reached from a phone, over mobile data, by someone who has already
 * decided to give us fifteen seconds.
 *
 * Market names and neighbourhoods live in i18n with the rest of the design
 * copy, not in `lib/landing.ts` env vars. The line `landing.ts` draws is
 * between descriptive copy and *verifiable business data* — a phone number, a
 * licence, an address, a years-in-business count, a testimonial — which is
 * never invented because inventing it is false advertising. Which
 * neighbourhoods an advisor covers is the former; if that ever becomes a
 * per-tenant claim rather than this page's copy, it moves to env with the rest.
 */
function Markets() {
  const { t } = useI18n();
  const markets = [
    { key: "aspen", src: "/landing/aspen-card.jpg" },
    { key: "valley", src: "/landing/valley-card.jpg" },
    { key: "denver", src: "/landing/denver-card.jpg" },
  ];
  return (
    <section id="markets" className="scroll-mt-20 border-b border-ln-line bg-ln-paper">
      <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <p className="text-[10px] uppercase tracking-[0.22em] text-ln-body">
          {t("landing.markets.eyebrow")}
        </p>
        <h2 className="mt-5 max-w-2xl font-ln-serif text-[30px] leading-[1.15] text-ln-ink sm:text-[40px]">
          {t("landing.markets.title")}
        </h2>
        <div className="mt-10 grid gap-6 sm:grid-cols-3">
          {markets.map(({ key, src }, i) => (
            <article key={key}>
              <div className="overflow-hidden border border-ln-line">
                {/* eslint-disable-next-line @next/next/no-img-element -- the
                    rest of this page uses plain <img> too: `sharp` is not
                    installed, so next/image would optimise nothing here and
                    only add a runtime dependency. Sized 3:2 to match the
                    downscaled files exactly, so nothing reflows as they load. */}
                <img
                  src={src}
                  alt=""
                  width={1200}
                  height={800}
                  /* The first card is above the fold on a phone; the other two
                     are not, and lazy-loading them is most of the byte saving. */
                  loading={i === 0 ? "eager" : "lazy"}
                  decoding="async"
                  className="aspect-[3/2] w-full object-cover"
                />
              </div>
              <h3 className="mt-4 font-ln-serif text-[21px] text-ln-ink">
                {t(`landing.markets.${key}.title`)}
              </h3>
              <p className="mt-1 text-sm leading-[1.7] text-ln-body">
                {t(`landing.markets.${key}.body`)}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Channel({
  href,
  label,
  value,
  hint,
}: {
  href: string;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <a href={href} className="group bg-ln-paper p-6 transition-colors hover:bg-ln-canvas sm:p-8">
      <p className="text-[10px] uppercase tracking-[0.18em] text-ln-body">{label}</p>
      <p className="mt-3 break-words font-ln-serif text-[21px] text-ln-ink group-hover:text-ln-bronze">
        {value}
      </p>
      <p className="mt-2 text-xs leading-[1.6] text-ln-body">{hint}</p>
    </a>
  );
}

function ReachUs() {
  const { t } = useI18n();
  // With no phone, no SMS number and no mailbox configured there is nothing
  // truthful to put here, so the section does not exist.
  if (!LANDING.hasAnyChannel) return null;
  return (
    <section id="reach" className="scroll-mt-20 border-b border-ln-line bg-ln-paper">
      <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <p className="text-[10px] uppercase tracking-[0.22em] text-ln-body">
          {t("landing.reach.eyebrow")}
        </p>
        <h2 className="mt-5 max-w-2xl font-ln-serif text-[30px] leading-[1.15] text-ln-ink sm:text-[40px]">
          {t("landing.reach.title")}
        </h2>
        <p className="mt-5 max-w-xl text-[15px] leading-[1.75] text-ln-body">
          {t("landing.reach.body")}
        </p>
        <div className="mt-10 grid gap-px bg-ln-line sm:grid-cols-3">
          {LANDING.phone && (
            <Channel
              href={`tel:${dialable(LANDING.phone)}`}
              label={t("landing.reach.call")}
              value={LANDING.phone}
              hint={t("landing.reach.callHint")}
            />
          )}
          {LANDING.sms && (
            <Channel
              href={`sms:${dialable(LANDING.sms)}`}
              label={t("landing.reach.text")}
              value={LANDING.sms}
              hint={t("landing.reach.textHint")}
            />
          )}
          {LANDING.email && (
            <Channel
              href={`mailto:${LANDING.email}`}
              label={t("landing.reach.email")}
              value={LANDING.email}
              hint={t("landing.reach.emailHint")}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function Voices() {
  const { t } = useI18n();
  // Client quotes ship only when real ones have been supplied and cleared.
  if (LANDING.testimonials.length === 0) return null;
  return (
    <section className="border-b border-ln-line">
      <div className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20">
        <h2 className="text-[10px] uppercase tracking-[0.22em] text-ln-body">
          {t("landing.voices.eyebrow")}
        </h2>
        <div className="mt-10 grid gap-px bg-ln-line md:grid-cols-3">
          {LANDING.testimonials.map((v) => (
            <figure key={v.attribution + v.quote.slice(0, 24)} className="bg-ln-paper p-6 sm:p-8">
              <blockquote className="font-ln-serif text-[19px] leading-[1.5] text-ln-ink">
                “{v.quote}”
              </blockquote>
              <figcaption className="mt-5 text-[11px] uppercase tracking-[0.12em] text-ln-body">
                {v.attribution}
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}

function Consult() {
  const { t } = useI18n();
  return (
    <section id="consult" className="scroll-mt-20 bg-ln-paper">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-14 sm:px-8 sm:py-20 lg:grid-cols-2 lg:items-start lg:gap-16">
        <div>
          <h2 className="font-ln-serif text-[30px] leading-[1.15] text-ln-ink sm:text-[40px]">
            {t("landing.consult.title")}
          </h2>
          <p className="mt-5 max-w-lg text-[15px] leading-[1.75] text-ln-body">
            {t("landing.consult.body")}
          </p>
        </div>
        <ConsultForm />
      </div>
    </section>
  );
}

function LandingFooter() {
  const { t } = useI18n();
  // `t()` never returns falsy, so a compliance line composed only of
  // translated strings would render on a blank install for a tenant in any
  // state. "Licensed in Colorado" is a claim about a specific licence: it
  // appears only where the operator has said which brokerage this is.
  const legal = [
    LANDING.address,
    LANDING.brokerage ? t("landing.footer.licensed") : "",
    LANDING.brokerage ? t("landing.footer.equalHousing") : "",
  ].filter(Boolean);

  return (
    <footer className="border-t border-ln-line bg-ln-canvas">
      <div className="mx-auto max-w-6xl space-y-2 px-5 py-10 text-[12px] leading-[1.7] text-ln-body sm:px-8">
        {(LANDING.advisors || LANDING.brokerage) && (
          <p className="text-ln-ink-soft">
            {[LANDING.advisors, t("landing.footer.role"), LANDING.brokerage]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
        {legal.length > 0 && <p>{legal.join(" · ")}</p>}
        <p className="pt-2">
          {/* inline-flex + min-height so the tap target reaches 44px on a
              phone. As a bare inline link it measured 15px, which is a miss
              more often than a hit. */}
          <Link
            href="/login"
            className="inline-flex min-h-[44px] items-center text-ln-body underline underline-offset-4 hover:text-ln-bronze"
          >
            {t("landing.footer.staffLogin")}
          </Link>
        </p>
      </div>
    </footer>
  );
}

export function Landing() {
  return (
    // `eko-landing` is the hook globals.css uses to repaint the document
    // background: the app shell is dark, and without it the overscroll gutter
    // bounces black behind a cream page.
    <div className="eko-landing min-h-screen bg-ln-canvas font-ln-sans text-ln-ink antialiased">
      <LandingNav />
      <main>
        <Hero />
        <HowWeWork />
        <Markets />
        <ReachUs />
        <Voices />
        <Consult />
      </main>
      <LandingFooter />
    </div>
  );
}
