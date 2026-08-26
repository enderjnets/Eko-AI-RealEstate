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
  channel: string; // channel of this message's conversation (for mixed timelines)
  llm_provider: string | null;
  llm_model: string | null;
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

export interface ContentPublication {
  id: number;
  platform: string;
  status: string;
  external_id: string | null;
  published_at: string | null;
  last_error: string | null;
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
  violations: { phrase: string; category: string }[] | null;
  approved_by: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  created_at: string;
  updated_at: string;
  publications: ContentPublication[];
}

export const contentApi = {
  list: (status?: ContentStatus) =>
    api<ContentPiece[]>(
      status ? `/v1/content?status=${status}` : `/v1/content`,
    ),
  edit: (id: number, body: { hook?: string; script?: string; caption?: string }) =>
    api<ContentPiece>(`/v1/content/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  submit: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/submit`, { method: "POST" }),
  approve: (id: number) =>
    api<ContentPiece>(`/v1/content/${id}/approve`, { method: "POST" }),
  reject: (id: number, reason: string) =>
    api<ContentPiece>(`/v1/content/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  /** The clip itself, behind the same auth as everything else. */
  mediaUrl: (id: number) => `/api/v1/content/${id}/media`,
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

export interface Analytics {
  total_leads: number;
  funnel: Record<string, number>;
  conversion_rate: number;
  by_channel: Record<string, number>;
  by_score_tier: Record<string, number>;
  leads_per_day: { date: string; count: number }[];
  avg_first_response_seconds: number | null;
}

export const analyticsApi = {
  get: () => api<Analytics>(`/v1/analytics`),
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
  | { ok: false; reason: "contact" | "rate" | "captcha" | "generic" };

export interface CapturePayload {
  form?: string;
  name?: string;
  email?: string;
  phone?: string;
  message?: string;
  consent: boolean;
  consent_text?: string;
  utm?: Record<string, string>;
  turnstile_token?: string;
  website?: string;
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
    // 422 is either our own `contact_required` / `consent_text_required` or a
    // pydantic body rejection. Only the first is worth a specific message —
    // the others mean the page sent something the form should not have built.
    const detail = await errorDetail(res);
    return { ok: false, reason: detail.includes("contact_required") ? "contact" : "generic" };
  }
  return { ok: false, reason: "generic" };
}
