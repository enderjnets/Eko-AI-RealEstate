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
import { useI18n } from "@/lib/i18n";
import { Turnstile, TURNSTILE_SITE_KEY } from "@/components/ui/Turnstile";

const FORM_KEY = process.env.NEXT_PUBLIC_CAPTURE_FORM_KEY || undefined;

/** Whitelisted attribution key; marks the lead as having come from this page. */
const LANDING_VARIANT = "landing";

type Goal = "selling" | "buying" | "valuing";

function ConsultFormInner() {
  const { t } = useI18n();
  const params = useSearchParams();

  const [f, setF] = useState({ name: "", phone: "", email: "", website: "" });
  const [goal, setGoal] = useState<Goal | null>(null);
  const [consent, setConsent] = useState(false);
  const [utm, setUtm] = useState<Record<string, string>>({});
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const collected = collectAttribution(
      params,
      typeof document !== "undefined" ? document.referrer : null,
    );
    // A variant named in the URL is more specific than "it was the landing",
    // so it wins; otherwise this page identifies itself.
    setUtm({ landing_variant: LANDING_VARIANT, ...collected });
  }, [params]);

  const set =
    (k: "name" | "phone" | "email" | "website") =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setF((p) => ({ ...p, [k]: e.target.value }));

  // The wording rendered beside the checkbox is the wording stored as evidence.
  const consentWording = t("contact.consent");

  const goals: { id: Goal; label: string }[] = [
    { id: "selling", label: t("landing.form.selling") },
    { id: "buying", label: t("landing.form.buying") },
    { id: "valuing", label: t("landing.form.valuing") },
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
    // sent as a sentence the classifier can read rather than a bare token.
    const goalLabel = goals.find((g) => g.id === goal)?.label;
    const message = goalLabel ? `${t("landing.form.goal")} ${goalLabel}` : undefined;

    const outcome: CaptureOutcome = await submitPublicLead({
      form: FORM_KEY,
      name: f.name.trim() || undefined,
      email: f.email.trim() || undefined,
      phone: f.phone.trim() || undefined,
      message,
      consent,
      consent_text: consent ? consentWording : undefined,
      utm,
      turnstile_token: captchaToken || undefined,
      website: f.website || undefined,
    });

    setLoading(false);
    if (outcome.ok) {
      setDone(true);
      return;
    }
    // A Turnstile token is single-use; whatever failed, this one is spent.
    setCaptchaToken(null);
    setError(
      outcome.reason === "contact"
        ? t("contact.errorContact")
        : outcome.reason === "rate"
          ? t("contact.errorRate")
          : outcome.reason === "captcha"
            ? t("contact.errorCaptcha")
            : t("contact.errorGeneric"),
    );
  }

  if (done) {
    return (
      <div className="border border-ln-line bg-ln-paper p-8 text-center sm:p-10">
        <h3 className="font-ln-serif text-2xl text-ln-ink">{t("landing.form.thanksTitle")}</h3>
        <p className="mt-3 text-sm leading-relaxed text-ln-body">{t("landing.form.thanksBody")}</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="border border-ln-line bg-ln-paper p-6 sm:p-8">
      <div className="space-y-4">
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
        <LandingField
          id="ln-email"
          label={t("landing.form.email")}
          type="email"
          value={f.email}
          onChange={set("email")}
          autoComplete="email"
        />

        <fieldset>
          <legend className="text-[11px] uppercase tracking-[0.14em] text-ln-muted">
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
                  onClick={() => setGoal(active ? null : g.id)}
                  // 44px floor: below it a thumb misses on a phone, and a
                  // phone is where this page is read.
                  className={`min-h-[44px] px-4 text-[11px] uppercase tracking-[0.08em] transition-colors ${
                    active
                      ? "bg-ln-ink text-ln-paper"
                      : "border border-ln-line-strong text-ln-body hover:border-ln-bronze hover:text-ln-bronze"
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

        <label className="flex items-start gap-3 pt-1 text-sm text-ln-body">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1 h-4 w-4 flex-none border-ln-line-strong accent-ln-bronze"
          />
          <span className="leading-relaxed">{consentWording}</span>
        </label>
        <p className="text-xs text-ln-faint">{t("contact.consentHint")}</p>

        <Turnstile
          onToken={setCaptchaToken}
          onError={() => setError(t("contact.errorCaptcha"))}
        />

        {error && <p className="text-sm text-red-700">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-ln-bronze px-6 py-4 text-[12px] uppercase tracking-[0.10em] text-ln-paper transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {loading ? t("landing.form.sending") : t("landing.form.submit")}
        </button>
        <p className="text-center text-[11px] tracking-[0.04em] text-ln-faint">
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
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  autoComplete?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-[11px] uppercase tracking-[0.14em] text-ln-muted"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        className="mt-2 h-12 w-full border border-ln-line-strong bg-transparent px-3 text-ln-ink outline-none focus:border-ln-bronze"
      />
    </div>
  );
}

export function ConsultForm() {
  // useSearchParams needs a Suspense boundary or the whole route opts out of
  // static rendering.
  return (
    <Suspense fallback={<div className="h-96 border border-ln-line bg-ln-paper" />}>
      <ConsultFormInner />
    </Suspense>
  );
}
