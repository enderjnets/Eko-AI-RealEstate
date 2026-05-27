"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus, X } from "lucide-react";
import { type LeadCreate, type LeadIntent, leadsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Channel = "sms" | "email";

const INTENTS: LeadIntent[] = ["rent", "buy", "valuation", "other"];

const EMPTY = {
  name: "",
  channel: "sms" as Channel,
  phone: "",
  intent: "" as LeadIntent | "",
  zone: "",
  budget_min: "",
  budget_max: "",
  property_type: "",
  urgency: "",
  first_message: "",
};

export function AddLeadButton() {
  const router = useRouter();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function close() {
    if (saving) return;
    setOpen(false);
    setForm({ ...EMPTY });
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const phone = form.phone.trim();
    if (!phone) {
      setError(t("leadNew.errorRequired"));
      return;
    }
    const body: LeadCreate = { phone, channel: form.channel };
    if (form.name.trim()) body.name = form.name.trim();
    if (form.intent) body.intent = form.intent;
    if (form.zone.trim()) body.zone = form.zone.trim();
    if (form.budget_min.trim()) body.budget_min = form.budget_min.trim();
    if (form.budget_max.trim()) body.budget_max = form.budget_max.trim();
    if (form.property_type.trim()) body.property_type = form.property_type.trim();
    if (form.urgency.trim()) body.urgency = form.urgency.trim();
    if (form.first_message.trim()) body.first_message = form.first_message.trim();

    setSaving(true);
    setError(null);
    try {
      const lead = await leadsApi.create(body);
      router.push(`/leads/${lead.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg.includes("409") ? t("leadNew.errorDuplicate") : msg);
      setSaving(false);
    }
  }

  const inputCls =
    "w-full px-3 py-1.5 rounded-md bg-white/5 border border-white/10 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-eko-violet/50";
  const labelCls = "block text-xs text-gray-400 mb-1";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-eko-violet/90 hover:bg-eko-violet text-white text-sm font-medium transition-colors shrink-0"
      >
        <Plus className="w-4 h-4" />
        {t("leads.add")}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm p-4 sm:p-8"
          onClick={close}
        >
          <div
            className="w-full max-w-lg my-auto rounded-xl border border-white/10 bg-eko-noir shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
              <h3 className="text-sm font-medium text-white">{t("leadNew.title")}</h3>
              <button
                type="button"
                onClick={close}
                className="text-gray-500 hover:text-white transition-colors"
                aria-label={t("common.cancel")}
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={submit} className="px-5 py-4 space-y-4">
              <div>
                <label className={labelCls}>{t("leadNew.name")}</label>
                <input
                  className={inputCls}
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder={t("leadNew.namePlaceholder")}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>{t("leadNew.channel")}</label>
                  <select
                    className={inputCls}
                    value={form.channel}
                    onChange={(e) => set("channel", e.target.value as Channel)}
                  >
                    <option value="sms" className="bg-eko-noir">
                      {t("leadNew.channel.sms")}
                    </option>
                    <option value="email" className="bg-eko-noir">
                      {t("leadNew.channel.email")}
                    </option>
                    <option value="voice" disabled className="bg-eko-noir text-gray-600">
                      {t("leadNew.channel.voice")}
                    </option>
                  </select>
                </div>
                <div>
                  <label className={labelCls}>
                    {form.channel === "email" ? t("leadNew.contactEmail") : t("leadNew.contactPhone")}
                    <span className="text-red-400"> *</span>
                  </label>
                  <input
                    className={inputCls}
                    value={form.phone}
                    onChange={(e) => set("phone", e.target.value)}
                    placeholder={
                      form.channel === "email"
                        ? t("leadNew.contactPlaceholderEmail")
                        : t("leadNew.contactPlaceholderSms")
                    }
                    type={form.channel === "email" ? "email" : "tel"}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>{t("leadNew.intent")}</label>
                  <select
                    className={inputCls}
                    value={form.intent}
                    onChange={(e) => set("intent", e.target.value as LeadIntent | "")}
                  >
                    <option value="" className="bg-eko-noir">
                      {t("leadNew.intentNone")}
                    </option>
                    {INTENTS.map((v) => (
                      <option key={v} value={v} className="bg-eko-noir">
                        {t(`intent.${v}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>{t("lead.field.zone")}</label>
                  <input
                    className={inputCls}
                    value={form.zone}
                    onChange={(e) => set("zone", e.target.value)}
                    placeholder="Brickell"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>{t("leadNew.budgetMin")}</label>
                  <input
                    className={inputCls}
                    value={form.budget_min}
                    onChange={(e) => set("budget_min", e.target.value)}
                    placeholder="2000"
                    inputMode="numeric"
                  />
                </div>
                <div>
                  <label className={labelCls}>{t("leadNew.budgetMax")}</label>
                  <input
                    className={inputCls}
                    value={form.budget_max}
                    onChange={(e) => set("budget_max", e.target.value)}
                    placeholder="4000"
                    inputMode="numeric"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>{t("lead.field.type")}</label>
                  <input
                    className={inputCls}
                    value={form.property_type}
                    onChange={(e) => set("property_type", e.target.value)}
                    placeholder={t("propType.condo")}
                  />
                </div>
                <div>
                  <label className={labelCls}>{t("lead.field.urgency")}</label>
                  <input
                    className={inputCls}
                    value={form.urgency}
                    onChange={(e) => set("urgency", e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className={labelCls}>{t("leadNew.firstMessage")}</label>
                <textarea
                  className={`${inputCls} resize-none`}
                  rows={3}
                  value={form.first_message}
                  onChange={(e) => set("first_message", e.target.value)}
                  placeholder={t("leadNew.firstMessagePlaceholder")}
                />
                <p className="mt-1 text-xs text-gray-500">{t("leadNew.firstMessageHint")}</p>
              </div>

              {error && <p className="text-xs text-red-400">{error}</p>}

              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex-1 inline-flex items-center justify-center gap-2 rounded-md bg-eko-violet/90 hover:bg-eko-violet py-2 text-sm font-medium text-white disabled:opacity-50 transition-colors"
                >
                  {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                  {saving ? t("leadNew.saving") : t("leadNew.save")}
                </button>
                <button
                  type="button"
                  onClick={close}
                  disabled={saving}
                  className="rounded-md border border-white/10 px-4 py-2 text-sm text-gray-400 hover:bg-white/5 disabled:opacity-50 transition-colors"
                >
                  {t("common.cancel")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
