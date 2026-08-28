"""New-lead notice to the agency — the interim funnel's second half.

The public form used to end in silence on the agency side: the lead row
appeared in the panel and nobody was told it existed. That was fine while the
form was one channel among several; it is not fine now that the funnel is
"visitor fills the form → the agent calls them back within a few hours". If
nobody hears about the lead, the promise on the page is false.

So: one email to `AgentSettings.booking_contact_email` per captured
submission, carrying everything needed to make the call — name, phone, email,
what they said, and where they came from. No link to the panel: there is no
panel-URL setting in the backend, and the email is complete without one.

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

import logging

from sqlalchemy import select

from app.services.email import send_email

log = logging.getLogger("app.lead_notify")


def _line(label: str, value: str | None) -> str:
    return f"{label}: {value}\n" if value else ""


async def send_new_lead_notice(lead_id: int, message_id: int | None) -> None:
    """Email the agency about a freshly captured form lead. Never raises.

    Reads everything on its own throwaway session (org inherited from the
    request's ContextVar, the same mechanism `pick_agent_safely` relies on),
    so it cannot poison the caller's transaction and needs nothing from it.
    """
    try:
        await _send_and_record(lead_id, message_id)
    except Exception as exc:  # noqa: BLE001 — the lead is already captured
        log.error("Lead %d: new-lead notice failed: %s", lead_id, exc)


async def _send_and_record(lead_id: int, message_id: int | None) -> None:
    from app.db.base import get_session_factory
    from app.models import AgentSettings, Lead
    from app.models.message import (
        Message,
        MessageDirection,
        MessageSender,
        MessageStatus,
    )
    from app.services.capture import ATTRIBUTION_KEYS
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

        who = lead.name or lead.phone or lead.email or f"lead {lead.id}"
        subject = f"New lead from the website — {who}"
        body = (
            "A new inquiry just came in through the website.\n\n"
            + _line("Name", lead.name)
            + _line("Phone", lead.phone)
            + _line("Email", lead.email)
            + _line("Message", (inbound.content if inbound else None))
            + _line("Came from", attribution)
            + "\nThey are expecting a call back in the next few hours.\n"
        )

        external_id: str | None = None
        failure: str | None = None
        try:
            result = await send_email(to=to, subject=subject, body_text=body)
            external_id = (result or {}).get("id")
            log.info("Lead %d: new-lead notice sent to the agency", lead.id)
        except Exception as exc:  # noqa: BLE001
            failure = str(exc)[:500]
            log.error("Lead %d: new-lead notice failed to send: %s", lead.id, exc)

        if inbound is None:
            return
        # Written AFTER the send (see module docstring). Internal note only —
        # it is the agency's copy, never a message to the lead, so it skips the
        # Fair Housing screen the lead-facing lanes get. `last_at` and
        # `last_message_at` stay untouched: a notification is not conversation
        # activity, and bumping those clocks would move the lead in the Inbox
        # without anybody having spoken.
        db.add(
            Message(
                conversation_id=inbound.conversation_id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.AGENT,
                content=body,
                subject=subject,
                internal=True,
                external_id=external_id,
                delivery_status=(
                    MessageStatus.SENT if external_id else MessageStatus.FAILED
                ),
                last_error=failure,
                # Spent on purpose when the send failed: the row then states
                # the truth — failed, not being retried — using the condition
                # the delivery sweep already honours. A blind retry here would
                # send the agency's note wherever the sweep's dispatcher
                # decides, which is the lead.
                send_attempts=0 if external_id else MAX_ATTEMPTS,
            )
        )
        await db.commit()
