/**
 * What the brief's Send button can do, and what the page says it just did.
 *
 * Both halves of this were wrong at once, and the bug was invisible from the
 * inside because the answers were never in danger — only the signal was.
 *
 * ── The measurement ──────────────────────────────────────────────────────
 * On 16-sep-2026 Natalia wrote: "I did send it press" / "It only did save".
 * The backend agreed with her. Between the container starting at 18:14 UTC
 * and her message there was one GET on `/public/brief/<token>` and **zero
 * POSTs**: she opened the page, pressed the button, and not a single request
 * left the browser.
 *
 * The button was `disabled={saving || !dirty}`. The autosave writes 1,200 ms
 * after the last tap and clears `dirty`, and a freshly loaded page is not
 * dirty either — so the button was dead on arrival and, after any edit, alive
 * for about a second. She was not confused; it really did nothing.
 *
 * ── Why `!dirty` was the wrong question ──────────────────────────────────
 * It is the right guard for a button that means *save my changes*, and this
 * one does not. It means **"I am done"**, which is a thing a person can say
 * about answers they wrote yesterday, or about a brief they read and had
 * nothing to add to. `PartnerBrief` already says so: "read it and had nothing
 * to say" is one of the two states `opened_at` exists to tell apart. There is
 * no state of this page in which "I am done" is not worth hearing, so the
 * only reason to refuse the press is a save already in flight.
 *
 * ── And the word it answers with ─────────────────────────────────────────
 * Fixing the button alone would have left the other half. A deliberate press
 * used to land on the same "Saved" the autosave had already been showing for
 * a second, so even a working button looked like it had ignored her. A press
 * that means "I am done" has to be answered with a different word, or the
 * person presses again — which is exactly what happened.
 */

/** Everything the page knows when it decides. */
export interface BriefSendInput {
  /** A write is in flight right now. */
  saving: boolean;
  /** Something has been changed and not yet written. */
  dirty: boolean;
  /** The last write failed. */
  failed: boolean;
  /** A deliberate press has landed, and nothing has been touched since. */
  sent: boolean;
  /** Anything has ever been written — from this session or a previous one. */
  everSaved: boolean;
}

/** The i18n key the status line shows. */
export type BriefStatusKey =
  | "brief.saveFailed"
  | "brief.saving"
  | "brief.unsaved"
  | "brief.sent"
  | "brief.saved"
  | "brief.untouched";

export interface BriefSendDecision {
  /** Whether the Send button can be pressed. */
  enabled: boolean;
  status: BriefStatusKey;
}

export function briefSend(input: BriefSendInput): BriefSendDecision {
  const { saving, dirty, failed, sent, everSaved } = input;

  // The whole fix. `dirty` decides what the status SAYS; it never decides
  // whether a person is allowed to tell us they have finished.
  const enabled = !saving;

  // Order matters and each step earns its place: a failure outranks
  // everything because it is the only one that asks for another press;
  // `dirty` outranks `sent` because an edit after sending means the thing we
  // were told about is no longer what is on screen.
  let status: BriefStatusKey;
  if (failed) status = "brief.saveFailed";
  else if (saving) status = "brief.saving";
  else if (dirty) status = "brief.unsaved";
  else if (sent) status = "brief.sent";
  else if (everSaved) status = "brief.saved";
  else status = "brief.untouched";

  return { enabled, status };
}
