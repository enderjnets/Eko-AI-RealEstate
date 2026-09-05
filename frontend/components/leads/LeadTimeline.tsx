"use client";

/**
 * What happened to this lead, oldest first.
 *
 * Until `lead_events` existed a lead had a status and nothing else: whether it
 * moved from new to qualified in an hour or in three weeks, whether a person
 * moved it or a phone call did, whether anybody ever rang back — none of it was
 * anywhere. This is the film to the status column's photograph.
 *
 * Read forwards, unlike the calls list next to it. That one is a worklist and
 * the newest row is the one you act on; this is a story, and a story that runs
 * backwards is one nobody reads twice.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { type LeadEvent, leadEventsApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function describe(event: LeadEvent, t: (k: string, v?: Record<string, string | number>) => string) {
  const meta = event.meta || {};
  switch (event.type) {
    case "status_changed":
      return t("timeline.status", {
        from: t(`status.${event.from_status}`),
        to: t(`status.${event.to_status}`),
      });
    case "call_inbound": {
      const secs = Number(meta.duration_seconds);
      const length = Number.isFinite(secs) ? ` · ${Math.round(secs)}s` : "";
      return `${t("timeline.callIn")}${length}`;
    }
    case "call_logged":
      return `${t("timeline.callOut")} · ${String(meta.outcome ?? "")}`;
    case "appointment_set":
      return t("timeline.appointmentSet", { via: String(meta.via ?? "") });
    case "appointment_cancelled":
      return t("timeline.appointmentCancelled");
    case "appointment_outcome":
      return meta.outcome === "completed"
        ? t("timeline.appointmentHeld")
        : t("timeline.appointmentNoShow");
    case "deal_closed":
      return t("timeline.dealClosed", { kind: String(meta.kind ?? "") });
    default:
      return t(`timeline.${event.type}`);
  }
}

export function LeadTimeline({ leadId }: { leadId: number }) {
  const { t, lang } = useI18n();
  const [events, setEvents] = useState<LeadEvent[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    leadEventsApi
      .list(leadId)
      .then((rows) => alive && setEvents(rows))
      .catch(() => alive && setEvents([]))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [leadId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-500 py-3">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t("common.loading")}
      </div>
    );
  }
  if (!events || events.length === 0) return null;

  const when = (iso: string) =>
    new Date(iso).toLocaleString(lang === "es" ? "es-ES" : "en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <section className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 mb-6">
      <h2 className="text-sm font-semibold text-white mb-3">{t("timeline.title")}</h2>
      <ol className="space-y-2.5">
        {events.map((e, i) => (
          <li key={`${e.at}-${i}`} className="flex gap-3 text-xs">
            <span className="text-gray-600 tabular-nums shrink-0 w-28">{when(e.at)}</span>
            <span className="text-gray-300 min-w-0">
              {describe(e, t)}
              {e.actor && <span className="text-gray-600"> · {e.actor}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
