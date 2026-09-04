"use client";

/**
 * The public landing — the v6 design from the Claude Design project, converted
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
 * holes. The hero is a <video> pinned to the viewport for several screens of
 * scrolling, its playhead driven by the scroll while four captions take turns
 * over it (LandingEffects documents the attributes). Its poster is the clip's
 * own first frame, so the page reads as complete and seamless before a byte
 * of video has arrived.
 *
 * Every section lives at module scope, NOT nested inside `Landing`. Nested
 * component functions get a new identity on each render, so React tears down
 * and rebuilds the whole subtree — and since `useI18n` re-renders every
 * consumer on language change, switching to Spanish mid-form would wipe the
 * visitor's name, phone, consent tick and Turnstile token on the one page
 * whose entire purpose is that form.
 *
 * What the design's 390px artboard leaves out and this page keeps: the Roaring
 * Fork Valley card, the fourth "how we work" card and the credentials list. An
 * artboard is a sketch of a phone, not a decision that a phone visitor should
 * hear about two markets instead of three.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowRight, Building2, CalendarCheck, Clock, Menu, Phone, Ruler, Users, X } from "lucide-react";
import { LANDING, dialable } from "@/lib/landing";
import { LandingEffects } from "@/components/landing/LandingEffects";
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

/** Sits on the film, so it is cream on dark and travels with the sticky stage. */
function LandingNav({ menuOpen, onOpenMenu }: { menuOpen: boolean; onOpenMenu: () => void }) {
  const { t } = useI18n();
  const link =
    "hidden text-[11px] uppercase tracking-[0.18em] text-ln-canvas/80 hover:text-ln-gold md:inline";
  return (
    <header className="absolute inset-x-0 top-0 z-[4]">
      <div className="flex items-center justify-between gap-4 px-5 py-6 sm:px-10 lg:px-14 lg:py-8">
        <div className="min-w-0">
          {LANDING.advisors && (
            <p className="truncate font-ln-serif text-[19px] font-light leading-none tracking-[0.05em] text-ln-canvas sm:text-[26px] sm:tracking-[0.06em]">
              {LANDING.advisors}
            </p>
          )}
          {LANDING.brokerage && (
            <p className="mt-1 truncate text-[7px] font-medium uppercase tracking-[0.28em] text-ln-canvas/60 sm:text-[8px] sm:tracking-[0.3em]">
              {LANDING.brokerage}
            </p>
          )}
        </div>
        <nav className="flex items-center gap-5 lg:gap-10">
          <a href="#consult" className={link}>
            {t("landing.nav.buying")}
          </a>
          <a href="#consult" className={link}>
            {t("landing.nav.selling")}
          </a>
          <a href="#markets" className={link}>
            {t("landing.nav.markets")}
          </a>
          <a href="#about" className={link}>
            {t("landing.nav.about")}
          </a>
          <span className="[&_button]:text-ln-canvas/70 [&_button:hover]:bg-ln-canvas/10 [&_button:hover]:text-ln-canvas">
            <LanguageSwitcher />
          </span>
          {/* Below md the four links are hidden and this is the only way into
              the page: without it a phone visitor cannot reach Markets or
              About at all, which is what shipped in v0.69.0. */}
          <button
            type="button"
            onClick={onOpenMenu}
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            aria-controls="landing-menu"
            aria-label={t("landing.menu.open")}
            className="-mr-2 flex h-11 w-11 items-center justify-center text-ln-canvas md:hidden"
          >
            <Menu className="h-[22px] w-[22px]" strokeWidth={1} />
          </button>
        </nav>
      </div>
    </header>
  );
}

/**
 * The phone's navigation, from the design's 390 artboard.
 *
 * 🔴 It is rendered as a sibling of <main>, NOT inside the hero, and that is
 * not tidiness. `[data-pin-stage]` has `overflow-hidden`, and the engine's
 * sticky fallback sets `will-change: transform` on it the moment it fires —
 * either one makes the stage a containing block for `position: fixed`, so an
 * overlay nested in there would be cropped to the film instead of covering the
 * screen. deploy-v6 puts `#mob-menu` outside its page for the same reason.
 */
function MobileMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    // Whatever opened it gets the focus back when it closes — otherwise the
    // reader is returned to the top of the document with no idea where.
    const opener = document.activeElement as HTMLElement | null;
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    root.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      /* aria-modal tells a screen reader to ignore the page behind; it does
         nothing to the browser's tab order. Measured before this existed: the
         6th Tab left the overlay and the 9th landed in the consult form's name
         field, invisible behind a full-screen panel. */
      const panel = dialogRef.current;
      if (!panel) return;
      const items = Array.from(
        panel.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"),
      ).filter((el) => el.offsetParent !== null);
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const outside = !active || !panel.contains(active);
      if (e.shiftKey ? active === first || outside : active === last || outside) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      }
    };
    // Resizing to a desktop width hides the overlay by CSS; without this the
    // page would stay locked behind an overlay nobody can see.
    const wide = matchMedia("(min-width: 768px)");
    const onWide = () => {
      if (wide.matches) onClose();
    };
    document.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => {
      document.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
      root.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const items = [
    { href: "#about", label: t("landing.menu.about"), italic: false },
    { href: "#how", label: t("landing.menu.how"), italic: false },
    { href: "#markets", label: t("landing.menu.markets"), italic: false },
    { href: "#consult", label: t("landing.nav.book"), italic: true },
  ];

  return (
    <div
      ref={dialogRef}
      id="landing-menu"
      role="dialog"
      aria-modal="true"
      aria-label={t("landing.menu.title")}
      className="fixed inset-0 z-50 flex flex-col bg-ln-night px-[22px] pb-[calc(30px+env(safe-area-inset-bottom,0px))] pt-[calc(14px+env(safe-area-inset-top,0px))] text-ln-canvas md:hidden"
    >
      <div className="-mr-2 flex items-start justify-between">
        <div className="min-w-0">
          {LANDING.advisors && (
            <p className="truncate font-ln-serif text-[19px] font-light leading-none tracking-[0.05em]">
              {LANDING.advisors}
            </p>
          )}
          {LANDING.brokerage && (
            <p className="mt-1 truncate text-[7px] font-medium uppercase tracking-[0.28em] text-ln-canvas/60">
              {LANDING.brokerage}
            </p>
          )}
        </div>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label={t("landing.menu.close")}
          className="flex h-11 w-11 flex-none items-center justify-center text-ln-canvas"
        >
          <X className="h-[22px] w-[22px]" strokeWidth={1} />
        </button>
      </div>

      <nav className="my-auto flex flex-col">
        {items.map(({ href, label, italic }, i) => (
          <a
            key={href}
            href={href}
            onClick={onClose}
            data-menu-link="1"
            className="flex items-baseline justify-between border-t border-ln-canvas/15 py-[18px] font-ln-serif text-[40px] font-light leading-none text-ln-cream last:border-b"
          >
            <span className={italic ? "italic" : undefined}>{label}</span>
            <span className="font-ln-sans text-[10px] uppercase tracking-[0.22em] text-ln-canvas/50">
              {String(i + 1).padStart(2, "0")}
            </span>
          </a>
        ))}
      </nav>

      {LANDING.phone && (
        <a
          href={`tel:${dialable(LANDING.phone)}`}
          onClick={onClose}
          data-menu-link="1"
          className="flex items-center justify-center gap-2.5 rounded-full bg-ln-canvas px-6 py-[18px] text-[11px] font-medium uppercase tracking-[0.16em] text-[#242219]"
        >
          <Phone className="h-3.5 w-3.5" />
          {LANDING.advisors
            ? t("landing.menu.call", { who: LANDING.advisors })
            : t("landing.menu.callPlain")}
        </a>
      )}
    </div>
  );
}

