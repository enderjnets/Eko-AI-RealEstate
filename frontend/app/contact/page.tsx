"use client";

/**
 * The landing-page capture form — the only page here a stranger is meant to
 * reach. It is what turns someone who watched a video into a lead in the
 * Inbox, and it carries the UTM parameters that later answer which video did
 * it.
 *
 * Two things in here are load-bearing rather than decorative:
 *
 * The consent checkbox sends the SAME string it renders. TCPA asks what the
 * person was looking at when they agreed, so the disclosure is read out of the
 * translation table once and both shown and submitted from that one value — a
 * second copy in the backend would drift from the page the day someone edits
 * the wording, and the stored "proof" would be of a sentence nobody saw.
 *
 * The honeypot is a real input, positioned off-screen rather than
 * `display:none`, because the crudest bots skip hidden fields but fill in
 * anything that looks like an address field.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { submitPublicLead, type CaptureOutcome } from "@/lib/api";
import { collectAttribution } from "@/lib/capture";
import { useI18n } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { TURNSTILE_SITE_KEY, Turnstile } from "@/components/ui/Turnstile";

const FORM_KEY = process.env.NEXT_PUBLIC_CAPTURE_FORM_KEY || undefined;

function ContactForm() {
  const { t } = useI18n();
  const params = useSearchParams();

  const [f, setF] = useState({
    name: "",
    email: "",
    phone: "",
    message: "",
    website: "", // honeypot
  });
  const [consent, setConsent] = useState(false);
  const [utm, setUtm] = useState<Record<string, string>>({});
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Read once on mount, through the pure helper so the rule that decides
    // which video gets credited for a lead is testable on its own.
    setUtm(
      collectAttribution(
        params,
        typeof document !== "undefined" ? document.referrer : null,
      ),
    );
  }, [params]);

  const set =
    (k: keyof typeof f) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setF((p) => ({ ...p, [k]: e.target.value }));

  // The exact wording rendered below, and the exact wording submitted. One
  // source, deliberately.
  const consentWording = t("contact.consent");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    if (!f.email.trim() && !f.phone.trim()) {
      setError(t("contact.errorContact"));
      return;
    }
    if (TURNSTILE_SITE_KEY && !captchaToken) {
      // The server would answer 400 and the visitor would read "we couldn't
      // verify that you're human" without ever having been shown a challenge
      // to fail.
      setError(t("contact.errorCaptchaPending"));
      return;
    }
    setLoading(true);
    setError(null);

    const outcome: CaptureOutcome = await submitPublicLead({
      form: FORM_KEY,
      name: f.name.trim() || undefined,
      email: f.email.trim() || undefined,
      phone: f.phone.trim() || undefined,
      message: f.message.trim() || undefined,
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
    // A Turnstile token is single-use. Whatever went wrong, the one in hand is
    // spent, so drop it and let the widget issue another.
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
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-gray-800 dark:bg-gray-950">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-50">
          {t("contact.thanksTitle")}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
          {t("contact.thanksBody")}
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-800 dark:bg-gray-950"
    >
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-50">
        {t("contact.title")}
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        {t("contact.subtitle")}
      </p>

      <div className="mt-6 space-y-4">
        <Field
          id="name"
          label={t("contact.name")}
          value={f.name}
          onChange={set("name")}
          autoComplete="name"
        />
        <Field
          id="email"
          label={t("contact.email")}
          type="email"
          value={f.email}
          onChange={set("email")}
          autoComplete="email"
        />
        <Field
          id="phone"
          label={t("contact.phone")}
          type="tel"
          value={f.phone}
          onChange={set("phone")}
          autoComplete="tel"
        />
        <p className="text-xs text-gray-500 dark:text-gray-500">
          {t("contact.contactHint")}
        </p>

        <div>
          <label
            htmlFor="message"
            className="block text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            {t("contact.message")}
          </label>
          <textarea
            id="message"
            rows={4}
            value={f.message}
            onChange={set("message")}
            placeholder={t("contact.messagePlaceholder")}
            maxLength={5000}
            className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-gray-400"
          />
        </div>

        {/* Honeypot. Off-screen rather than hidden, and never focusable or
            announced, so a screen reader user cannot land in it by accident. */}
        <div aria-hidden="true" className="absolute left-[-9999px] top-auto h-px w-px overflow-hidden">
          <label htmlFor="website">Website</label>
          <input
            id="website"
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={f.website}
            onChange={set("website")}
          />
        </div>

        <label className="flex items-start gap-3 text-sm text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1 h-4 w-4 shrink-0 rounded border-gray-300 dark:border-gray-700"
          />
          <span className="leading-relaxed">{consentWording}</span>
        </label>
        <p className="text-xs text-gray-500 dark:text-gray-500">
          {t("contact.consentHint")}
        </p>

        <Turnstile
          onToken={setCaptchaToken}
          onError={() => setError(t("contact.errorCaptcha"))}
        />

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
        >
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          {loading ? t("contact.sending") : t("contact.submit")}
        </button>
      </div>
    </form>
  );
}

function Field({
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
        className="block text-sm font-medium text-gray-700 dark:text-gray-300"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-gray-400"
      />
    </div>
  );
}

export default function ContactPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-gray-50 px-4 py-12 dark:bg-black">
      {/* useSearchParams needs a Suspense boundary or the whole route opts out
          of static rendering and the build warns. */}
      <Suspense fallback={<Loader2 className="h-5 w-5 animate-spin text-gray-400" />}>
        <ContactForm />
      </Suspense>
      <LanguageSwitcher />
    </main>
  );
}
