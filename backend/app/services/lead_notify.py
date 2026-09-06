"""New-lead notice to the agency — the interim funnel's second half.

The public form used to end in silence on the agency side: the lead row
appeared in the panel and nobody was told it existed. That was fine while the
form was one channel among several; it is not fine now that the funnel is
"visitor fills the form → the agent calls them back within a few hours". If
nobody hears about the lead, the promise on the page is false.

So: one notice per captured submission, carrying everything needed to make the
call — name, phone, email, what they said, and where they came from, plus a
link straight to the lead in the panel.

**Two origins, one recipient, one link.** The form was the only one for a long
time, and the phone was the hole: Clara answers a call, the transcript and the
summary land in the panel, and nobody is told. A caller who spoke to an
assistant and never hears back is worse off than one who reached voicemail, and
the product had no way to know the difference. `origin="call"` is that second
origin — same mailbox, same Telegram, a subject that says which one it was.

The link (`PANEL_URL/leads/<id>`) exists because the notice used to be a dead
end: everything needed to make the call, and no way to reach the conversation
it is about. It is omitted entirely when `PANEL_URL` is empty rather than
rendered as `https:///leads/12`, which is what a naive f-string produces on the
default install.

**Two transports, not one, and the reason is measured.** It went by email
alone until a real submission on 5-Sep-2026 proved that is not enough: Resend
accepted the send, reported `last_event: delivered`, the product recorded
`delivery_status=sent` with a message id and no error — and the mail never
appeared in the destination mailbox, spam and trash included. Every layer said
success and a human was still never told. The LLM monitor has had a second
transport since the safety-net work for exactly this reason; a LEAD is worth at
least what an infrastructure alarm is worth. Telegram is the backup because it
is already configured, already used by this product, and does not share a
failure mode with email.

Modelled on `visit_invite.py`, which already solved the hard parts:

* The notice is sent AFTER the capture commit and can never break it — a
  notification failure costs the notification, never the lead.
* On success the notice is recorded in the lead's thread as an
  ``internal=True`` message, which keeps it out of the delivery sweep and out
  of the LLM's history by construction (the v0.60 mechanism).
* The record is written after the send, never before: a PENDING row written
  first is exactly what the delivery sweep would re-send to the LEAD.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.services.calculator import summary_line
from app.services.email import send_email
from app.services.telegram_notify import send_operator_telegram, undeliverable_reason

log = logging.getLogger("app.lead_notify")


def _calculator_line(lead: object) -> str | None:
    """The one-line summary of what they calculated, or None. A malformed
    snapshot must not cost the notice: the number is a courtesy, the lead is
    the point."""
    snapshot = getattr(lead, "calculator_snapshot", None)
    if not isinstance(snapshot, dict):
        return None
    try:
        return summary_line(snapshot)
    except (KeyError, TypeError, ValueError):
        return None


def _line(label: str, value: str | None) -> str:
    return f"{label}: {value}\n" if value else ""


def _spoken_duration(seconds: float | None) -> str | None:
    """`m:ss`, or None when the provider did not say.

    None and 0 both mean "no number to show" and both must produce no line: a
    literal "Duration: None" in a notice is the kind of detail that makes a
    human distrust the rest of the message.

    `OverflowError` is in the list because `1e400` is a valid JSON number that
    parses to `inf`, and `int(float("inf"))` raises it — a class `ValueError`
    does not cover. This runs before either transport, so that one field would
    have cost the email, the Telegram backup AND the row that records the
    attempt: the whole notice, for a number that is a courtesy.
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError, OverflowError):
        return None
    if total <= 0:
        return None
    return f"{total // 60}:{total % 60:02d}"


def _panel_link(lead_id: int) -> str | None:
    """The lead's page in the panel, or None when no panel URL is configured.

    Read here rather than passed in, so both origins get it by construction and
    a third one cannot forget.
    """
    from app.config import get_settings

    base = (get_settings().PANEL_URL or "").strip().rstrip("/")
    return f"{base}/leads/{lead_id}" if base else None


async def _notify_agency_by_email(
    to: str, subject: str, body: str, lead_id: int
) -> tuple[str | None, str | None]:
    """Mail the booking mailbox. Returns `(provider id, failure)`; never raises.

    A module-level function with a name that says who it addresses, rather than
    a closure called `_mail`: both AST sweeps name what they exempt, and a
    generic name in a security table is one a future unrelated `_mail`
    inherits by accident.
    """
    try:
        result = await send_email(to=to, subject=subject, body_text=body)
        external_id = (result or {}).get("id")
        if external_id:
            log.info("Lead %d: new-lead notice sent to the agency", lead_id)
            return external_id, None
        failure = "the provider accepted the send but returned no id"
        log.error("Lead %d: %s", lead_id, failure)
        return None, failure
    except TimeoutError:
        failure = "the email provider did not answer in time (the send may still complete)"
        log.error("Lead %d: %s", lead_id, failure)
        return None, failure
    except Exception as exc:  # noqa: BLE001
        log.error("Lead %d: new-lead notice failed to send: %s", lead_id, exc)
        return None, str(exc)[:500]