/**
 * The scroll-driven film. The host is several viewports tall and its stage is
 * sticky, so the page keeps scrolling while the frame stays put; the engine
 * turns that scroll into the clip's playhead and into which caption is up.
 *
 * Heights: the design's artboards are 4400/900 (desktop) and 2900/720 (phone)
 * — host over stage — i.e. 4.9 and 4.0 viewports. BOTH are in `svh`, which is
 * the stable one: `dvh` tracks the live viewport, so on iOS the film would
 * resize under the reader every time the Safari toolbar folds or unfolds
 * mid-scroll, and the progress denominator would move with it. deploy-v6 says
 * this in as many words and pins its stage to a measured height that it only
 * re-reads on a width change or a jump over 160px. The cost of `svh` is the
 * mirror image and much smaller: with the toolbar collapsed the stage is a
 * strip shorter than the viewport, and that strip is the host's own night.
 * Not measurable from a Mac — decided, and listed as undecided-by-measurement.
 *
 * Caption windows are the design's, as fractions of that scroll: 0–.22 the
 * opening, .27–.49 who we are, .53–.75 how we work, .79–1 the consult with its
 * buttons. Only the first is visible before the engine runs (and with JS off);
 * the others start `opacity-0 invisible pointer-events-none` so the four never
 * stack on the first paint and no invisible button takes a click or a Tab.
 * `lib/__tests__/landingHero.test.ts` pins that, and the video's missing
 * `autoPlay`/`loop`: either would come back silently and undo the engine.
 */
