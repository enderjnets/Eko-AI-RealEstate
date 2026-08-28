"use client";

/**
 * The public landing — the v4 design from the Claude Design project, converted
 * to a responsive page. Root is deliberately the marketing page and not the
 * dashboard: this is the address a stranger arrives at from an ad or a video.
 * Staff sign in at /login, which still lands on /leads.
 *
 * Everything factual on this page — the advisors' names, the brokerage, the
 * office address, phone numbers — is read from lib/landing.ts and rendered
 * only when it has actually been configured. A real-estate advertisement that
 * invents any of those is not a placeholder, it is a false statement to a
 * consumer.
 *
 * The imagery is served from `public/landing/`, never hotlinked from the
 * design tool's CDN: that host belongs to somebody else's uptime and referrer
 * policy, and it would break silently — the layout would still render, with
 * holes. The hero is a <video> whose poster is the design's hero plate; when
 * `/landing/casa-hero.mp4` has not been shipped, the poster IS the hero and
 * the page is complete without it.
 *
 * Every section lives at module scope, NOT nested inside `Landing`. Nested
 * component functions get a new identity on each render, so React tears down
 * and rebuilds the whole subtree — and since `useI18n` re-renders every
 * consumer on language change, switching to Spanish mid-form would wipe the
 * visitor's name, phone, consent tick and Turnstile token on the one page
 * whose entire purpose is that form.
 */

import Link from "next/link";
import { Building2, CalendarCheck, Clock, Phone, Ruler, Users } from "lucide-react";
import { LANDING, dialable } from "@/lib/landing";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { ConsultForm } from "@/components/landing/ConsultForm";

function Eyebrow({ children, tone = "dark" }: { children: React.ReactNode; tone?: "dark" | "light" }) {
  return (
    <p
      className={`text-[10px] font-medium uppercase tracking-[0.3em] ${
        tone === "dark" ? "text-ln-muted" : "text-ln-cream/60"
      }`}
    >
      {children}
    </p>
  );
}

/** The design's signature heading: light serif with an italic tail. */
function SplitTitle({ a, italic }: { a: string; italic: string }) {
  return (
    <h2 className="font-ln-serif text-[38px] font-light leading-[1.04] tracking-[-0.015em] text-ln-ink sm:text-[52px] lg:text-[58px]">
      {a}
      <br />
      <span className="italic">{italic}</span>.
    </h2>
  );
}