async def _notify_agency_by_telegram(subject: str, body: str, lead_id: int) -> bool:
    """The backup transport, to the owner's OWN chat. Never raises.

    A backup that can break the primary path is not a backup, so every failure
    here is a log line and a `False`.
    """
    blocked = undeliverable_reason()
    if blocked:
        log.info("Lead %d: telegram backup unavailable (%s)", lead_id, blocked)
        return False
    try:
        return bool(await send_operator_telegram(subject, body))
    except Exception as exc:  # noqa: BLE001
        log.error("Lead %d: telegram backup failed: %s", lead_id, exc)
        return False


async def send_new_lead_notice(
    lead_id: int,
    message_id: int | None,
    *,
    origin: str = "form",
    conversation_id: int | None = None,
    call: dict | None = None,
) -> None:
    """Email the agency about a lead that just arrived. Never raises.

    Reads everything on its own throwaway session (org inherited from the
    request's ContextVar, the same mechanism `pick_agent_safely` relies on),
    so it cannot poison the caller's transaction and needs nothing from it.

    The three extras are KEYWORD-ONLY and all default to today's behaviour, so
    the form's call site — the funnel's only conversion point — did not have to
    change to gain a second origin:

    * `origin` — `"form"` or `"call"`; picks the subject and the body.
    * `conversation_id` — which thread files the internal copy when there is no
      inbound message to hang it on. A call has a transcript, not a message the
      form posted, so `message_id` is None and this is how the note reaches the
      voice thread instead of being dropped.
    * `call` — `duration_seconds` and `summary` for the call body. Passed in
      rather than re-read, because the report is the authority on what was
      said and it is already in the webhook's hand.
    """
    try:
        await _send_and_record(
            lead_id, message_id, origin=origin, conversation_id=conversation_id, call=call
        )
    except Exception as exc:  # noqa: BLE001 — the lead is already captured
        log.error("Lead %d: new-lead notice failed: %s", lead_id, exc)


