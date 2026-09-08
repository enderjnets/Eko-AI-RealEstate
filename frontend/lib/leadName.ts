/**
 * The one place a first and last name become the single `name` the API takes.
 *
 * The public form asks for two fields; `leads.name` is one column (`String(160)`,
 * `models/lead.py`) and `PublicLeadIn.name` one field capped at `MAX_NAME` = 160
 * (`services/capture.py:49`). Joining here rather than in each form keeps the
 * two callers — `ConsultForm` (used by `/`, `/fall` and `/calculator`) and
 * `/contact`, which has its own form — from drifting apart, and it is the only
 * part of this change a test can execute: this repo deliberately has no DOM in
 * vitest (`vitest.config.ts`: "deliberately NOT adding jsdom or
 * @testing-library"), so a rendered form cannot be asserted at all.
 *
 * Storing the two in one column is not a shortcut. `name` already holds whole
 * names arriving from the other channels — `services/conversation.py` fills it
 * from a WhatsApp profile's `from_name` — and every consumer treats it as a
 * label for a person: the notice's `who`, the calendar attendee, the Inbox row.
 * A second column would mean a migration on the table every lead enters, for a
 * distinction nothing reads.
 *
 * Trimming each part BEFORE joining is what makes a half that holds only spaces
 * count as empty, so `"Ana "` + `"   "` is `"Ana"` and not `"Ana "`. The double
 * space it also avoids would have been collapsed server-side anyway
 * (`capture.py` does `" ".join(value.split())`) — an earlier version of this
 * comment claimed otherwise and was wrong.
 *
 * The result is capped as well as the fields are. `maxLength` on the inputs
 * stops typing, pasting and browser autofill — all three measured — but NOT a
 * password manager assigning `input.value` directly, and in that case
 * `validity.tooLong` stays false, so nothing warns. The server does not
 * truncate an over-long name: `PublicLeadIn.name` has `max_length=MAX_NAME`,
 * which pydantic REJECTS, and a 422 loses the whole submission — email, phone,
 * TCPA consent and the calculator snapshot with it. Capping here keeps the
 * promise the form makes everywhere else: the lead is the point, the field is
 * courtesy.
 */
export function fullName(first: string, last: string): string {
  return [first, last]
    .map((s) => s.trim())
    .filter(Boolean)
    .join(" ")
    .slice(0, NAME_MAX);
}

/** `MAX_NAME` in `backend/app/services/capture.py`. Crossed by a test. */
export const NAME_MAX = 160;

/**
 * Per-field cap. Two of these plus the joining space is 159, one under the 160
 * the server accepts — so a long name is refused by the browser, in place, and
 * never becomes a 422 the form has no wording for.
 */
export const NAME_FIELD_MAX = 79;