function Hero({ menuOpen, onOpenMenu }: { menuOpen: boolean; onOpenMenu: () => void }) {
  const { t } = useI18n();
  const eyebrow =
    "mb-4 text-[9px] font-medium uppercase tracking-[0.26em] text-ln-canvas/70 md:mb-6 md:text-[10px] md:tracking-[0.32em]";
  const title = "font-ln-serif font-light text-ln-cream [text-wrap:pretty]";
  const body = "text-[15px] leading-[1.7] text-ln-canvas/85 md:text-[17px] md:leading-[1.75]";
  const aside =
    "invisible pointer-events-none absolute inset-x-5 bottom-[70px] z-[3] opacity-0 will-change-[opacity,transform] md:inset-x-auto md:bottom-[110px] md:max-w-[660px]";
  const asideTitle = `${title} mb-3.5 text-[46px] leading-[0.98] tracking-[-0.02em] md:mb-[22px] md:text-[64px] md:leading-[0.96] lg:text-[84px]`;

  return (
    <section data-pin-host="1" className="relative h-[400svh] bg-ln-night md:h-[490svh]">
      <div data-pin-stage="1" className="sticky top-0 h-svh overflow-hidden bg-ln-night">
        {/* No autoPlay, no loop: the engine primes it and then owns the
            playhead, and the clip cannot loop (see LandingEffects).
            `preload` stays "auto" and NOT the design's "none" + data-src:
            measured on this build, that swap moved the clip's bytes before the
            poster finished from 11,254 to 0 — 11KB of 17.8MB, with the poster
            landing at the same 2.1s. A 11KB claim is not an optimisation. */}
        <video
          data-hero-video="1"
          muted
          playsInline
          preload="auto"
          poster="/landing/hero-poster.jpg"
          className="absolute inset-0 h-full w-full object-cover"
        >
          <source src="/landing/casa-hero.mp4" type="video/mp4" />
        </video>
        <div className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-40 bg-gradient-to-b from-ln-night/60 to-transparent md:h-[220px]" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-[260px] bg-gradient-to-t from-ln-night/75 to-transparent md:h-[320px]" />

        <LandingNav menuOpen={menuOpen} onOpenMenu={onOpenMenu} />

        <div
          data-cap="0,0.22"
          className="absolute inset-0 z-[3] flex flex-col items-center justify-center px-5 text-center will-change-[opacity,transform] md:px-14"
        >
          <p className={`${eyebrow} md:mb-[30px]`}>{t("landing.hero.kicker")}</p>
          <h1
            className={`${title} mb-4 text-[50px] leading-[0.96] tracking-[-0.02em] [text-shadow:0_2px_40px_rgba(0,0,0,0.35)] sm:text-[80px] md:mb-[22px] md:leading-[0.92] md:tracking-[-0.025em] lg:text-[96px] xl:text-[118px]`}
          >
            {t("landing.hero.titleLine1")}
            <br />
            {t("landing.hero.titleLine2")} <span className="italic">{t("landing.hero.titleItalic")}</span>.
          </h1>
          <p className={`${body} max-w-[310px] md:max-w-[600px]`}>{t("landing.hero.body")}</p>
        </div>

        <div data-cap="0.27,0.49" className={`${aside} md:left-14`}>
          <p className={eyebrow}>{t("landing.hero.who.eyebrow")}</p>
          <h2 className={asideTitle}>
            {t("landing.hero.who.titleA")}
            <br />
            <span className="italic">{t("landing.hero.who.titleItalic")}</span>.
          </h2>
          <p className={`${body} md:max-w-[520px]`}>{t("landing.hero.who.body")}</p>
        </div>

        <div data-cap="0.53,0.75" className={`${aside} md:right-14`}>
          <p className={eyebrow}>{t("landing.how.eyebrow")}</p>
          <h2 className={asideTitle}>
            {t("landing.hero.price.titleA")}
            <br />
            <span className="italic">{t("landing.hero.price.titleItalic")}</span>.
          </h2>
          <p className={`${body} md:max-w-[520px]`}>{t("landing.hero.price.body")}</p>
        </div>

        <div
          data-cap="0.79,1"
          className="invisible pointer-events-none absolute inset-0 z-[3] flex flex-col items-center justify-center px-5 text-center opacity-0 will-change-[opacity,transform] md:px-14"
        >
          <p className={eyebrow}>{t("landing.hero.talk.eyebrow")}</p>
          <h2
            className={`${title} mb-4 text-[50px] leading-[0.96] tracking-[-0.02em] md:mb-6 md:text-[76px] md:leading-[0.94] md:tracking-[-0.025em] lg:text-[96px]`}
          >
            {t("landing.consult.titleA")}
            <br />
            <span className="italic">{t("landing.consult.titleItalic")}</span>.
          </h2>
          <p className={`${body} mb-[26px] max-w-[310px] md:mb-9 md:max-w-[560px]`}>
            {t("landing.consult.body")}
          </p>
          <div className="flex w-full max-w-[360px] flex-col gap-2.5 md:w-auto md:max-w-none md:flex-row md:gap-3.5">
            <a
              href="#consult"
              className="inline-flex min-h-[52px] items-center justify-center gap-3 rounded-full bg-ln-canvas px-8 py-4 text-[11px] font-medium uppercase tracking-[0.16em] text-[#242219] hover:opacity-90"
            >
              <CalendarCheck className="h-3.5 w-3.5" />
              {t("landing.hero.cta")}
            </a>
            {LANDING.phone && (
              <a
                href={`tel:${dialable(LANDING.phone)}`}
                className="inline-flex min-h-[52px] items-center justify-center gap-3 rounded-full border border-ln-canvas/45 bg-ln-night/35 px-8 py-4 text-[11px] font-medium uppercase tracking-[0.16em] text-ln-canvas backdrop-blur hover:border-ln-canvas"
              >
                <Phone className="h-3.5 w-3.5" />
                {t("landing.hero.callUs")}
              </a>
            )}
          </div>
        </div>

        <div
          data-cap="0,0.14"
          className="absolute bottom-[30px] left-14 z-[4] hidden items-center gap-2.5 text-[10px] uppercase tracking-[0.22em] text-ln-canvas/60 md:flex"
        >
          <ArrowDown className="h-[13px] w-[13px]" />
          {t("landing.hero.scroll")}
        </div>
        <div className="absolute inset-x-5 bottom-0 z-[4] h-px bg-ln-canvas/20 md:inset-x-14">
          <div data-pin-bar="1" className="h-full w-0 bg-ln-canvas" />
        </div>
      </div>
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
        <div data-reveal="up" data-drift="44" className="flex flex-col justify-center px-5 py-16 sm:px-10 lg:px-14 lg:py-28">
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
        <div data-reveal="clip" className="relative min-h-[420px] overflow-hidden bg-ln-tint lg:min-h-[720px]">
          {/* 0.10, not the design's 0.14: the engine zooms by 1+amt*1.1 to
              cover its own translate, and at 0.14 that zoom plus the cover
              crop ate the top of the photo — Robbie's forehead, specifically.
              The object-position anchors the crop near the top of the frame
              for the same reason. */}
          <div data-parallax="0.10" className="absolute inset-0">
            {/* eslint-disable-next-line @next/next/no-img-element -- the page
                uses plain <img> throughout: `sharp` is not installed, so
                next/image would optimise nothing and only add a dependency. */}
            <img
              src="/landing/natalia-robbie.jpg"
              alt={LANDING.advisors || ""}
              loading="lazy"
              decoding="async"
              className="absolute inset-0 h-full w-full object-cover [object-position:50%_12%]"
            />
          </div>
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
        <div data-reveal="up" data-drift="34" className="mb-14 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between lg:gap-16">
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
            <article key={title} data-reveal="up" className="border-t border-ln-line-strong pt-6">
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
      <div className="pt-16 lg:pt-28">
        <div
          data-reveal="up"
          data-drift="34"
          className="mb-12 flex items-end justify-between gap-8 px-5 sm:px-10 lg:px-14"
        >
          <div>
            <Eyebrow>{t("landing.markets.eyebrow")}</Eyebrow>
            <div className="mt-6">
              <SplitTitle a={t("landing.markets.titleA")} italic={t("landing.markets.titleItalic")} />
            </div>
          </div>
          <div className="hidden items-center gap-4 text-ln-muted md:flex">
            <span className="whitespace-nowrap text-[10px] uppercase tracking-[0.22em]">
              {t("landing.markets.drag")}
            </span>
            <ArrowRight className="h-4 w-4" />
          </div>
        </div>
        {/* The design's rail: horizontal, draggable (the engine wires the
            grab), scrollbar hidden in globals.css. On a phone the native
            swipe IS the rail. */}
        <div
          data-rail="1"
          className="flex gap-5 overflow-x-auto overflow-y-hidden px-5 pb-16 sm:px-10 lg:px-14 lg:pb-28"
        >
          {markets.map(({ key, src }, i) => (
            <article key={key} data-reveal="up" className="w-[290px] flex-none sm:w-[400px]">
              <div className="relative aspect-[4/5] overflow-hidden bg-ln-tint">
                {/* The design's card parallax (0.10): the image box is taller
                    than the frame and starts above it, so the translate has
                    room on both sides and object-cover never shows an edge.
                    The aspect-* class reserves the frame, so nothing reflows
                    while the landscape files load. */}
                <div data-parallax="0.10" className="absolute inset-x-0 -top-[8%] h-[117%]">
                  {/* eslint-disable-next-line @next/next/no-img-element -- see
                      the portrait note. */}
                  <img
                    src={src}
                    alt=""
                    loading={i === 0 ? "eager" : "lazy"}
                    decoding="async"
                    className="h-full w-full object-cover"
                  />
                </div>
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
          <div className="flex h-[363px] w-[150px] flex-none items-center justify-center border border-ln-hair sm:h-[500px]">
            <span className="text-[10px] uppercase tracking-[0.22em] text-ln-faint">
              {t("landing.markets.more")}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function Consult() {
  const { t } = useI18n();
  return (
    <section id="consult" className="relative scroll-mt-10 overflow-hidden bg-ln-dark">
      <div data-parallax="0.24" className="absolute inset-0">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/landing/cta-bg.jpg"
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
        />
      </div>
      <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(20,18,14,0.88)_0%,rgba(20,18,14,0.76)_46%,rgba(20,18,14,0.6)_100%)]" />
      <div data-reveal="up" data-drift="30" className="relative grid items-center gap-14 px-5 py-20 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-24 lg:px-14 lg:py-32">
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

/* lucide-react carries no brand marks, so these are the design's own outlines.
   They are decorative — the link's aria-label names the destination — and they
   live inside a component rather than in a module constant: JSX evaluated at
   module scope needs React in scope and blows up the moment another module
   merely imports this file. */
function SocialGlyph({ name }: { name: string }) {
  const paths =
    name === "instagram" ? (
      <>
        <rect x="2" y="2" width="20" height="20" rx="5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="17.5" cy="6.5" r="0.6" fill="currentColor" />
      </>
    ) : name === "youtube" ? (
      <>
        <path d="M2.5 12c0-3 .3-4.6.6-5.3a2.6 2.6 0 0 1 1.8-1.5C6.5 4.8 12 4.8 12 4.8s5.5 0 7.1.4a2.6 2.6 0 0 1 1.8 1.5c.3.7.6 2.3.6 5.3s-.3 4.6-.6 5.3a2.6 2.6 0 0 1-1.8 1.5c-1.6.4-7.1.4-7.1.4s-5.5 0-7.1-.4a2.6 2.6 0 0 1-1.8-1.5c-.3-.7-.6-2.3-.6-5.3z" />
        <path d="M10 9.5v5l4.5-2.5z" fill="currentColor" />
      </>
    ) : (
      <path d="M9 12a4 4 0 1 0 4 4V4a5 5 0 0 0 5 5" />
    );
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths}
    </svg>
  );
}

const SOCIAL_NAME: Record<string, string> = {
  instagram: "Instagram",
  youtube: "YouTube",
  tiktok: "TikTok",
};

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
        <div className="flex items-center gap-6">
          {/* The videos send people here; this is the way back. Each icon
              exists only if its URL was configured — an empty row of dead
              circles would be worse than no row. Privacy and Terms, which the
              design also lists, are deliberately NOT here: those pages do not
              exist, and this page does not link to anything that is not there. */}
          {LANDING.socials.length > 0 && (
            <div className="flex items-center gap-2.5">
              {LANDING.socials.map(({ key, url }) => (
                <a
                  key={key}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={SOCIAL_NAME[key]}
                  className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-ln-hair text-ln-body hover:border-ln-gold hover:text-ln-gold"
                >
                  <SocialGlyph name={key} />
                </a>
              ))}
            </div>
          )}
          {/* inline-flex + min-height so the tap target reaches 44px on a
              phone. As a bare inline link it measured 15px. */}
          <Link
            href="/login"
            className="inline-flex min-h-[44px] items-center whitespace-nowrap text-[11px] tracking-[0.04em] text-ln-muted underline underline-offset-4 hover:text-ln-gold"
          >
            {t("landing.footer.staffLogin")}
          </Link>
        </div>
      </div>
    </footer>
  );
}

export function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  return (
    // `eko-landing` is the hook globals.css uses to repaint the document
    // background: the app shell is dark, and without it the overscroll gutter
    // bounces black behind a cream page.
    <div className="eko-landing relative min-h-screen bg-ln-canvas font-ln-sans text-ln-ink antialiased">
      <LandingEffects />
      <main>
        <Hero menuOpen={menuOpen} onOpenMenu={() => setMenuOpen(true)} />
        <TwoOfUs />
        <HowWeWork />
        <Markets />
        <Consult />
      </main>
      <LandingFooter />
      <MobileMenu open={menuOpen} onClose={closeMenu} />
    </div>
  );
}
