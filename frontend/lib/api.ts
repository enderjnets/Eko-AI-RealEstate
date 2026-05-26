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
  name: string | null;
  status: LeadStatus;
  intent: LeadIntent | null;
  budget_min: string | null; // Decimal serializes as string in JSON
  budget_max: string | null;
  zone: string | null;
  property_type: string | null;
  urgency: string | null;
  human_takeover: boolean;
  score: number;
  score_breakdown: {
    components?: Record<string, number>;
    base?: number;
    status_gate?: number;
    status?: string;
    tier?: "hot" | "warm" | "cold";
  };
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
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`API ${res.status}: ${detail || res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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
  lead_id: number;
  calendar_provider: string;
  external_booking_id: string;
  status: VisitStatus;
  scheduled_at: string;
  duration_minutes: number;
  timezone: string;
  property_address: string | null;
  meeting_url: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface BookingIn {
  start_time: string;
  duration_minutes?: number;
  property_address?: string;
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
};

export interface AgencySettings {
  agency_name: string;
  agency_phone: string | null;
  agent_persona: string;
  greeting_template: string;
  languages: string[];
  business_hours: Record<string, { open: string; close: string } | null>;
  created_at: string;
  updated_at: string;
}

export interface AgencySettingsPatch {
  agency_name?: string;
  agency_phone?: string | null;
  agent_persona?: string;
  greeting_template?: string;
  languages?: string[];
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
  get: (id: number) => api<Lead>(`/v1/leads/${id}`),
  patch: (id: number, body: LeadPatch) =>
    api<Lead>(`/v1/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  sendMessage: (id: number, text: string, subject?: string) =>
    api<HumanMessageResult>(`/v1/leads/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, subject }),
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
};

export interface MeResult {
  authenticated: boolean;
  auth_enabled: boolean;
}

export const authApi = {
  me: () => api<MeResult>(`/v1/auth/me`),
  login: (password: string) =>
    api<{ ok: boolean; auth_enabled?: boolean }>(`/v1/auth/login`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => api<{ ok: boolean }>(`/v1/auth/logout`, { method: "POST" }),
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
