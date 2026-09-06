/**
 * Typed HTTP client for the Eko AI Realtors backend.
 *
 * All requests go through `/api/...` (same-origin), which next.config.js rewrites
 * to the backend container. Works regardless of how the frontend is reached
 * (LAN, Tailscale, future Cloudflare).
 */

export type LeadStatus =
  | "new"
  | "qualified"
  | "visiting"
  | "post_visit"
  | "won"
  | "lost"
  | "paused";

export type LeadIntent = "rent" | "buy" | "valuation" | "other";

export type MessageDirection = "inbound" | "outbound";
export type MessageSender = "lead" | "agent" | "human";
export type MessageStatus = "pending" | "sent" | "delivered" | "read" | "failed";

export type CalculatorCredit = "excellent" | "good" | "fair";
export type CalculatorCappedBy = "rent" | "savings" | "floor";

/**
 * What a visitor calculated on /calculator before leaving their email —
 * recomputed and stored by the server (`leads.calculator_snapshot`), never the
 * browser's own figure. Under the estimate floor (`capped_by: "floor"`) the
 * page showed no price, `price` is a sub-floor number and the two comparison
 * fields are null: a floor snapshot is "they tried", not "they could buy X".
 */
export interface CalculatorSnapshot {
  version: number;
  computed_at: string;
  lang: "en" | "es" | null;
  inputs: { rent: number; savings: number; credit: CalculatorCredit };
  assumptions: Record<string, unknown>;
  result: {
    price: number;
    capped_by: CalculatorCappedBy;
    loan: number;
    down: number;
    monthly: { pi: number; tax: number; insurance: number; pmi: number; hoa: number; total: number };
    net_5y: number | null;
    crossover_year: number | null;
  };
}

