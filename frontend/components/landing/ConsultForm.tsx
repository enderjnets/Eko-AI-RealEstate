"use client";

/**
 * The landing's only conversion point: a stranger asks for the fifteen-minute
 * consult. It posts through the same public capture path as /contact — same
 * endpoint, same honeypot, same Turnstile, same one-source consent wording —
 * because a second, subtly different capture form is how a TCPA record ends up
 * saying something the visitor never read.
 *
 * `form` is NOT a label for this page — it is the tenant key the backend looks
 * up in `channel_routes`, and a key that is supplied but unregistered is
 * refused with a 404. So the landing sends the install's own capture key, the
 * same one /contact sends: both forms belong to the same agency. Which page a
 * lead came from is attribution, and rides in `landing_variant` instead.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { submitPublicLead, type CaptureOutcome } from "@/lib/api";
import { collectAttribution } from "@/lib/capture";
import { getTracker, sessionKey, storedAttribution } from "@/lib/track";
import { useI18n } from "@/lib/i18n";
import { ArrowRight } from "lucide-react";
import { Turnstile, TURNSTILE_SITE_KEY } from "@/components/ui/Turnstile";

const FORM_KEY = process.env.NEXT_PUBLIC_CAPTURE_FORM_KEY || undefined;

/**
 * Whitelisted attribution key; marks the lead as having come from this page.
 *
 * The DEFAULT, not the only value. `/fall` renders this same form and passes
 * its own variant, which is the whole reason the form takes a prop instead of
 * being copied: the consent wording rendered beside the checkbox is the wording
 * stored as evidence, and a second capture form is how that record ends up
 * describing a sentence the visitor never read. One form, one consent string,
 * one endpoint — only the attribution differs.
 */
const LANDING_VARIANT = "landing";

type Goal = "selling" | "buying" | "valuing";

