"use client";

/**
 * Log a call in under a minute.
 *
 * That budget is the whole design. If marking a call takes longer than a
 * minute it does not get marked, and what does arrive is worse than nothing —
 * so this is taps, not typing: the outcome is one chip, what changed is
 * pre-filled from what the lead already says, and the advisor confirms or
 * corrects rather than transcribes. Everything else is optional and stays
 * folded away.
 *
 * Saving is not filing. Each outcome fires exactly one action on the server —
 * a follow-up queued, pending nudges cancelled, an opt-out recorded — so there
 * is no second screen to remember.
 */

import { useState } from "react";
import { Loader2, PhoneCall } from "lucide-react";
import {
  type CallIn,
  type CallOutcome,
  type Lead,
  type LeadIntent,
  type PreferredChannel,
  callsApi,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const OUTCOMES: CallOutcome[] = [
  "wants_listings",
  "booked_visit",
  "follow_up",
  "no_answer",
  "has_agent",
  "do_not_contact",
  "wrong_number",
];

/** Outcomes that mean stop. The panel says so before the advisor commits. */
const STAND_DOWN: CallOutcome[] = ["has_agent", "do_not_contact", "wrong_number"];

const FOLLOW_UP_DAYS = [1, 3, 7, 14, 30];

const INTENTS: LeadIntent[] = ["buy", "rent", "valuation"];
const URGENCIES = ["high", "medium", "low"] as const;
const CHANNELS: PreferredChannel[] = ["sms", "email", "call"];

export function CallPanel({
  lead,
  onLogged,
}: {
  lead: Lead;
  onLogged: () => void;
}) {
  const { t } = useI18n();

  const [outcome, setOutcome] = useState<CallOutcome | null>(null);
  const [intent, setIntent] = useState<LeadIntent | null>(null);
  const [urgency, setUrgency] = useState<string | null>(null);
  const [preferred, setPreferred] = useState<PreferredChannel | null>(null);
  const [zone, setZone] = useState("");
  const [budgetMax, setBudgetMax] = useState("");
  const [note, setNote] = useState("");
  const [askedForTexts, setAskedForTexts] = useState(false);
  const [followUpDays, setFollowUpDays] = useState<number | null>(null);

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const standDown = outcome !== null && STAND_DOWN.includes(outcome);

  function reset() {
    setOutcome(null);
    setIntent(null);
    setUrgency(null);
    setPreferred(null);
    setZone("");
    setBudgetMax("");
    setNote("");
    setAskedForTexts(false);
    setFollowUpDays(null);
  }

  async function save() {
    if (!outcome || saving) return;
    setSaving(true);
    setError(null);
    setSaved(null);

    // Only what the advisor actually touched is sent. An omitted field means
    // "did not come up" on the server and leaves the lead's value alone; a
    // blank one would wipe it.
    const body: CallIn = { outcome };
    if (intent) body.intent = intent;
    if (urgency) body.urgency = urgency;
    if (preferred) body.preferred_channel = preferred;
    if (zone.trim()) body.zone = zone.trim();
    if (budgetMax.trim() && Number.isFinite(Number(budgetMax))) {
      body.budget_max = Number(budgetMax);
    }
    if (note.trim()) body.note = note.trim();
    if (askedForTexts) body.asked_for_texts = true;
    // A stand-down outcome cancels rather than schedules; the server enforces
    // this too, but sending it would be a confusing thing to have asked for.
    if (followUpDays !== null && !standDown) body.follow_up_in_days = followUpDays;

    try {
      const result = await callsApi.log(lead.id, body);
      if (result.follow_up_scheduled_for) {
        setSaved(
          t("call.savedFollowUp").replace(
            "{date}",
            new Date(result.follow_up_scheduled_for).toLocaleDateString(),
          ),
        );
      } else if (result.cancelled_follow_ups > 0) {
        setSaved(
          t("call.savedCancelled").replace("{n}", String(result.cancelled_follow_ups)),
        );
      } else {
        setSaved(t("call.saved"));
      }
      reset();
      onLogged();
    } catch {
      setError(t("call.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-950">
      <div className="flex items-center gap-2">
        <PhoneCall className="h-4 w-4 text-eko-violet" />
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-50">
          {t("call.title")}
        </h2>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{t("call.subtitle")}</p>

      <Group label={t("call.outcome")}>
        {OUTCOMES.map((o) => (
          <Chip
            key={o}
            active={outcome === o}
            danger={STAND_DOWN.includes(o)}
            onClick={() => setOutcome(outcome === o ? null : o)}
          >
            {t(`call.outcome.${o}`)}
          </Chip>
        ))}
      </Group>

      {standDown && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {t("call.standDown")}
        </p>
      )}

      {outcome && !standDown && (
        <>
          <Group label={t("call.intent")}>
            {INTENTS.map((i) => (
              <Chip key={i} active={intent === i} onClick={() => setIntent(intent === i ? null : i)}>
                {t(`intent.${i}`)}
              </Chip>
            ))}
          </Group>

          <Group label={t("call.urgency")}>
            {URGENCIES.map((u) => (
              <Chip key={u} active={urgency === u} onClick={() => setUrgency(urgency === u ? null : u)}>
                {t(`call.urgency.${u}`)}
              </Chip>
            ))}
          </Group>

          <Group label={t("call.preferred")}>
            {CHANNELS.map((c) => (
              <Chip
                key={c}
                active={preferred === c}
                onClick={() => setPreferred(preferred === c ? null : c)}
              >
                {t(`call.preferred.${c}`)}
              </Chip>
            ))}
          </Group>
          {(preferred === "email" || preferred === "call") && (
            // Saying this out loud is the honest half of the feature: those two
            // are worked by hand from the console's list, not sent.
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
              {t("call.preferredManual")}
            </p>
          )}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field
              id="call-zone"
              label={t("call.zone")}
              value={zone}
              placeholder={lead.zone || ""}
              onChange={setZone}
            />
            <Field
              id="call-budget"
              label={t("call.budgetMax")}
              value={budgetMax}
              type="number"
              placeholder={lead.budget_max ? String(lead.budget_max) : ""}
              onChange={setBudgetMax}
            />
          </div>

          <Group label={t("call.followUp")}>
            <Chip active={followUpDays === null} onClick={() => setFollowUpDays(null)}>
              {t("call.followUp.none")}
            </Chip>
            {FOLLOW_UP_DAYS.map((d) => (
              <Chip key={d} active={followUpDays === d} onClick={() => setFollowUpDays(d)}>
                {t("call.followUp.days").replace("{n}", String(d))}
              </Chip>
            ))}
          </Group>

          <label className="mt-4 flex items-start gap-3 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={askedForTexts}
              onChange={(e) => setAskedForTexts(e.target.checked)}
              className="mt-0.5 h-4 w-4 flex-none"
            />
            <span>
              {t("call.consent")}
              <span className="mt-0.5 block text-xs text-gray-500 dark:text-gray-400">
                {t("call.consentHint")}
              </span>
            </span>
          </label>
        </>
      )}

      {outcome && (
        <div className="mt-4">
          <label
            htmlFor="call-note"
            className="block text-xs font-medium text-gray-600 dark:text-gray-400"
          >
            {t("call.note")}
          </label>
          <textarea
            id="call-note"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm text-gray-900 focus:border-gray-900 dark:border-gray-700 dark:text-gray-100 dark:focus:border-gray-300"
          />
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">
          {saved}
        </p>
      )}

      <button
        type="button"
        onClick={save}
        disabled={!outcome || saving}
        className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-eko-violet px-5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        {saving && <Loader2 className="h-4 w-4 animate-spin" />}
        {saving ? t("call.saving") : t("call.save")}
      </button>
    </section>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <fieldset className="mt-4">
      <legend className="text-xs font-medium text-gray-600 dark:text-gray-400">
        {label}
      </legend>
      <div className="mt-2 flex flex-wrap gap-2">{children}</div>
    </fieldset>
  );
}

function Chip({
  active,
  danger,
  onClick,
  children,
}: {
  active: boolean;
  danger?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      // 44px floor: this gets used on a phone between showings.
      className={`min-h-[44px] rounded-lg border px-3 text-sm transition-colors ${
        active
          ? danger
            ? "border-red-500 bg-red-500 text-white"
            : "border-eko-violet bg-eko-violet text-white"
          : "border-gray-300 text-gray-700 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 h-11 w-full rounded-lg border border-gray-300 bg-transparent px-3 text-sm text-gray-900 focus:border-gray-900 dark:border-gray-700 dark:text-gray-100 dark:focus:border-gray-300"
      />
    </div>
  );
}
