/**
 * Reading and saving a partner brief.
 *
 * Its own module rather than another entry in `lib/api.ts`, because nothing
 * here shares that file's assumptions: a brief has no session, no org header
 * and no captcha, and its credential is the token already in the path. Mixing
 * it in would invite a future edit to wrap it in the panel's auth handling.
 *
 * The types below are the contract between `scripts/create_brief.py`'s payload
 * and the page that renders it. They are deliberately loose — every field
 * optional, unknown `kind` ignored by the renderer — because a brief written
 * next month will carry blocks this build has never heard of, and the page
 * that meets one must drop it rather than break.
 */

export interface BriefField {
  id: string;
  label: string;
  hint?: string;
  /** One line instead of a box. For an answer that is a date or a yes. */
  single?: boolean;
}

export interface BriefPerson {
  /** Stable key for the answer. Never the array index: reordering the list
   *  between drafts would silently reassign every verdict she gave. */
  id: string;
  name: string;
  detail?: string;
  meta?: string;
  /** A short warning shown on the row, e.g. where the mail actually goes. */
  flag?: string;
}

export interface BriefBlock {
  kind:
    | "plan"
    | "asks"
    | "prose"
    | "questions"
    | "people"
    | "letter"
    | "doc"
    | "colophon";
  /** Also the anchor the index jumps to, and the key answers are filed under. */
  id?: string;
  kicker?: string;
  heading?: string;
  body?: string[];
  lede?: boolean;

  card?: string[];
  cardStyle?: "tint" | "flag";

  groups?: { label?: string; steps?: string[]; body?: string[] }[];
  items?: { label: string; who?: string; anchor?: string }[];
  fields?: BriefField[];

  people?: BriefPerson[];
  labels?: { go?: string; touch?: string; out?: string };
  actions?: {
    out?: string;
    touch?: string;
    name?: string;
    namePrompt?: string;
    copy?: string;
  };
  states?: { go?: string; touch?: string; out?: string };
  note?: string[];

  letter?: string;
  choiceLabel?: string;
  choices?: { value: string; label: string }[];

  docs?: { title: string; subtitle?: string; href: string; icon?: string }[];
  signature?: string;
}

export interface BriefPayload {
  eyebrow?: string;
  headline?: string;
  standfirst?: string;
  blocks?: BriefBlock[];
}

export interface Brief {
  title: string;
  recipient: string;
  payload: BriefPayload;
  answers: Record<string, unknown>;
  answered_at: string | null;
}

function url(token: string): string {
  return `/api/v1/public/brief/${encodeURIComponent(token)}`;
}

/** The brief, or null when there is no such token — which is also the answer
 *  for a token that exists somewhere else. There is nothing to tell apart. */
export async function loadBrief(token: string): Promise<Brief | null> {
  try {
    const res = await fetch(url(token), { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Brief;
  } catch {
    return null;
  }
}

/** True when the answers are durable. False means *try again* — never shown
 *  as "saved", because a person who believes they saved stops.
 *
 *  `notify` says this save was a deliberate press of the button rather than
 *  the autosave timer. The server decides what to do with that; the page's
 *  job is only to be honest about which kind of save this was. */
export async function saveBrief(
  token: string,
  answers: Record<string, unknown>,
  notify = false,
): Promise<boolean> {
  try {
    const res = await fetch(url(token), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers, notify }),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}
