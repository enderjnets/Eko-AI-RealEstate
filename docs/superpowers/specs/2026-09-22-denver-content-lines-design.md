# Denver content lines design

## Goal

Run a seven-day English editorial system that grows the Denver Home Story social audience while preserving the existing conversion rail and every post already scheduled in Buffer.

The active weekly mix is:

| Day (Denver) | Series | Objective | CTA |
|---|---|---|---|
| Monday | Denver, Decoded | Growth | Follow, comment, or share |
| Tuesday | Conversion | Site action | Denver Home Story or the seeded calculator |
| Wednesday | Denver, Decoded | Growth | Follow, comment, or share |
| Thursday | Denver Market, No Hype | Authority | Follow for the next sourced update |
| Friday | Denver, Decoded | Growth | Follow, comment, or share |
| Saturday | Denver Weekend | Growth | Save or share |
| Sunday | Conversion | Site action | Denver Home Story or the seeded calculator |

`Ask Denver Home Story` is represented as a series but disabled. Once the agents record answers, a feature flag alternates it with `Denver Market, No Hype` on Thursdays.

## Alternatives considered

1. **Prompt labels only.** Cheapest change, but the label disappears before rendering, publishing and analytics, so the wrong CTA can still be attached and results cannot be separated.
2. **Choose a prompt from the current weekday.** Simple, but an existing Buffer backlog shifts the actual publication day and destroys the intended cadence.
3. **Persist the series and editorial date end to end.** More schema work, but it preserves the objective through approval, rendering, scheduling and measurement. This is the selected design.

## Data model

Every content piece gains:

- `series`: `conversion`, `denver_decoded`, `denver_weekend`, `denver_market_no_hype`, or `ask_denver_home_story`.
- `editorial_date`: the intended Denver-local publication date for new generated pieces.
- `source`: nullable structured provenance. Market pieces store the official source name, report title, publication date and URL.

Existing rows migrate to `conversion` with no editorial date or source. This keeps all prior approved, scheduled and published pieces semantically unchanged.

## Calendar and Buffer preservation

The writer finds the latest of:

- today in the agency timezone;
- the latest locally known Buffer `scheduled_at` date;
- the latest active piece's existing `publish_window_start`, including an
  approved or publishing piece Buffer has not assigned a slot yet;
- the latest `editorial_date` already reserved by the writer.

It reserves the following day when a future date already exists, otherwise today. The series comes from that reserved date. The piece's `publish_window_start` receives the same date so the existing publisher cannot place it earlier. The publisher still searches its existing per-platform free slots and never mutates, deletes, or duplicates a Buffer post.

The writer keeps at most seven active new-line dates waiting at once. This is
one weekly mix: enough to review ahead without an hourly loop filling months of
unapproved content. Rejected dates leave the active backlog and can be reused.

If the next Thursday lacks a current verified market source, that date is skipped and the writer advances to the next eligible date. It does not create an unsourced authority draft.

## Editorial contracts

Contracts are trusted server data, never model output.

### Conversion

- 45–65 model-written words before the deterministic spoken sign-off.
- 7–9 distinct scenes.
- Finished duration 20–35 seconds.
- Deterministic site or seeded calculator CTA.

### Denver, Decoded

- English only.
- 25–35 words and 5–6 distinct scenes. This range is grounded in the measured
  DHS narrator rate so the finished copy plus deterministic CTA lands near the
  12–18 second target.
- Finished duration 12–18 seconds.
- 0–2 seconds: immediate local question or visual contrast.
- 2–10 seconds: two choices, one curiosity, or one local decision.
- 10–14 seconds: reveal and short explanation.
- Exactly one social CTA: follow, comment, or share.
- No calculator, form, URL, phone number, valuation, appointment, or sales pitch.

### Denver Weekend

- Same duration and production limits as Denver, Decoded.
- Current, locally useful Saturday idea.
- One save-or-share CTA.
- No sales CTA.

### Denver Market, No Hype

- Same short production limits.
- The brief must come from the newest official DMAR market report and be no more than 45 days old.
- The source name and publication date are added deterministically to the caption and final card.
- No number or claim outside the fetched source summary.
- One follow CTA.

### Ask Denver Home Story

- Disabled until an agent-recording workflow is enabled.
- It is never synthesized as if Natalia or Robbie answered a question.

## Rendering and publishing

The render-job payload carries the contract bounds and final-card copy for the persisted series. The ROG worker validates those bounds instead of applying the conversion limits globally.

The conversion rail continues to require a Denver Home Story link before Buffer accepts it. Growth and authority pieces are intentionally link-free and pass only when their deterministic social CTA is present. Brokerage identification and the AI disclosure remain mandatory on every generated advertisement.

## Approval UI and measurement

The Content page shows a visible series badge, objective, editorial date and source. Reviewers can therefore judge whether the script and CTA match the intended job.

The API exposes the series on each piece so existing platform metrics can be grouped without heuristics. The first 21-day evaluation separates the lines. Available metrics remain factual: views, likes and comments from the connected sources. Follows, shares, retention and profile visits are reported only where a connected platform supplies them; no proxy is invented.

## Failure behavior

- DMAR unavailable, malformed or stale: skip the authority date and log the reason.
- Existing queue extends into the future: start after it.
- Approval is late: never publish earlier than the editorial date; use the next free slot.
- Old worker sees a new payload: additive fields retain conversion-compatible defaults.
- Ask flag enabled without recorded input: skip the slot rather than fabricate an answer.
