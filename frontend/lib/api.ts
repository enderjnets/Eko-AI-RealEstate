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

export const leadsApi = {
  list: (params?: { status?: LeadStatus; intent?: LeadIntent; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.intent) q.set("intent", params.intent);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    const qs = q.toString();
    return api<LeadList>(`/v1/leads${qs ? `?${qs}` : ""}`);
  },
  get: (id: number) => api<Lead>(`/v1/leads/${id}`),
  patch: (id: number, body: LeadPatch) =>
    api<Lead>(`/v1/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
};

export const conversationsApi = {
  get: (leadId: number) => api<Conversation>(`/v1/conversations/${leadId}`),
};
