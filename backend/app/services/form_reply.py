"""Clara answers the website form the same way she answers an email.

Measured in production on 2026-09-19. A real person filled the form on
denverhomestory.com. The lead was written, the agency got its notice by email
AND by Telegram, the panel showed the row — and the person who had just been
promised a call back "within a few hours" received nothing at all. Not a line.

The reason was not a bug. `public.py` sends exactly two things after a capture:
the notice to the agency, and `send_calculator_breakdown` to the visitor — and
that second one needs a `calculator_snapshot`, which somebody who filled the
form without touching the calculator does not have. Nothing was ever built for
that case, on a funnel that had measured **zero** form submissions in ninety
days. The first person to bother writing got silence.

── Why this routes through the existing pipeline ───────────────────────────
`handle_inbound_message` is channel-agnostic and already does all of it:
classify, generate the reply in the language the person wrote in, screen it
for Fair Housing, honour an opt-out, attach the compliant footer, send it
threaded so the answer comes back, and open the options request when they ask
to see places. Writing a second, simpler reply here would duplicate every one
of those and quietly miss one.

It also fixes something else by construction. `ConsultForm.tsx` says of the
chip: "it becomes the first message in the thread the advisor opens, and the
classifier reads it too." The classifier did NOT read it — the form wrote to a
`web` conversation that the pipeline never sees, so every website lead arrived
with `intent` empty and scored 0 on it. Feeding the same sentence through the
pipeline is what makes that comment true.

── What this deliberately does not do ──────────────────────────────────────
Nothing when the visitor left a calculator snapshot: they already get their own
numbers back from `send_calculator_breakdown`, and two emails within seconds of
one button is worse than one.

Nothing when there is no email address. And it never raises: the visitor has
already submitted, the lead is already durable, and a failure here must cost
the reply, never the capture.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select

log = logging.getLogger("app.form_reply")

__all__ = ["answer_the_form"]


async def answer_the_form(lead_id: int, *, message: str | None) -> bool:
    """Send Clara's first reply to a website form submission. Never raises.

    Returns True when a reply was attempted through the pipeline, False when
    this lane deliberately said nothing — which is most of the reasons it can
    end, and none of them are errors.
    """
    from app.db.base import get_session_factory
    from app.models import Lead
    from app.services._common import ParsedMessage
    from app.services.conversation import FORM_ORIGIN, handle_inbound_message

    text = (message or "").strip()
    if not text:
        return False

    try:
        async with get_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.id == lead_id))
            ).scalar_one_or_none()
            if lead is None:
                return False

            to = (lead.email or "").strip()
            if not to:
                # A phone-only submission is refused by the route before it gets
                # here, but the lane is not allowed to assume that.
                log.info("Lead %d: no address, so no reply to the form", lead_id)
                return False

            # Redundant on purpose, and it stays.
            #
            # `handle_inbound_message` already refuses: an opted-out lead gets
            # `opted_out_no_reply`, the message is stored for a human and the
            # model is never called. That is the real guard, it is older than
            # this lane, and removing THIS check leaves the suite green — which
            # is the correct outcome, not a hole. Verified by mutating the
            # pipeline's own line instead, which does turn it red.
            #
            # Kept because it is earlier and cheaper: it saves an LLM call, a
            # conversation, a message row and a commit for somebody we were
            # never going to write to. A second lock on a door that is already
            # locked costs nothing and is read by whoever edits this next.
            if lead.opted_out_at is not None:
                log.info("Lead %d: opted out, so no reply to the form", lead_id)
                return False

            if lead.calculator_snapshot is not None:
                # `send_calculator_breakdown` is already writing to them.
                log.info("Lead %d: the breakdown answers this one", lead_id)
                return False

            parsed = ParsedMessage(
                channel="email",
                # Deterministic, because `Message.external_id` is UNIQUE: a
                # double-submitted form that slipped past the duplicate filter
                # produces the same id and the insert refuses it, rather than
                # two replies to one person.
                # sha256 and not `hash()`: Python randomises string hashing per
                # process, so the "same id" would differ between the worker that
                # took the first submit and the one that took the retry — an
                # idempotency key that is only idempotent inside one process is
                # not one.
                external_id=(
                    "web-form:"
                    f"{lead_id}:"
                    f"{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
                ),
                from_identifier=to,
                from_name=lead.name,
                content=text,
                # No subject: a form has none. The pipeline's fallback writes a
                # plain one in the language the person used.
                subject=None,
                thread_id=None,
                extra={"origin": FORM_ORIGIN},
            )
            result = await handle_inbound_message(parsed, db)
            await db.commit()
            log.info("Lead %d: Clara answered the form (%s)", lead_id, result.get("status"))
            return True
    except Exception as exc:  # noqa: BLE001 — the capture already succeeded
        log.error("Lead %d: could not answer the form: %s", lead_id, exc)
        return False