function LandingNav() {
  const { t } = useI18n();
  return (
    <header className="absolute inset-x-0 top-0 z-20">
      <div className="flex items-center justify-between gap-4 px-5 py-6 sm:px-10 lg:px-14 lg:py-8">
        <div className="min-w-0">
          {LANDING.advisors && (
            <p className="truncate font-ln-serif text-[22px] font-light leading-none tracking-[0.06em] text-ln-ink sm:text-[25px]">
              {LANDING.advisors}
            </p>
          )}
          {LANDING.brokerage && (
            <p className="mt-1 truncate text-[8px] font-medium uppercase tracking-[0.3em] text-ln-ink/60">
              {LANDING.brokerage}
            </p>
          )}
        </div>
        <nav className="flex items-center gap-5 lg:gap-9">
          <a
            href="#about"
            className="hidden text-[11px] uppercase tracking-[0.18em] text-ln-ink/75 hover:text-ln-gold md:inline"
          >
            {t("landing.nav.about")}
          </a>
          <a
            href="#how"
            className="hidden text-[11px] uppercase tracking-[0.18em] text-ln-ink/75 hover:text-ln-gold md:inline"
          >
            {t("landing.how.eyebrow")}
          </a>
          <a
            href="#markets"
            className="hidden text-[11px] uppercase tracking-[0.18em] text-ln-ink/75 hover:text-ln-gold md:inline"
          >
            {t("landing.nav.markets")}
          </a>
          <span className="[&_button]:text-ln-ink/60 [&_button:hover]:text-ln-ink">
            <LanguageSwitcher />
          </span>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
  const { t } = useI18n();
  return (
    <section className="relative overflow-hidden bg-[linear-gradient(180deg,#A9BDD2_0%,#C7D0D6_26%,#E1DBD1_52%,#EFE3D0_74%,#E4D4BC_100%)]">
      {/* The design's radial glow: it is what keeps the paragraph readable
          where the composition lets it ride over the house. */}
      <div className="relative z-10 flex flex-col items-center px-5 pb-[46vw] pt-28 text-center [background:radial-gradient(58%_66%_at_50%_44%,rgba(244,241,234,0.78)_0%,rgba(244,241,234,0.44)_54%,rgba(244,241,234,0)_80%)] sm:px-10 sm:pt-36 md:pb-[380px] lg:pt-40">
        <p className="mb-7 text-[10px] font-medium uppercase tracking-[0.32em] text-ln-ink/60">
          {t("landing.hero.kicker")}
        </p>
        <h1 className="mb-6 font-ln-serif text-[52px] font-light leading-[0.95] tracking-[-0.025em] text-ln-ink sm:text-[80px] lg:text-[108px]">
          {t("landing.hero.titleLine1")}
          <br />
          {t("landing.hero.titleLine2")} <span className="italic">{t("landing.hero.titleItalic")}</span>.
        </h1>
        <p className="mb-9 max-w-[600px] text-[15px] leading-[1.7] text-ln-ink-soft [text-shadow:0_1px_14px_rgba(244,241,234,0.95)] sm:text-base">
          {t("landing.hero.body")}
        </p>
        <div className="flex flex-col items-center gap-3.5 sm:flex-row">
          <a
            href="#consult"
            className="inline-flex min-h-[52px] items-center gap-3 rounded-full bg-[#242219] px-8 py-4 text-[11px] font-medium uppercase tracking-[0.16em] text-ln-canvas hover:opacity-90"
          >
            <CalendarCheck className="h-3.5 w-3.5" />
            {t("landing.hero.cta")}
          </a>
          {LANDING.phone && (
            <a
              href={`tel:${dialable(LANDING.phone)}`}
              className="inline-flex min-h-[52px] items-center gap-3 rounded-full border border-ln-ink/25 bg-ln-canvas/80 px-8 py-4 text-[11px] font-medium uppercase tracking-[0.16em] text-ln-ink backdrop-blur hover:border-ln-gold"
            >
              <Phone className="h-3.5 w-3.5" />
              {t("landing.hero.callUs")}
            </a>
          )}
        </div>
      </div>

      {/* The house, rising into the composition from below. Poster-first: the
          clip is an enhancement the page must never depend on. */}
      <div className="absolute inset-x-0 bottom-0 z-0 h-[52vw] max-h-[560px] overflow-hidden [mask-image:radial-gradient(135%_108%_at_50%_100%,#000_70%,transparent_99%)]">
        <video
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          poster="/landing/hero-plate.jpg"
          className="h-full w-full object-cover [object-position:50%_42%]"
        >
          <source src="/landing/casa-hero.mp4" type="video/mp4" />
        </video>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-28 bg-gradient-to-b from-transparent via-ln-warm/30 to-ln-warm" />
    </section>
  );
}

function TwoOfUs() {
  const { t } = useI18n();
  const credentials = [
    [LANDING.advisors, t("landing.footer.role"), LANDING.brokerage]
      .filter(Boolean)
      .join(" · "),
    // "Licensed across Colorado" is a claim about a specific licence: it
    // appears only where the operator has said which brokerage this is —
    // the same rule the footer already applies.
    LANDING.brokerage ? t("landing.two.item2") : "",
    t("landing.two.item3"),
  ].filter(Boolean);

  return (
    <section id="about" className="scroll-mt-10 bg-ln-canvas">
      <div className="grid lg:grid-cols-2">
        <div className="flex flex-col justify-center px-5 py-16 sm:px-10 lg:px-14 lg:py-28">
          <Eyebrow>{t("landing.two.eyebrow")}</Eyebrow>
          <div className="mt-7">
            <SplitTitle a={t("landing.two.titleA")} italic={t("landing.two.titleItalic")} />
          </div>
          <p className="mt-6 max-w-[460px] text-base leading-[1.8] text-ln-body">
            {t("landing.two.p1")}
          </p>
          <p className="mt-5 max-w-[460px] text-base leading-[1.8] text-ln-body">
            {t("landing.two.p2")}
          </p>
          <ol className="mt-10 border-t border-ln-hair">
            {credentials.map((line, i) => (
              <li
                key={line}
                className="flex items-baseline gap-5 border-b border-ln-hair py-5"
              >
                <span className="w-7 flex-none font-ln-serif text-[15px] italic text-ln-gold">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="text-sm leading-[1.6] text-ln-ink-soft">{line}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="relative min-h-[420px] bg-ln-tint lg:min-h-[720px]">
          {/* eslint-disable-next-line @next/next/no-img-element -- the page
              uses plain <img> throughout: `sharp` is not installed, so
              next/image would optimise nothing and only add a dependency. */}
          <img
            src="/landing/natalia-robbie.jpg"
            alt={LANDING.advisors || ""}
            loading="lazy"
            decoding="async"
            className="absolute inset-0 h-full w-full object-cover"
          />
        </div>
      </div>
    </section>
  );
}

function HowWeWork() {
  const { t } = useI18n();
  const cards = [
    { Icon: Building2, title: t("landing.how.oneFile.title"), body: t("landing.how.oneFile.body") },
    { Icon: Ruler, title: t("landing.how.price.title"), body: t("landing.how.price.body") },
    { Icon: Users, title: t("landing.how.network.title"), body: t("landing.how.network.body") },
    { Icon: Clock, title: t("landing.how.answered.title"), body: t("landing.how.answered.body") },
  ];
  return (
    <section id="how" className="scroll-mt-10 bg-ln-stone">
      <div className="px-5 py-16 sm:px-10 lg:px-14 lg:py-28">
        <div className="mb-14 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between lg:gap-16">
          <div>
            <Eyebrow>{t("landing.how.eyebrow")}</Eyebrow>
            <div className="mt-6">
              <SplitTitle a={t("landing.how.titleA")} italic={t("landing.how.titleItalic")} />
            </div>
          </div>
          <p className="max-w-[340px] text-[15px] leading-[1.8] text-ln-body">
            {t("landing.how.intro")}
          </p>
        </div>
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-11">
          {cards.map(({ Icon, title, body }) => (
            <article key={title} className="border-t border-ln-line-strong pt-6">
              <Icon className="h-[22px] w-[22px] text-ln-gold" strokeWidth={1} />
              <h3 className="mb-3 mt-6 font-ln-serif text-[26px] leading-[1.2] text-ln-ink">
                {title}
              </h3>
              <p className="text-sm leading-[1.75] text-ln-body">{body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Markets() {
  const { t } = useI18n();
  const markets = [
    { key: "aspen", src: "/landing/aspen-card.jpg" },
    { key: "valley", src: "/landing/valley-card.jpg" },
    { key: "denver", src: "/landing/denver-card.jpg" },
  ];
  return (
    <section id="markets" className="scroll-mt-10 bg-ln-canvas">
      <div className="px-5 py-16 sm:px-10 lg:px-14 lg:py-28">
        <div className="mb-12">
          <Eyebrow>{t("landing.markets.eyebrow")}</Eyebrow>
          <div className="mt-6">
            <SplitTitle a={t("landing.markets.titleA")} italic={t("landing.markets.titleItalic")} />
          </div>
        </div>
        <div className="grid gap-10 sm:grid-cols-3 sm:gap-5">
          {markets.map(({ key, src }, i) => (
            <article key={key}>
              <div className="overflow-hidden bg-ln-tint">
                {/* eslint-disable-next-line @next/next/no-img-element -- see
                    the portrait note. Sized 3:2 to match the downscaled files
                    exactly, so nothing reflows as they load. */}
                <img
                  src={src}
                  alt=""
                  width={1200}
                  height={800}
                  loading={i === 0 ? "eager" : "lazy"}
                  decoding="async"
                  className="aspect-[3/4] w-full object-cover sm:aspect-[4/5]"
                />
              </div>
              <div className="mt-4 flex items-baseline justify-between gap-5 border-t border-ln-hair pt-4">
                <div>
                  <h3 className="font-ln-serif text-2xl text-ln-ink">
                    {t(`landing.markets.${key}.title`)}
                  </h3>
                  <p className="mt-1 text-xs tracking-[0.04em] text-ln-muted">
                    {t(`landing.markets.${key}.body`)}
                  </p>
                </div>
                <span className="whitespace-nowrap font-ln-serif text-sm italic text-ln-gold">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Consult() {
  const { t } = useI18n();
  return (
    <section id="consult" className="relative scroll-mt-10 overflow-hidden bg-ln-dark">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/landing/cta-bg.jpg"
        alt=""
        loading="lazy"
        decoding="async"
        className="absolute inset-0 h-full w-full object-cover"
      />
      <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(20,18,14,0.88)_0%,rgba(20,18,14,0.76)_46%,rgba(20,18,14,0.6)_100%)]" />
      <div className="relative grid items-center gap-14 px-5 py-20 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-24 lg:px-14 lg:py-32">
        <div>
          <h2 className="font-ln-serif text-[44px] font-light leading-none tracking-[-0.02em] text-ln-cream sm:text-[60px] lg:text-[76px]">
            {t("landing.consult.titleA")}
            <br />
            <span className="italic">{t("landing.consult.titleItalic")}</span>.
          </h2>
          <p className="mt-6 max-w-[430px] text-base leading-[1.8] text-ln-canvas/80">
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
  // "Licensed in Colorado" is a claim about a specific licence: it appears
  // only where the operator has said which brokerage this is.
  const legal = [
    LANDING.address,
    LANDING.brokerage ? t("landing.footer.licensed") : "",
    LANDING.brokerage ? t("landing.footer.equalHousing") : "",
  ].filter(Boolean);

  return (
    <footer className="border-t border-ln-hair bg-ln-canvas">
      <div className="flex flex-col gap-6 px-5 py-11 sm:flex-row sm:items-start sm:justify-between sm:gap-12 sm:px-10 lg:px-14">
        <div className="text-[11px] leading-[1.75] tracking-[0.04em] text-ln-muted">
          {(LANDING.advisors || LANDING.brokerage) && (
            <p>
              {[LANDING.advisors, t("landing.footer.role"), LANDING.brokerage]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {legal.length > 0 && <p>{legal.join(" · ")}</p>}
        </div>
        {/* inline-flex + min-height so the tap target reaches 44px on a
            phone. As a bare inline link it measured 15px. */}
        <Link
          href="/login"
          className="inline-flex min-h-[44px] items-center whitespace-nowrap text-[11px] tracking-[0.04em] text-ln-muted underline underline-offset-4 hover:text-ln-gold"
        >
          {t("landing.footer.staffLogin")}
        </Link>
      </div>
    </footer>
  );
}

export function Landing() {
  return (
    // `eko-landing` is the hook globals.css uses to repaint the document
    // background: the app shell is dark, and without it the overscroll gutter
    // bounces black behind a cream page.
    <div className="eko-landing relative min-h-screen bg-ln-canvas font-ln-sans text-ln-ink antialiased">
      <LandingNav />
      <main>
        <Hero />
        <TwoOfUs />
        <HowWeWork />
        <Markets />
        <Consult />
      </main>
      <LandingFooter />
    </div>
  );
}