export interface Lead {
  id: number;
  phone: string;
  email: string | null;
  name: string | null;
  status: LeadStatus;
  intent: LeadIntent | null;
  budget_min: string | null; // Decimal serializes as string in JSON
  budget_max: string | null;
  zone: string | null;
  property_type: string | null;
  urgency: string | null;
  human_takeover: boolean;
  /** Set when this lead replied STOP. Automated messages are suppressed. */
  opted_out_at?: string | null;
  consent_at?: string | null;
  score: number;
  score_breakdown: {
    components?: Record<string, number>;
    base?: number;
    status_gate?: number;
    status?: string;
    tier?: "hot" | "warm" | "cold";
  };
  needs_response?: boolean;
  /**
   * How it ended. `won_kind` says which business it was — a listing that sold,
   * a buyer who bought and a rental are three different things behind one
   * `won`. `won_value` is the commission and arrives `null` for anyone who is
   * not an admin; the rest of the close is visible to the whole office.
   */
  won_kind?: WonKind | null;
  won_value?: string | null; // Decimal serializes as string in JSON
  won_at?: string | null;
  lost_reason?: string | null;
  /**
   * Which video / campaign / page produced this lead (utm_*, referrer,
   * landing_variant…). Server-filtered through a whitelist — never the raw
   * meta column. Empty object when nothing was captured.
   */
  attribution: Record<string, string>;
  /** Null for every lead that did not come through /calculator. */
  calculator?: CalculatorSnapshot | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadList {
  total: number;
  items: Lead[];
}

export interface Message {
  id: number;
  direction: MessageDirection;
  sender: MessageSender;
  content: string;
  external_id: string | null;
  delivery_status: MessageStatus;
  subject: string | null;
  /**
   * In the lead's thread but never sent to them — today, the copy of an
   * appointment invitation that went to the agency. Must be rendered as such:
   * unmarked, a realtor reads it as something the client received.
   */
  internal: boolean;
  channel: string; // channel of this message's conversation (for mixed timelines)
  llm_provider: string | null;
  llm_model: string | null;
  /** Fair Housing hits found on the way out. null = never screened. */
  fair_housing_flags: { phrase: string; category: string }[] | null;
  created_at: string;
}

export interface Conversation {
  id: number;
  lead_id: number;
  channel: string;
  external_thread_id: string | null;
  status: "active" | "archived";
  summary: string | null;
  started_at: string;
  last_at: string;
  messages: Message[];
}

export interface ConversationSummary {
  id: number;
  channel: string;
  status: "active" | "archived";
  external_thread_id: string | null;
  started_at: string;
  last_at: string;
  message_count: number;
}

export interface Timeline {
  lead_id: number;
  messages: Message[]; // flat, time-ordered across all channels
  conversations: ConversationSummary[];
  channels: string[];
  primary_channel: string | null;
  primary_conversation_id: number | null;
}

export type SendChannel = "sms" | "email" | "whatsapp";

/** Must match `WON_KINDS` in `backend/app/models/lead.py`: the API refuses
 *  anything else, and a close is the one field with no sensible default. */
export const WON_KINDS = [
  "listing_sold",
  "buyer_purchase",
  "rental",
  "referral",
  "other",
] as const;
export type WonKind = (typeof WON_KINDS)[number];

export interface LeadPatch {
  name?: string;
  status?: LeadStatus;
  intent?: LeadIntent;
  zone?: string;
  budget_min?: number | string;
  budget_max?: number | string;
  property_type?: string;
  urgency?: string;
  human_takeover?: boolean;
  won_kind?: WonKind;
  won_value?: number | string;
  won_at?: string;
  lost_reason?: string;
}

export interface LeadCreate {
  phone: string; // identifier: phone (sms) or email address (email)
  name?: string;
  intent?: LeadIntent;
  zone?: string;
  budget_min?: number | string;
  budget_max?: number | string;
  property_type?: string;
  urgency?: string;
  channel?: "sms" | "email";
  first_message?: string;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await errorDetail(res)}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// Read the response body exactly once (a stream can't be read twice — reading it
// as JSON then again as text throws "body stream already read" and masks the real
// error). Read text, then try to pull a JSON `detail` out of it.
async function errorDetail(res: Response): Promise<string> {
  let raw = "";
  try {
    raw = await res.text();
  } catch {
    return res.statusText;
  }
  try {
    const body = JSON.parse(raw);
    if (typeof body?.detail === "string") return body.detail;
    // FastAPI validation errors: `detail` is an array of {loc, msg}. Render it
    // readable ("budget_min: Input should be a valid decimal") instead of dumping
    // the raw JSON (which also crashes React if rendered as an object).
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((e: { loc?: unknown[]; msg?: string }) => {
          const field =
            Array.isArray(e?.loc) && e.loc.length ? String(e.loc[e.loc.length - 1]) : "";
          return field ? `${field}: ${e?.msg ?? "invalid"}` : e?.msg ?? "invalid";
        })
        .join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return raw || res.statusText;
  }
}

export interface HumanMessageResult {
  status: "ok" | "error";
  lead_id: number | null;
  channel: string | null;
  outbound_id: number | null;
  outbound_status: string | null;
  error: string | null;
}

export interface SuggestionsResult {
  suggestions: string[];
  provider: string | null;
  model: string | null;
  error: string | null;
}

export type VisitStatus =
  | "scheduled"
  | "confirmed"
  | "cancelled"
  | "completed"
  | "no_show";

export interface Slot {
  start: string; // ISO datetime
  end: string;
}

export interface SlotsResponse {
  slots: Slot[];
  timezone: string;
  days: number;
}

export interface Visit {
  id: number;
  lead_id: number | null;
  title: string | null;
  calendar_provider: string;
  external_booking_id: string;
  status: VisitStatus;
  scheduled_at: string;
  duration_minutes: number;
  timezone: string;
  property_address: string | null;
  property_id: number | null;
  meeting_url: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarItem {
  kind: "visit" | "event" | "followup";
  id: number;
  title: string;
  scheduled_at: string;
  duration_minutes: number | null;
  timezone: string | null;
  status: string | null;
  lead_id: number | null;
  lead_name: string | null;
  property_address: string | null;
  property_id: number | null;
  notes: string | null;
}

export interface AgendaResponse {
  items: CalendarItem[];
  timezone: string;
}

export interface ManualEventIn {
  title: string;
  scheduled_at: string;
  duration_minutes?: number;
  notes?: string;
  property_address?: string;
  /** Which listing the showing is for, so the post-visit message can name it. */
  property_id?: number;
  lead_id?: number | null;
  timezone?: string;
}

export interface BookingIn {
  start_time: string;
  duration_minutes?: number;
  property_address?: string;
  /** Which listing the showing is for, so the post-visit message can name it. */
  property_id?: number;
  notes?: string;
  timezone?: string;
}

export const calendarApi = {
  slots: (leadId: number, opts?: { days?: number; timezone?: string }) => {
    const q = new URLSearchParams();
    if (opts?.days) q.set("days", String(opts.days));
    if (opts?.timezone) q.set("timezone", opts.timezone);
    const qs = q.toString();
    return api<SlotsResponse>(`/v1/leads/${leadId}/calendar/slots${qs ? `?${qs}` : ""}`);
  },
  book: (leadId: number, body: BookingIn) =>
    api<Visit>(`/v1/leads/${leadId}/calendar/book`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const visitsApi = {
  list: (leadId: number) => api<Visit[]>(`/v1/leads/${leadId}/visits`),
  cancel: (visitId: number, reason?: string) =>
    api<Visit>(`/v1/visits/${visitId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  /** Did the appointment actually happen. Only from a visit still standing —
   *  the API answers 409 for one already cancelled or already resolved. */
  outcome: (visitId: number, outcome: "completed" | "no_show") =>
    api<Visit>(`/v1/visits/${visitId}/outcome`, {
      method: "POST",
      body: JSON.stringify({ outcome }),
    }),
  all: (opts?: { from?: string; to?: string }) => {
    const q = new URLSearchParams();
    if (opts?.from) q.set("from", opts.from);
    if (opts?.to) q.set("to", opts.to);
    const qs = q.toString();
    return api<Visit[]>(`/v1/visits${qs ? `?${qs}` : ""}`);
  },
  agenda: (days = 30) => api<AgendaResponse>(`/v1/visits/agenda?days=${days}`),
  createEvent: (body: ManualEventIn) =>
    api<Visit>(`/v1/visits`, { method: "POST", body: JSON.stringify(body) }),
};

// ── Call console ────────────────────────────────────────────────────────────

export type CallOutcome =
  | "wants_listings"
  | "booked_visit"
  | "follow_up"
  | "no_answer"
  | "has_agent"
  | "do_not_contact"
  | "wrong_number";

export type PreferredChannel = "sms" | "email" | "call";

export interface CallLog {
  id: number;
  lead_id: number;
  outcome: CallOutcome;
  note: string | null;
  logged_by: string | null;
  created_at: string;
}

export interface CallIn {
  outcome: CallOutcome;
  note?: string;
  intent?: LeadIntent;
  urgency?: string;
  zone?: string;
  property_type?: string;
  budget_min?: number;
  budget_max?: number;
  preferred_channel?: PreferredChannel;
  name?: string;
  email?: string;
  follow_up_in_days?: number;
  /** The person asked ON THE CALL to be sent something. Records consent. */
  asked_for_texts?: boolean;
}

export interface CallResult {
  call: CallLog;
  score: number;
  follow_up_scheduled_for: string | null;
  cancelled_follow_ups: number;
  /** True only when the "asked for texts" tick actually became a record. */
  consent_recorded: boolean;
  /** They had already opted out, so no consent was written. */
  consent_refused_opted_out: boolean;
  preferred_channel: PreferredChannel | null;
}

export const callsApi = {
  list: (leadId: number) => api<CallLog[]>(`/v1/leads/${leadId}/calls`),
  log: (leadId: number, body: CallIn) =>
    api<CallResult>(`/v1/leads/${leadId}/calls`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export interface ConsoleLead {
  id: number;
  name: string | null;
  phone: string | null;
  email: string | null;
  score: number | null;
  status: LeadStatus;
  zone: string | null;
  preferred_channel: PreferredChannel | null;
  last_message_at: string | null;
}

export interface ConsoleTask {
  follow_up_id: number;
  scheduled_for: string;
  channel: PreferredChannel;
  lead: ConsoleLead;
}

export interface HeldFollowUp {
  follow_up_id: number;
  scheduled_for: string;
  holds: number;
  /** "pending" = held for want of permission; "failed" = the sends failed. */
  status: "pending" | "failed";
  lead: ConsoleLead;
}

export interface ConsoleToday {
  tasks: ConsoleTask[];
  held: HeldFollowUp[];
  untouched_hot: ConsoleLead[];
  generated_at: string;
}

export const consoleApi = {
  today: () => api<ConsoleToday>(`/v1/console/today`),
};

// ─── Content Studio (v0.52+) ────────────────────────────────────────────

export type ContentStatus =
  | "draft"
  | "needs_approval"
  | "approved"
  | "publishing"
  | "published"
  | "rejected"
  | "failed";

/**
 * The newest reading of a post's public counters.
 *
 * `source` is not decoration: `youtube_api` was read from the platform,
 * `manual` was typed by a person because TikTok and Instagram hand view counts
 * only to a first-party app that has passed platform review. The console shows
 * which is which so a hand-read estimate is never taken for a measurement.
 */
export interface PublicationMetrics {
  views: number | null;
  likes: number | null;
  comments: number | null;
  captured_on: string;
  source: "youtube_api" | "manual";
}

export interface ContentPublication {
  id: number;
  platform: string;
  status: string;
  external_id: string | null;
  published_at: string | null;
  /** When the platform will publish it. What the console counts down to. */
  scheduled_at: string | null;
  /** The post's real address on the platform, once it has gone out. */
  external_url: string | null;
  last_error: string | null;
  /** Null when nobody has read the counters yet: no key, no address, or a
   *  network whose number has not been typed in. */
  latest_metrics: PublicationMetrics | null;
}

export interface ContentPiece {
  id: number;
  kind: "generated" | "recorded";
  language: "en" | "es";
  status: ContentStatus;
  hook: string | null;
  script: string | null;
  caption: string | null;
  media_path: string | null;
  /** Why the clip is not rendered, in the render's own words. */
  render_error: string | null;
  render_state?: string | null;
  render_stage?: string | null;
  render_progress?: number | null;
  render_machine_working?: boolean | null;
  violations: { phrase: string; category: string }[] | null;
  approved_by: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  created_at: string;
  updated_at: string;
  publications: ContentPublication[];
}

/**
 * Why the queue looks the way it does — booleans, counts, and one number.
 *
 * Mirrors `StudioStatus` in `backend/app/api/v1/content.py`, whose docstring
 * carries the reasoning for why a size cap is allowed here when a config value
 * would not be. An audit found this half of the pair still asserting the old
 * rule above a field that breaks it.
 */
export interface StudioStatus {
  studio_enabled: boolean;
  render_enabled: boolean;
  brokerage_line_set: boolean;
  publishing_available: boolean;
  /** Whether this install can actually post right now (switch on, nothing missing). */
  publishing_ready: boolean;
  /** Megabytes. Compared against `file.size` before the upload is opened. */
  upload_max_mb: number;
  /**
   * The agency's IANA zone. Scheduled dates are rendered in it, never in the
   * reader's: 20:30 in Denver would otherwise read as 03:30 in Madrid with
   * nothing on screen to say so.
   */
  timezone: string;
  counts: Record<string, number>;
}

/** Ten minutes: a clip at the size cap on slow mobile data, with room to spare. */
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

/**
 * The reason a rejected upload failed, in whatever form the server sent it.
 *
 * Mirrors `errorDetail()` including its last resort, and that last resort is
 * the point: `xhr.statusText` is the empty string on HTTP/2, so a 413 from a
 * proxy — an HTML page, no JSON — used to render as "API 413:" and nothing
 * after it. The most likely rejection produced the least useful sentence.
 */
function xhrDetail(xhr: XMLHttpRequest): string {
  const raw = xhr.responseText ?? "";
  try {
    const body = JSON.parse(raw);
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((e: { loc?: unknown[]; msg?: string }) =>
          `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`.trim(),
        )
        .join("; ");
    }
  } catch {
    /* not JSON — fall through to the raw body */
  }
  return raw.trim().slice(0, 200) || xhr.statusText || "no reason given";
}

/** Client-side failures, keyed so the UI can translate them. */
/**
 * A file's size in MB, rounded UP to one decimal.
 *
 * Not `toFixed(1)`, which rounds to nearest: a clip one byte over a 95 MB cap
 * came out as "95.0" and the refusal read "That clip is 95 MB and the limit is
 * 95 MB" — a sentence that contradicts itself and asks the person to trim a
 * file that already looks small enough. Rounding up means the number shown is
 * never below the cap it was refused for.
 */
const sizeMb = (file: File) =>
  (Math.ceil((file.size / (1024 * 1024)) * 10) / 10).toFixed(1);

export type UploadFailure = "network" | "cancelled" | "timeout" | "tooLarge";
// `detail` carries the numbers a message needs to be actionable. Kept as a
// string rather than a rich error type because these cross `Error.message`,
// which is the only channel a rejected Promise has to the caller here.
const uploadFailure = (kind: UploadFailure, detail?: string) =>
  detail ? `upload:${kind}:${detail}` : `upload:${kind}`;

export const contentApi = {
  status: () => api<StudioStatus>(`/v1/content/status`),
  /**
   * Pieces in any of the given statuses; all of them when none is given.
   *
   * A list, because a console tab is not a status: "Approved" holds both
   * `approved` and `publishing`, since a piece already handed to the queue is
   * still waiting to go out and is exactly the one whose date somebody opened
   * the console to see. Repeated `?status=` params, which is what FastAPI
   * reads into a list.
   */
  list: (status?: ContentStatus | ContentStatus[]) => {
    const wanted = status === undefined ? [] : ([] as ContentStatus[]).concat(status);
    const q = wanted.map((s) => `status=${encodeURIComponent(s)}`).join("&");
    return api<ContentPiece[]>(q ? `/v1/content?${q}` : `/v1/content`);
  },
  edit: (id: number, body: { hook?: string; script?: string; caption?: string }) =>
    api<ContentPiece>(`/v1/content/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  submit: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/submit`, { method: "POST" }),
  approve: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/approve`, { method: "POST" }),
  /** A piece that failed to publish, back in front of a person. */
  retry: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/retry`, { method: "POST" }),
  /** Make the video again, from the plan the piece already carries. */
  rebuild: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/rebuild`, { method: "POST" }),
  reject: (id: number, reason: string) =>
    api<ContentPiece>(`/v1/content/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  /**
   * Type in a view count the platform will not tell a machine.
   *
   * For TikTok and Instagram this is the only way the number ever arrives.
   * Allowed for YouTube too: a person correcting a stale reading is more right
   * than a tick from six hours ago.
   */
  setMetrics: (
    id: number,
    platform: string,
    body: { views: number; likes?: number; comments?: number },
  ) =>
    api<ContentPiece>(`/v1/content/${id}/publications/${platform}/metrics`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /** The clip itself, behind the same auth as everything else. */
  mediaUrl: (id: number) => `/api/v1/content/${id}/media`,

  /**
   * A clip from the phone, streamed as a RAW body.
   *
   * Not multipart, unlike `discoveryApi.upload`: this route reads
   * `request.stream()` and enforces the size cap while writing to disk, so a
   * 4K clip never sits in memory. The filename is a query parameter and only
   * survives long enough to give the server a suffix.
   *
   * XHR rather than fetch, and that is the whole reason this is not three
   * lines: fetch cannot report upload progress in any browser, and the device
   * this exists for is a phone on mobile data sending hundreds of megabytes.
   * Without a progress bar that is indistinguishable from a frozen page, and
   * a person who thinks it froze presses the button again.
   */
  upload: (
    file: File,
    language: "en" | "es",
    onProgress?: (percent: number) => void,
    maxMb?: number,
  ): Promise<ContentPiece> =>
    new Promise((resolve, reject) => {
      // Before the request exists, not after. A 4K phone clip is a few hundred
      // MB; sending it over mobile data to be told at the end that it was too
      // big costs minutes and the person's allowance, and the answer they get
      // is an HTML error page from a proxy rather than a sentence.
      //
      // `maxMb` undefined means the caller could not learn the limit —
      // `contentApi.status()` swallows its own failure — and in that case the
      // upload GOES AHEAD. The server is the gate and always was; refusing to
      // send because one GET failed would break uploading every time an
      // unrelated request did, which is a worse product than a wasted upload.
      if (maxMb !== undefined && file.size > maxMb * 1024 * 1024) {
        reject(new Error(uploadFailure("tooLarge", `${sizeMb(file)}:${maxMb}`)));
        return;
      }
      const url =
        `/api/v1/content/upload?filename=${encodeURIComponent(file.name)}` +
        `&language=${language}`;
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          // `total > 0` as well as lengthComputable: a zero-length body
          // divides to NaN and paints a bar of width "NaN%".
          if (e.lengthComputable && e.total > 0) {
            onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
          }
        };
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as ContentPiece);
          } catch {
            reject(new Error(`API ${xhr.status}: unreadable response`));
          }
          return;
        }
        // A 413 is the SAME event as the pre-flight check above, arriving from
        // the other side. It happens whenever the limit could not be learned
        // (`maxMb` undefined) and on any clip that clears the tunnel but not
        // our own body-size middleware. Without this it surfaced as the raw
        // internal token `API 413: body_too_large` — English, in a bilingual
        // product, with a translated sentence for exactly this event sitting
        // unused. One event, one message, whichever wall stopped it.
        if (xhr.status === 413) {
          let limit = maxMb;
          try {
            const parsed = JSON.parse(xhr.responseText) as { limit_mb?: number };
            if (typeof parsed.limit_mb === "number") limit = parsed.limit_mb;
          } catch {
            // A proxy's HTML page, not our JSON. `limit` stays whatever the
            // caller knew, and the message degrades to a blank rather than a lie.
          }
          reject(new Error(uploadFailure("tooLarge", `${sizeMb(file)}:${limit ?? ""}`)));
          return;
        }
        reject(new Error(`API ${xhr.status}: ${xhrDetail(xhr)}`));
      };
      xhr.onerror = () => reject(new Error(uploadFailure("network")));
      xhr.onabort = () => reject(new Error(uploadFailure("cancelled")));
      // Without a timeout an upload can hang forever on a half-open mobile
      // connection — which is the exact situation this feature exists for —
      // and the caller's `finally` never runs, so the progress bar sticks and
      // the button stays disabled with no way out but a page reload.
      xhr.timeout = UPLOAD_TIMEOUT_MS;
      xhr.ontimeout = () => reject(new Error(uploadFailure("timeout")));
      xhr.send(file);
    }),
};

export interface AgencySettings {
  agency_name: string;
  /** Colorado-required brokerage identification, burned into rendered clips. */
  brokerage_line: string | null;
  agency_phone: string | null;
  /** Where Cal.com sends the confirmation for a lead who only gave a phone. */
  booking_contact_email: string | null;
  agent_persona: string;
  greeting_template: string;
  languages: string[];
  timezone: string;
  business_hours: Record<string, { open: string; close: string } | null>;
  created_at: string;
  updated_at: string;
}

export interface AgencySettingsPatch {
  agency_name?: string;
  brokerage_line?: string | null;
  agency_phone?: string | null;
  booking_contact_email?: string | null;
  agent_persona?: string;
  greeting_template?: string;
  languages?: string[];
  timezone?: string;
  business_hours?: Record<string, { open: string; close: string } | null>;
}

// ── Agent availability ───────────────────────────────────────────────────────
// There is no `email` anywhere in these types on purpose. The backend takes it
// from the session token, so a client cannot address another agent's schedule —
// not because a check rejects it, but because no field carries a victim.

export type AppointmentActivity = "showing" | "valuation" | "call" | "open_house";

export interface AvailabilityWindow {
  /** 0 = Monday, matching the backend and `Date.getDay()` shifted by one. */
  days: number[];
  /** "HH:MM", 24-hour, in the agency's timezone. */
  start: string;
  end: string;
}

export interface ActivityAvailability {
  activity: AppointmentActivity;
  label: string;
  duration_minutes: number;
  active: boolean;
  /** False while Cal.com is still being provisioned: an empty week then means
      "not set up yet", not "never available". */
  configured: boolean;
  windows: AvailabilityWindow[];
}

export interface MyAvailability {
  email: string;
  timezone: string;
  /** Non-null means nothing here can work yet, and says why in plain words. */
  unavailable_reason: string | null;
  activities: ActivityAvailability[];
}

export interface TeamAvailability {
  email: string;
  activities: ActivityAvailability[];
}

export const availabilityApi = {
  mine: () => api<MyAvailability>(`/v1/availability/me`),
  setActivity: (
    activity: AppointmentActivity,
    body: {
      windows: AvailabilityWindow[];
      duration_minutes?: number;
      active?: boolean;
    },
  ) =>
    api<ActivityAvailability>(`/v1/availability/me/${activity}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  team: () => api<TeamAvailability[]>(`/v1/availability`),
};

export const settingsApi = {
  get: () => api<AgencySettings>(`/v1/settings`),
  update: (body: AgencySettingsPatch) =>
    api<AgencySettings>(`/v1/settings`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

export type PropertySource = "reso" | "idx" | "mls" | "manual";
export type PropertyStatus = "active" | "pending" | "sold" | "off_market";

export interface Property {
  id: number;
  source: PropertySource;
  external_id: string;
  status: PropertyStatus;
  title: string;
  description: string | null;
  property_type: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  zone: string | null;
  price: string | null; // Decimal serializes as string
  bedrooms: number | null;
  bathrooms: string | null;
  sqft: number | null;
  url: string | null;
  photos: string[];
  listed_at: string | null;
  created_at: string;
  updated_at: string;
  /** IDX: the listing broker who must be credited beside this listing. */
  listing_broker: string | null;
  listing_agent: string | null;
  listing_type: string | null;
}

export interface PropertyList {
  total: number;
  items: Property[];
}

export interface PropertyFilters {
  status?: PropertyStatus;
  source?: PropertySource;
  city?: string;
  zone?: string;
  property_type?: string;
  min_price?: number;
  max_price?: number;
  limit?: number;
  offset?: number;
}

export const propertiesApi = {
  list: (params?: PropertyFilters) => {
    const q = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    });
    const qs = q.toString();
    return api<PropertyList>(`/v1/properties${qs ? `?${qs}` : ""}`);
  },
  get: (id: number) => api<Property>(`/v1/properties/${id}`),
  sync: () => api<{ created: number; updated: number; total: number }>(`/v1/properties/sync`, { method: "POST" }),
};

export const leadsApi = {
  list: (params?: { status?: LeadStatus; intent?: LeadIntent; sort?: "score" | "recent"; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.intent) q.set("intent", params.intent);
    if (params?.sort) q.set("sort", params.sort);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    const qs = q.toString();
    return api<LeadList>(`/v1/leads${qs ? `?${qs}` : ""}`);
  },
  digest: (limit: number = 5) => api<Lead[]>(`/v1/leads/digest?limit=${limit}`),
  create: (body: LeadCreate) =>
    api<Lead>(`/v1/leads`, { method: "POST", body: JSON.stringify(body) }),
  get: (id: number) => api<Lead>(`/v1/leads/${id}`),
  patch: (id: number, body: LeadPatch) =>
    api<Lead>(`/v1/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  sendMessage: (
    id: number,
    text: string,
    opts?: { subject?: string; channel?: SendChannel },
  ) =>
    api<HumanMessageResult>(`/v1/leads/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, subject: opts?.subject, channel: opts?.channel }),
    }),
  suggestions: (id: number, count: number = 3) =>
    api<SuggestionsResult>(`/v1/leads/${id}/suggestions`, {
      method: "POST",
      body: JSON.stringify({ count }),
    }),
  matches: (id: number, limit: number = 6) =>
    api<Property[]>(`/v1/leads/${id}/matches?limit=${limit}`),
};

export const conversationsApi = {
  get: (leadId: number) => api<Conversation>(`/v1/conversations/${leadId}`),
  timeline: (leadId: number) => api<Timeline>(`/v1/conversations/${leadId}/timeline`),
};

export type InboxFilter = "pending" | "booked" | "all" | "attention";

export interface InboxItem {
  lead_id: number;
  name: string | null;
  identifier: string;
  status: LeadStatus;
  intent: LeadIntent | null;
  zone: string | null;
  score: number;
  tier: "hot" | "warm" | "cold";
  human_takeover: boolean;
  channels: string[];
  last_message_at: string | null;
  last_direction: MessageDirection | null;
  last_channel: string | null;
  last_preview: string | null;
  needs_response: boolean;
  needs_attention: boolean;
  has_visit: boolean;
  next_visit_at: string | null;
  visit_status: VisitStatus | null;
  handled_at: string | null;
}

export interface InboxList {
  items: InboxItem[];
  pending_count: number;
  booked_count: number;
  attention_count: number;
}

export interface InboxCount {
  pending: number;
  booked: number;
  attention: number;
}

export const inboxApi = {
  list: (params?: { filter?: InboxFilter; channel?: string }) => {
    const q = new URLSearchParams();
    if (params?.filter) q.set("filter", params.filter);
    if (params?.channel) q.set("channel", params.channel);
    const qs = q.toString();
    return api<InboxList>(`/v1/inbox${qs ? `?${qs}` : ""}`);
  },
  count: () => api<InboxCount>(`/v1/inbox/count`),
  markHandled: (leadId: number) =>
    api<InboxCount>(`/v1/inbox/${leadId}/handled`, { method: "POST" }),
  unmarkHandled: (leadId: number) =>
    api<InboxCount>(`/v1/inbox/${leadId}/handled`, { method: "DELETE" }),
};

export type Role = "admin" | "member" | "viewer";

export interface MeResult {
  authenticated: boolean;
  auth_enabled: boolean;
  role?: Role;
  google_signin_enabled?: boolean;
  apple_signin_enabled?: boolean;
  registration_enabled?: boolean;
  /** Runs the platform, not an agency. Operator-only controls key off this. */
  is_platform_operator?: boolean;
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
  phone?: string;
  address?: string;
  state?: string;
  country?: string;
  company?: string;
}

export const authApi = {
  me: () => api<MeResult>(`/v1/auth/me`),
  login: (password: string) =>
    api<{ ok: boolean; auth_enabled?: boolean }>(`/v1/auth/login`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  loginGoogle: (idToken: string) =>
    api<{ ok: boolean; auth_enabled?: boolean }>(`/v1/auth/login/google`, {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    }),
  loginApple: (idToken: string) =>
    api<{ ok: boolean; auth_enabled?: boolean }>(`/v1/auth/login/apple`, {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    }),
  loginAccount: (email: string, password: string) =>
    api<{ ok: boolean; role: Role; auth_enabled?: boolean }>(`/v1/auth/login/account`, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (payload: RegisterPayload) =>
    api<{ ok: boolean; role: Role; auth_enabled?: boolean }>(`/v1/auth/register`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: () => api<{ ok: boolean }>(`/v1/auth/logout`, { method: "POST" }),
};

export interface TeamMember {
  email: string;
  role: Role;
  added_by: string | null;
  created_at: string;
  immutable: boolean;
}

export const teamApi = {
  list: () => api<TeamMember[]>(`/v1/team`),
  add: (email: string, role: Role) =>
    api<TeamMember>(`/v1/team`, { method: "POST", body: JSON.stringify({ email, role }) }),
  updateRole: (email: string, role: Role) =>
    api<TeamMember>(`/v1/team/${encodeURIComponent(email)}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
  remove: (email: string) =>
    api<{ ok: boolean }>(`/v1/team/${encodeURIComponent(email)}`, { method: "DELETE" }),
};

export interface DemoAccount {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  company: string | null;
  address: string | null;
  state: string | null;
  country: string | null;
  role: string;
  created_at: string;
}

export const accountsApi = {
  list: () => api<DemoAccount[]>(`/v1/team/accounts`),
  remove: (id: number) => api<{ ok: boolean }>(`/v1/team/accounts/${id}`, { method: "DELETE" }),
  setRole: (id: number, role: "viewer" | "member") =>
    api<DemoAccount>(`/v1/team/accounts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
};

export interface UserActivity {
  email: string;
  source: string | null;
  first_seen: string;
  last_seen: string;
  login_count: number;
  request_count: number;
  active_days: number;
  top_sections: { section: string; count: number }[];
  device: string | null;
  last_ip: string | null;
}

export const activityApi = {
  list: () => api<UserActivity[]>(`/v1/team/activity`),
};

export interface FunnelStep {
  stage: string;
  count: number;
  /** Against the step above, not against the top. "Half the people who reached
   *  the form sent it" is actionable; "3% of visitors sent it" is not. */
  pct_of_previous: number | null;
}

export interface Breakdown {
  name: string;
  sessions: number;
  leads: number;
}

export interface Analytics {
  range: { from: string; to: string; timezone: string };
  traffic: {
    sessions: number;
    engaged: number;
    avg_scroll_pct: number;
    cta_clicks: number;
    tel_clicks: number;
    form_starts: number;
    form_submits: number;
    by_day: { date: string; sessions: number }[];
    by_source: Breakdown[];
    by_device: Breakdown[];
    by_in_app: Breakdown[];
    by_country: Breakdown[];
    by_region: Breakdown[];
    by_city: Breakdown[];
    by_lang: Breakdown[];
    sections: Record<string, number>;
  };
  funnel: FunnelStep[];
  leads: {
    total: number;
    by_status: Record<string, number>;
    by_intent: Record<string, number>;
    by_channel: Record<string, number>;
    /** `no_web` is a lead that never touched the landing page — imported,
     *  phoned in, found by discovery. Not the same as `direct`. */
    by_source: Record<string, number>;
    new_by_day: { date: string; leads: number }[];
  };
  response: {
    first_response_seconds: { median: number | null; p90: number | null; avg: number | null };
    /** `fallback` is the canned reply sent when no model answered. Folded into
     *  `ai` it would hide an outage behind a healthy response time. */
    by_kind: Record<string, number>;
    unanswered: number;
  };
  calls: {
    inbound: number;
    avg_duration_seconds: number | null;
    by_ended_reason: Record<string, number>;
    logged: number;
    by_outcome: Record<string, number>;
  };
  appointments: {
    set: number;
    completed: number;
    no_show: number;
    cancelled: number;
    by_purpose: Record<string, number>;
  };
  deals: {
    won: number;
    by_kind: Record<string, number>;
    /** null for anyone who is not an admin. */
    total_value: number | null;
    median_days_lead_to_won: number | null;
    lost: number;
    lost_reasons: Record<string, number>;
    close_rate: number;
  };
  content: {
    piece_id: number;
    platform: string;
    published_at: string;
    external_url: string | null;
    /** **Association, not attribution.** What happened in the 48 hours after
     *  this went out. A Shorts description link is not clickable and Instagram
     *  strips the referrer, so most viewers arrive indistinguishable from
     *  anyone else. The page must never label this "attribution". */
    association: { window_hours: number; sessions: number; leads: number };
    leads_tagged: number;
    /** How many people actually watched. This one IS a measurement — it is the
     *  platform's own counter — which is why it sits apart from `association`.
     *  Null when nobody has read it: no key, no address, or a network whose
     *  number has not been typed in yet. */
    views: { count: number | null; captured_on: string; source: string } | null;
  }[];
  by_agent: { email: string; calls_logged: number; appointments: number; won: number }[];
}

export type AnalyticsRange = "7d" | "30d" | "90d";

export const analyticsApi = {
  get: (opts?: { range?: AnalyticsRange } | { from: string; to: string }) => {
    const q = new URLSearchParams();
    if (opts && "from" in opts) {
      q.set("from", opts.from);
      q.set("to", opts.to);
    } else if (opts?.range) {
      q.set("range", opts.range);
    }
    const qs = q.toString();
    return api<Analytics>(`/v1/analytics${qs ? `?${qs}` : ""}`);
  },
};

export type LeadCategory =
  | "fsbo"
  | "expired"
  | "absentee"
  | "preforeclosure"
  | "high_equity"
  | "investor_llc"
  | "renter";

export const SELLER_CATEGORIES: LeadCategory[] = ["fsbo", "expired", "absentee", "preforeclosure", "high_equity"];
export const BUYER_CATEGORIES: LeadCategory[] = ["investor_llc", "renter"];

export interface BusinessLead {
  business_name: string;
  source: string;
  category: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  motivation: string | null;
  timeline: string | null;
  property_type: string | null;
  est_value: string | null;
}

export interface DiscoverySearchIn {
  category: LeadCategory;
  query: string;
  city: string;
  state: string;
  max_results: number;
}

export interface ImportResult {
  created: number;
  skipped: number;
  total: number;
  lead_ids: number[];
}

export interface EnrichResult {
  lead_id: number;
  name: string | null;
  enrichment: Record<string, unknown>;
}

export const discoveryApi = {
  search: (body: DiscoverySearchIn) =>
    api<{ results: BusinessLead[] }>(`/v1/discovery/search`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  import: (leads: BusinessLead[], source_label = "discovery") =>
    api<ImportResult>(`/v1/discovery/import`, {
      method: "POST",
      body: JSON.stringify({ leads, source_label }),
    }),
  enrich: (leadId: number) =>
    api<EnrichResult>(`/v1/discovery/enrich/${leadId}`, { method: "POST" }),
  // Upload bypasses api() — multipart/form-data must NOT carry a JSON Content-Type.
  upload: async (file: File): Promise<{ results: BusinessLead[] }> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/v1/discovery/upload`, { method: "POST", body: fd, cache: "no-store" });
    if (!res.ok) {
      throw new Error(`API ${res.status}: ${await errorDetail(res)}`);
    }
    return res.json();
  },
};

// ── Public capture form ──────────────────────────────────────────────────
// Bypasses api() deliberately: that helper throws a string-formatted Error and
// the contact form needs the STATUS to tell a visitor the truth. "Too many
// submissions" and "we could not verify you are human" are different problems
// with different fixes, and collapsing both into "something went wrong" is how
// a form quietly stops converting.
export type CaptureOutcome =
  | { ok: true }
  | { ok: false; reason: "contact" | "email" | "rate" | "captcha" | "generic" };

/**
 * What /calculator sends along with the form: the three inputs and the
 * sliders the visitor moved — never the result. Mirrors `CalculatorIn` on the
 * server, which recomputes everything before storing it.
 */
export interface CalculatorPayload {
  rent: number;
  savings: number;
  credit: CalculatorCredit;
  appreciation?: number;
  rent_growth?: number;
  rate?: number;
  hoa_monthly?: number;
  lang?: "en" | "es";
}

export interface CapturePayload {
  form?: string;
  name?: string;
  email?: string;
  phone?: string;
  message?: string;
  consent: boolean;
  consent_text?: string;
  utm?: Record<string, string>;
  /** The landing visit this submission came from, when the tracker is
   *  running. Joins the lead to what the visitor did before writing. */
  session_id?: string;
  turnstile_token?: string;
  website?: string;
  /** Present only when the form sits under /calculator. */
  calculator?: CalculatorPayload;
}

export async function submitPublicLead(payload: CapturePayload): Promise<CaptureOutcome> {
  let res: Response;
  try {
    res = await fetch(`/api/v1/public/leads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return { ok: false, reason: "generic" };
  }
  if (res.ok) return { ok: true };
  if (res.status === 429) return { ok: false, reason: "rate" };
  if (res.status === 400) return { ok: false, reason: "captcha" };
  if (res.status === 422) {
    // 422 is one of our own refusals (`contact_required`, `email_required`,
    // `consent_text_required`) or a pydantic body rejection. The first two are
    // things the visitor can fix and deserve their own words — `email_required`
    // used to fall through to "something went wrong", which told a phone-only
    // submitter nothing while the fix was one field away.
    const detail = await errorDetail(res);
    if (detail.includes("email_required")) return { ok: false, reason: "email" };
    return { ok: false, reason: detail.includes("contact_required") ? "contact" : "generic" };
  }
  return { ok: false, reason: "generic" };
}

export interface LeadEvent {
  type: string;
  at: string;
  actor: string | null;
  from_status: string | null;
  to_status: string | null;
  /** `recording_url` is stripped for anyone who is not an admin. */
  meta: Record<string, unknown> | null;
}

export const leadEventsApi = {
  /** Oldest first: this is read as a story, unlike the calls list beside it,
   *  which is a worklist and runs newest first. */
  list: (leadId: number) => api<LeadEvent[]>(`/v1/leads/${leadId}/events`),
};