function ConsultFormInner({ variant }: { variant: string }) {
  const { t } = useI18n();
  const params = useSearchParams();

  const [f, setF] = useState({ name: "", phone: "", email: "", website: "" });
  const [goal, setGoal] = useState<Goal | null>(null);
  const [consent, setConsent] = useState(false);
  const [utm, setUtm] = useState<Record<string, string>>({});
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [started, setStarted] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let storage: Storage | null = null;
    try {
      storage = window.sessionStorage;
    } catch {
      storage = null;
    }
    const collected = collectAttribution(params, document.referrer);
    // What the tracker remembered when the visit started wins over an empty
    // URL: somebody who landed on `/?utm_source=tiktok`, read three sections
    // and scrolled down here still came from TikTok. A UTM in the CURRENT url
    // is more specific still, so it goes last.
    setUtm({
      landing_variant: variant,
      ...storedAttribution(storage),
      ...collected,
    });
    setSessionId(sessionKey(storage));
  }, [params, variant]);

  // The moment somebody starts filling this in — once, on the first field they
  // touch. It is the funnel step between "read the page" and "sent it", and
  // without it an abandoned form is indistinguishable from a visitor who never
  // looked at it.
  const onFirstTouch = () => {
    if (started) return;
    setStarted(true);
    getTracker()?.record("form_start");
  };

  const set =
    (k: "name" | "phone" | "email" | "website") =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setF((p) => ({ ...p, [k]: e.target.value }));

  // The wording rendered beside the checkbox is the wording stored as evidence.
  const consentWording = t("contact.consent");

  // Each chip carries the sentence it becomes. The chip label is a fragment
  // meant to be read under "I'm…", so sending it as the message produced
  // "I'm… Selling" in the inbox — which tells the advisor nothing and reads
  // like a bug to the person who has to answer it.
  const goals: { id: Goal; label: string; message: string }[] = [
    {
      id: "selling",
      label: t("landing.form.selling"),
      message: t("landing.form.msgSelling"),
    },
    {
      id: "buying",
      label: t("landing.form.buying"),
      message: t("landing.form.msgBuying"),
    },
    {
      id: "valuing",
      label: t("landing.form.valuing"),
      message: t("landing.form.msgValuing"),
    },
  ];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!f.email.trim() && !f.phone.trim()) {
      setError(t("contact.errorContact"));
      return;
    }
    if (TURNSTILE_SITE_KEY && !captchaToken) {
      setError(t("contact.errorCaptchaPending"));
      return;
    }
    setLoading(true);
    setError(null);

    // The chip is the only thing the visitor tells us about intent, so it is
    // sent as a sentence — it becomes the first message in the thread the
    // advisor opens, and the classifier reads it too.
    const message = goals.find((g) => g.id === goal)?.message;

    const outcome: CaptureOutcome = await submitPublicLead({
      form: FORM_KEY,
      name: f.name.trim() || undefined,
      email: f.email.trim() || undefined,
      phone: f.phone.trim() || undefined,
      message,
      consent,
      consent_text: consent ? consentWording : undefined,
      utm,
      session_id: sessionId,
      turnstile_token: captchaToken || undefined,
      website: f.website || undefined,
    });

    setLoading(false);
    if (outcome.ok) {
      // Recorded on the page as well as by the server's own link, because the
      // two disagreeing is the interesting case: a submission the server never
      // saw — a captcha refusal, a dropped connection — is invisible if only
      // the successful path writes it.
      getTracker()?.record("form_submit");
      setDone(true);
      return;
    }
    getTracker()?.record("form_error", { reason: outcome.reason || "generic" });
    // A Turnstile token is single-use; whatever failed, this one is spent.
    setCaptchaToken(null);
    setError(
      outcome.reason === "contact"
        ? t("contact.errorContact")
        : outcome.reason === "email"
          ? t("contact.errorEmail")
          : outcome.reason === "rate"
            ? t("contact.errorRate")
            : outcome.reason === "captcha"
              ? t("contact.errorCaptcha")
              : t("contact.errorGeneric"),
    );
  }

  if (done) {
    return (
      <div className="border border-ln-cream/25 bg-ln-dark/40 p-8 text-center backdrop-blur sm:p-10">
        <h3 className="font-ln-serif text-2xl text-ln-cream">{t("landing.form.thanksTitle")}</h3>
        <p className="mt-3 text-sm leading-relaxed text-ln-canvas/70">{t("landing.form.thanksBody")}</p>
      </div>
    );
  }

  return (
    // `onFocusCapture` on the form rather than a prop threaded through every
    // field: it catches the first input, the checkbox and anything added
    // later, and cannot be forgotten on a new field. The chips get an explicit
    // call because a button tap does not focus on iOS, so relying on focus
    // alone would under-report exactly the device most of this traffic uses.
    <form onSubmit={handleSubmit} onFocusCapture={onFirstTouch}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <LandingField
            id="ln-name"
            label={t("landing.form.name")}
            value={f.name}
            onChange={set("name")}
            autoComplete="given-name"
          />
          <LandingField
            id="ln-phone"
            label={t("landing.form.phone")}
            type="tel"
            value={f.phone}
            onChange={set("phone")}
            autoComplete="tel"
          />
        </div>
        {/* Required in the markup too: the backend refuses a lead without an
            address while SMS is parked (CAPTURE_REQUIRE_EMAIL), and the
            browser saying so first beats a round-trip to learn the same. */}
        <LandingField
          id="ln-email"
          label={t("landing.form.email")}
          type="email"
          value={f.email}
          onChange={set("email")}
          autoComplete="email"
          required
        />

        <fieldset>
          <legend className="text-[11px] uppercase tracking-[0.14em] text-ln-canvas/55">
            {t("landing.form.goal")}
          </legend>
          <div className="mt-3 flex flex-wrap gap-2">
            {goals.map((g) => {
              const active = goal === g.id;
              return (
                <button
                  key={g.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    onFirstTouch();
                    setGoal(active ? null : g.id);
                  }}
                  // 44px floor: below it a thumb misses on a phone, and a
                  // phone is where this page is read.
                  className={`min-h-[44px] px-[18px] text-[10px] uppercase tracking-[0.14em] transition-colors ${
                    active
                      ? "bg-ln-canvas text-ln-ink"
                      : "border border-ln-cream/35 text-ln-canvas/80 hover:border-ln-cream/70 hover:text-ln-cream"
                  }`}
                >
                  {g.label}
                </button>
              );
            })}
          </div>
        </fieldset>

        {/* Honeypot: offscreen for people, irresistible to a form-filling bot. */}
        <div className="absolute left-[-9999px]" aria-hidden="true">
          <label htmlFor="ln-website">Website</label>
          <input
            id="ln-website"
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={f.website}
            onChange={set("website")}
          />
        </div>

        <label className="flex items-start gap-3 pt-1 text-sm text-ln-canvas/70">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1 h-4 w-4 flex-none border-ln-cream/40 accent-ln-gold"
          />
          <span className="leading-relaxed">{consentWording}</span>
        </label>
        <p className="text-xs text-ln-canvas/50">{t("contact.consentHint")}</p>

        <Turnstile
          onToken={setCaptchaToken}
          onError={() => setError(t("contact.errorCaptcha"))}
        />

        {/* role=alert so a screen reader hears the refusal; without it the
            form appears to have done nothing at all. */}
        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="flex w-full items-center justify-center gap-3 bg-ln-gold px-6 py-5 text-[11px] font-medium uppercase tracking-[0.16em] text-ln-cream transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {loading ? t("landing.form.sending") : t("landing.form.submit")}
          <ArrowRight className="h-[15px] w-[15px]" />
        </button>
        <p className="text-center text-[11px] tracking-[0.06em] text-ln-canvas/55">
          {t("landing.form.reassure")}
        </p>
      </div>
    </form>
  );
}

function LandingField({
  id,
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  autoComplete?: string;
  required?: boolean;
}) {
  // The design draws inputs as underlined rules on the dark panel; the label
  // rides inside as a placeholder would, but stays a real <label> for a11y.
  return (
    <div>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        required={required}
        placeholder={label}
        className="h-12 w-full border-b border-ln-cream/35 bg-transparent text-[14px] text-ln-cream outline-none placeholder:text-ln-canvas/55 focus:border-ln-cream/80"
      />
    </div>
  );
}

export function ConsultForm({ variant = LANDING_VARIANT }: { variant?: string } = {}) {
  // useSearchParams needs a Suspense boundary or the whole route opts out of
  // static rendering.
  return (
    <Suspense fallback={<div className="h-96 border border-ln-cream/20" />}>
      <ConsultFormInner variant={variant} />
    </Suspense>
  );
}