async def _send_and_record(
    lead_id: int,
    message_id: int | None,
    *,
    origin: str = "form",
    conversation_id: int | None = None,
    call: dict | None = None,
) -> None:
    from app.db.base import get_session_factory
    from app.models import AgentSettings, Lead
    from app.models.message import (
        Message,
        MessageDirection,
        MessageSender,
        MessageStatus,
    )
    from app.services.capture import ATTRIBUTION_KEYS, normalize_phone
    from app.services.delivery import MAX_ATTEMPTS
    from app.services.tenant_context import get_org_id

    async with get_session_factory()() as db:
        lead = (
            await db.execute(select(Lead).where(Lead.id == lead_id))
        ).scalar_one_or_none()
        if lead is None:
            log.warning("Lead %d: vanished before the notice could be built", lead_id)
            return
        cfg = (
            await db.execute(
                select(AgentSettings).where(AgentSettings.org_id == get_org_id())
            )
        ).scalar_one_or_none()
        to = ((getattr(cfg, "booking_contact_email", None) or "").strip()) or None
        if not to:
            # Same posture as visit_invite: an empty contact address is a
            # configuration gap somebody has to fix, not a silent no-op.
            log.warning(
                "Lead %d: booking_contact_email is empty in Settings, so nobody "
                "was told about the new lead",
                lead_id,
            )
            return

        inbound = None
        if message_id is not None:
            inbound = (
                await db.execute(select(Message).where(Message.id == message_id))
            ).scalar_one_or_none()

        # NESTED under meta["attribution"] — `_record_attribution` writes it
        # there, not at the top level. v0.60's blocker was a reader that looked
        # one level too high and returned {} for every real lead while its
        # tests passed on a shape they had fabricated themselves.
        meta = lead.meta if isinstance(lead.meta, dict) else {}
        touch = meta.get("attribution")
        touch = touch if isinstance(touch, dict) else {}
        attribution = ", ".join(
            f"{k}={touch[k]}"
            for k in sorted(ATTRIBUTION_KEYS)
            if isinstance(touch.get(k), str) and touch[k]
        )

        # `leads.phone` is the IDENTIFIER, not necessarily a phone: capture
        # stores the number when there is one and the EMAIL ADDRESS otherwise,
        # so that an SMS reply and a form post resolve to the same person.
        # Labelling it "Phone" unconditionally told the advisor to call an
        # email address, and printed the same value twice under two different
        # labels. On leads from `/fall` that is not an edge case: the form's
        # only required field is the address, so it was going to be every one
        # of them.
        identifier = (lead.phone or "").strip()
        phone = identifier if normalize_phone(identifier) else None
        # A THIRD shape, and it is neither. A web call carries no caller number,
        # so `parse_end_of_call_report` keys the lead on `voice:<call id>` — an
        # internal handle. The fallback below was written when the identifier
        # could only be a number or an address; left alone it printed
        # `Email: voice:0c3a9b12-…` and put that in the subject line, telling
        # the agent to write to a string that is not an address.
        placeholder = identifier.startswith("voice:")
        # If the identifier IS the address, it is the contact even when the
        # column is empty — losing it would leave a notice with no way to
        # answer the person it is about.
        email = (lead.email or "").strip() or (
            None if (phone or placeholder) else identifier or None
        )

        who = lead.name or phone or email or f"lead {lead.id}"
        facts = call if isinstance(call, dict) else {}
        if origin == "call":
            subject = f"New call answered by Clara — {who}"
            body = (
                "Clara answered a call.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Duration", _spoken_duration(facts.get("duration_seconds")))
                + _line("Summary", (facts.get("summary") or None))
                + _line("Came from", attribution)
                + _line("Calculator", _calculator_line(lead))
                + "\nThe full transcript and the recording are in the panel.\n"
            )
        else:
            subject = f"New lead from the website — {who}"
            body = (
                "A new inquiry just came in through the website.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Message", (inbound.content if inbound else None))
                + _line("Came from", attribution)
                + _line("Calculator", _calculator_line(lead))
                + "\nThey are expecting a call back in the next few hours.\n"
            )
        # LAST, and on its own line: it is the one thing in the mail that is
        # clicked rather than read, and a link buried mid-paragraph on a phone
        # is a link nobody presses.
        if (link := _panel_link(lead.id)) is not None:
            body += f"\nOpen in Eko AI Realtors: {link}\n"

        # ── Both transports, CONCURRENTLY ───────────────────────────────
        # ONE budget for the pair, not one each. This runs inside the public
        # form's POST — the funnel's only conversion point — and the mail
        # client waits up to 20 s on its own. Sent in series the worst case
        # would be the SUM of the two, which is how adding a safety net makes
        # the thing it protects worse: sixteen seconds of "Sending…" in front
        # of a visitor.
        #
        # Telegram is attempted whether or not the email reports success,
        # because "reports success" is precisely what proved untrustworthy: the
        # incident that put it here had an id, no error, and a provider saying
        # delivered.
        external_id: str | None = None
        failure: str | None = None
        telegram_ok = False
        try:
            # `return_exceptions=True` on top of the per-transport handlers: a
            # raise escaping here would cost the whole notice AND leave the row
            # unwritten, which is worse than either transport failing.
            results = await asyncio.wait_for(
                asyncio.gather(
                    _notify_agency_by_email(to, subject, body, lead.id),
                    _notify_agency_by_telegram(subject, body, lead.id),
                    return_exceptions=True,
                ),
                timeout=8.0,
            )
            mail_result, telegram_result = results
            if isinstance(mail_result, tuple):
                external_id, failure = mail_result
            else:
                failure = str(mail_result)[:500]
            telegram_ok = telegram_result is True
        except TimeoutError:
            failure = "no transport answered within 8s"
            log.error("Lead %d: notice transports timed out", lead.id)

        # The row states whether a human was reachable AT ALL, not whether the
        # mail worked. Recording FAILED while Telegram carried the notice would
        # send somebody chasing an outage that did not happen; recording SENT
        # when neither arrived is the lie this whole module exists to prevent.
        delivered = bool(external_id) or telegram_ok
        if failure and telegram_ok:
            failure = f"email failed ({failure}); telegram carried the notice"
        elif not delivered and not failure:
            failure = "no transport could deliver the notice"
        if not delivered:
            log.error(
                "Lead %d: NOBODY was told about this lead — both transports failed",
                lead.id,
            )

        # The thread the agency's copy is filed in. `inbound` for a form post,
        # the voice conversation for a call: without the second, every call
        # notice was dropped on the floor here, because a call has a transcript
        # rather than a message the form posted.
        thread_id = inbound.conversation_id if inbound is not None else conversation_id
        if thread_id is None:
            return
        # Written AFTER the send (see module docstring). Internal note only —
        # it is the agency's copy, never a message to the lead, so it skips the
        # Fair Housing screen the lead-facing lanes get. `last_at` and
        # `last_message_at` stay untouched: a notification is not conversation
        # activity, and bumping those clocks would move the lead in the Inbox
        # without anybody having spoken.
        db.add(
            Message(
                conversation_id=thread_id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.AGENT,
                content=body,
                subject=subject,
                internal=True,
                external_id=external_id,
                delivery_status=(
                    MessageStatus.SENT if delivered else MessageStatus.FAILED
                ),
                last_error=failure,
                # Spent on purpose when the send failed: the row then states
                # the truth — failed, not being retried — using the condition
                # the delivery sweep already honours. A blind retry here would
                # send the agency's note wherever the sweep's dispatcher
                # decides, which is the lead.
                send_attempts=0 if delivered else MAX_ATTEMPTS,
            )
        )
        await db.commit()
