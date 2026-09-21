"""New-lead notice to the agency — the interim funnel's second half.

The public form used to end in silence on the agency side: the lead row
appeared in the panel and nobody was told it existed. That was fine while the
form was one channel among several; it is not fine now that the funnel is
"visitor fills the form → the agent calls them back within a few hours". If
nobody hears about the lead, the promise on the page is false.

So: one notice per captured submission, carrying everything needed to make the
call — name, phone, email, what they said, and where they came from, plus a
link straight to the lead in the panel.

**Two origins, one link, and — since 6-Sep-2026 — a second reader.** The mail
goes to the agency's `booking_contact_email` as it always has; when
`OWNER_NOTICE_EMAIL` is set, the person who OPERATES the install gets their own
copy of the same message. Two sends, never two recipients on one: the agency's
notice must not carry the operator's address in its header, where a "Reply all"
would find it. The setting lives in the environment rather than in Settings
because Settings is the agency's to edit, and a safety net the watched party
can delete is not one.

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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing_request import MAX_SELECTED
from app.services.calculator import summary_line
from app.services.email import send_email
from app.services.lead_traffic import is_noncommercial
from app.services.telegram_notify import send_operator_telegram, undeliverable_reason

log = logging.getLogger("app.lead_notify")

# Per transport, not for the three together — see the gather below. Named
# rather than inlined so a test can shorten it: proving that a stalled leg
# cannot bury a delivered one should not cost the suite eight seconds.
NOTICE_TIMEOUT_SECONDS = 8.0


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


def _picker_link(request_id: int | None) -> str | None:
    """Her screen for one options request, or None when no panel is configured.

    A dedicated page rather than a section of the lead's: what she has to do
    here is pick from a list, and the notice that asks her to do it should land
    on the thing itself. Same guard as `_panel_link` — an empty `PANEL_URL`
    produces no link rather than `https:///options/4`.
    """
    from app.config import get_settings

    if request_id is None:
        return None
    base = (get_settings().PANEL_URL or "").strip().rstrip("/")
    return f"{base}/options/{request_id}" if base else None


def _matrix_recipe_for(lead: object) -> str | None:
    """The Matrix search that would fill this shortlist, or nothing.

    Wrapped because a notice is worth more than a recipe: if the scorer cannot
    project this lead for any reason, she still gets told somebody is waiting.
    """
    try:
        from app.services.listing_match import matrix_recipe, requirements_of

        req = requirements_of(lead)
        return matrix_recipe(req) if req.stated_anything else None
    except Exception as exc:  # noqa: BLE001 — the notice matters more
        log.warning("Could not build a Matrix recipe: %s", exc)
        return None


def _upload_link() -> str | None:
    """Where an export goes once she has downloaded it.

    Same guard as `_picker_link`: an empty `PANEL_URL` produces no link rather
    than `https:///properties`. The page is `/properties`, which hosts the
    import box — there is no separate upload route.
    """
    from app.config import get_settings

    base = (get_settings().PANEL_URL or "").strip().rstrip("/")
    return f"{base}/properties" if base else None


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


async def _notify_owner_by_email(
    to: str, subject: str, body: str, lead_id: int, agency_to: str | None
) -> bool:
    """The operator's own copy of the notice. Never raises, never blocks.

    A SEPARATE message rather than a second recipient on the agency's, and that
    is not a stylistic choice: `to: [natalia, owner]` puts the operator's
    personal address in the header of every notice the agency receives, and a
    "Reply all" from them would then write to it. The agency's mail is theirs
    alone; this one is a copy that exists beside it.

    Its own function, with its own name, because both AST sweeps list what may
    send — a copy dispatched from inside `_notify_agency_by_email` would ride
    that function's exemption and be invisible to them.
    """
    try:
        note = (
            f"\n—\nOperator copy. The agency was told at {agency_to}.\n"
            if agency_to
            else "\n—\nOperator copy. The agency has no contact address set in "
            "Settings, so NOBODY at the agency was told.\n"
        )
        result = await send_email(to=to, subject=subject, body_text=body + note)
        if (result or {}).get("id"):
            log.info("Lead %d: operator copy of the notice sent", lead_id)
            return True
        log.error("Lead %d: operator copy accepted with no id", lead_id)
        return False
    except Exception as exc:  # noqa: BLE001 — a copy may never cost the original
        log.error("Lead %d: operator copy failed to send: %s", lead_id, exc)
        return False


async def _not_attempted(value):
    """A leg of the gather below that was never configured.

    Keeps the arity of `asyncio.gather` fixed, so the three transports are read
    positionally in one place instead of being assembled by a list whose length
    depends on configuration — which is how the wrong result gets unpacked into
    the wrong variable on the day somebody adds a fourth.
    """
    return value


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
    request_id: int | None = None,
) -> None:
    """Email the agency about a lead that just arrived. Never raises.

    Reads everything on its own throwaway session (org inherited from the
    request's ContextVar, the same mechanism `pick_agent_safely` relies on),
    so it cannot poison the caller's transaction and needs nothing from it.

    The three extras are KEYWORD-ONLY and all default to today's behaviour, so
    the form's call site — the funnel's only conversion point — did not have to
    change to gain a second origin:

    * `origin` — `"form"`, `"call"`, `"message"` (someone wrote in on any
      channel) or `"qualified"` (the handoff, once Clara has an intent, an area
      and a figure); picks the subject and the body.
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
            lead_id,
            message_id,
            origin=origin,
            conversation_id=conversation_id,
            call=call,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001 — the lead is already captured
        log.error("Lead %d: new-lead notice failed: %s", lead_id, exc)


# Origins a stranger can trigger from outside, with nothing but an email
# address. The form and a phone call are NOT here: the form has a honeypot, a
# per-IP budget, a captcha and its own global limit, and a call costs a call.
#
# `options` is here and `callback` is NOT, and the difference is who is on the
# other end. An options request is opened by whoever wrote to `hello@` — the
# same anonymous path the cap was built for, and the expensive one, because
# each notice asks Natalia to run a search against a metered MLS allowance.
# A callback comes from somebody already holding a token we mailed to an
# address that received our options; it is the conversion point of this whole
# circuit, and a budget a stranger can exhaust on its behalf would be the
# `public.py` kill switch again, this time aimed at the one event worth
# interrupting her day for.
_STRANGER_ORIGINS = frozenset({"message", "qualified", "options"})


async def _notices_in_24h(db: AsyncSession) -> int:
    """How many agency notices this org has already produced in a rolling day.

    Counts the internal trace row every notice leaves in the lead's thread, so
    the budget is measured from what was actually delivered rather than from a
    counter that can drift. The session is org-scoped, so RLS does the tenant
    filtering.

    Rolling 24h, not a calendar day: a cap that resets at midnight is a cap that
    a flood times itself against.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func

    from app.models.message import Message

    since = datetime.now(UTC) - timedelta(days=1)
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.internal.is_(True), Message.created_at >= since)
            )
        ).scalar_one()
    )


async def _send_and_record(
    lead_id: int,
    message_id: int | None,
    *,
    origin: str = "form",
    conversation_id: int | None = None,
    call: dict | None = None,
    request_id: int | None = None,
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
        if is_noncommercial(lead.meta):
            log.info("Lead %d: noncommercial notice suppressed (%s)", lead_id, origin)
            return
        cfg = (
            await db.execute(
                select(AgentSettings).where(AgentSettings.org_id == get_org_id())
            )
        ).scalar_one_or_none()
        to = ((getattr(cfg, "booking_contact_email", None) or "").strip()) or None
        # The operator's copy. Read from the environment, never from Settings:
        # the agency edits Settings, and a safety net the watched party can
        # remove is not one.
        from app.config import get_settings as _settings

        owner = ((_settings().OWNER_NOTICE_EMAIL or "").strip()) or None

        # ── The daily budget, charged before anything is composed ──────────
        #
        # Since the email channel opened this morning, anyone in the world can
        # reach `hello@` and produce a lead. `origin="qualified"` then fires a
        # notice for every one that names a neighbourhood and a figure — so
        # fifty emails are fifty "Ready for you" mails in the realtor's inbox,
        # and if they each became an MLS search they would be fifty exports
        # against a 500-listing ceiling whose penalty is $15,000 and suspension
        # of her access (REcolorado Rules §12.4).
        #
        # Only stranger origins are capped. A notice from the form must never be
        # suppressed because someone flooded the mailbox — that is the shape of
        # mistake `public.py` already paid for, where a budget charged too early
        # became a kill switch anyone could hold down.
        capped = False
        if origin in _STRANGER_ORIGINS:
            spent = await _notices_in_24h(db)
            cap = _settings().AGENCY_NOTICE_DAILY_CAP
            if spent > cap:
                # Suppressed, and it says so where a human looks for it. The
                # lead itself is untouched and sitting in the panel: what is
                # dropped is the nudge, never the person.
                log.error(
                    "Lead %d: agency notice suppressed — %d notices in 24h is "
                    "over the cap of %d. The lead is in the panel.",
                    lead_id, spent, cap,
                )
                return
            capped = spent == cap
        if owner and to and owner.casefold() == to.casefold():
            # The same person twice. Reachable and not hypothetical: the owner
            # pointed `booking_contact_email` at himself for the Fase 4
            # rehearsal, and every rehearsal after this one will do it again.
            owner = None
        if not to and not owner:
            # Same posture as visit_invite: an empty contact address is a
            # configuration gap somebody has to fix, not a silent no-op.
            log.warning(
                "Lead %d: booking_contact_email is empty in Settings, so nobody "
                "was told about the new lead",
                lead_id,
            )
            return
        if not to:
            # The net doing its job. Worth its own line, because the agency
            # silently not being told is the failure this module exists to
            # prevent and it must not be hidden by the copy that succeeded.
            log.warning(
                "Lead %d: booking_contact_email is empty in Settings — only the "
                "operator's copy will go out",
                lead_id,
            )

        # The options request this notice is about, when there is one. Read
        # here rather than passed in as a dict: the row is the authority on what
        # the client typed, and a caller that assembled the words itself is a
        # caller that can get them wrong.
        listing_request = None
        if request_id is not None:
            from app.models import ListingRequest

            listing_request = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one_or_none()

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
        if capped:
            # Sent INSTEAD of this lead's notice, exactly once: it leaves its own
            # trace row, which pushes the count past the cap, so everything after
            # it takes the early return above. One "go and look" beats fifty
            # notices and beats silence.
            subject = "Automatic notices paused — check the panel"
            body = (
                "More inquiries have arrived in the last 24 hours than the "
                "automatic notices are allowed to carry, so they have been "
                "paused until the day rolls over.\n\n"
                "Nothing has been lost: every lead is in the panel, including "
                "the ones you were not emailed about.\n\n"
                "If this was not a busy day, it was probably not real traffic — "
                "tell whoever runs the system.\n"
            )
        elif origin == "call":
            # Said plainly, in the first line and in the subject, because this
            # is the whole triage: a call with words is a conversation to read,
            # and a call without them is a number to ring back. The notice used
            # to describe the second as if it were the first.
            silent = facts.get("caller_spoke") is False
            subject = (
                f"Clara answered, the caller said nothing — {who}"
                if silent
                else f"New call answered by Clara — {who}"
            )
            body = (
                (
                    "Clara answered, and the caller hung up without saying "
                    "anything. There is no transcript and no summary — only "
                    "the number, which is worth a call back.\n\n"
                    if silent
                    else "Clara answered a call.\n\n"
                )
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Duration", _spoken_duration(facts.get("duration_seconds")))
                + _line("Summary", (facts.get("summary") or None))
                + _line("Came from", attribution)
                + _line("Calculator", _calculator_line(lead))
                # Promising a transcript that does not exist is how a person
                # stops believing the rest of the notice.
                + (
                    "\nThe recording is in the panel.\n"
                    if silent
                    else "\nThe full transcript and the recording are in the panel.\n"
                )
            )
        elif origin == "message":
            # Someone who wrote in rather than filling the form. Until v0.134.0
            # nobody at the agency was told about these at all: the notice fired
            # from the form and from a call, and a person who simply emailed
            # `hello@` appeared in the panel and nowhere else.
            subject = f"New inquiry — Clara is answering — {who}"
            body = (
                "Someone wrote in. Clara has already answered; take it over "
                "from the panel whenever you want to.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("They wrote", (inbound.content if inbound else None))
                + _line("Came from", attribution)
                + _line("Calculator", _calculator_line(lead))
            )
        elif origin == "options":
            # The expensive one. Everything downstream of this notice costs
            # Natalia a search in Matrix and, if she exports, part of a 500-record
            # allowance that renews every 30 days and whose penalty for abuse
            # falls on HER licence — so this origin is capped upstream with the
            # other stranger origins, and the body says what the work is rather
            # than leaving her to work it out.
            # A second round is not a new person, and saying so would send her
            # looking for a lead she has never heard of. `origin` is on the row
            # because of this line.
            again = getattr(listing_request, "origin", "message") == "more"
            subject = (
                f"They want a different set — {who}"
                if again
                else f"They asked to see actual listings — {who}"
            )
            body = (
                (
                    "They read what you sent and asked for another set. "
                    "Nothing has been sent yet.\n\n"
                    if again
                    else "Someone asked to see places, not advice. Clara has told "
                    "them a short list is coming from you — nothing has been sent "
                    "yet.\n\n"
                )
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Wants", lead.intent.value if lead.intent else None)
                + _line("Area", lead.zone)
                + _line("Timeline", lead.urgency)
                + _line("They wrote", (inbound.content if inbound else None))
                + _line("Calculator", _calculator_line(lead))
            )
            # What actually matched, and what is missing. The binary version of
            # this notice — "here they are" or nothing — was the one that sent
            # her to a screen with eight one-bedroom condos on it for a lead who
            # had asked for a two-bedroom house with a garage, and left her to
            # work out for herself that the answer was an export.
            summary = getattr(listing_request, "match_summary", None) or {}
            matched = summary.get("matched")
            active = summary.get("active")
            unmet = [u for u in (summary.get("unmet") or []) if isinstance(u, str)]
            suggestions = getattr(listing_request, "suggestions", None) or []

            if matched is not None and active is not None:
                body += f"\nMatched: {len(suggestions)} of {active} active"
                if matched != len(suggestions):
                    body += f" ({matched} in the area)"
                body += "\n"
            for line in unmet:
                body += f"  · {line}\n"

            if (picker := _picker_link(request_id)) is not None:
                body += f"\nPick up to six and they go out in your name: {picker}\n"

            # Short of a full shortlist: the search to run, and where to put it.
            # Printed only when it is actually needed, because a recipe under a
            # list of six is noise, and noise is how a notice stops being read.
            if len(suggestions) < MAX_SELECTED:
                recipe = _matrix_recipe_for(lead)
                if recipe:
                    body += f"\n{recipe}\n"
                if (upload := _upload_link()) is not None:
                    body += f"\nUpload the export here: {upload}\n"
        elif origin == "callback":
            # The conversion point of the whole circuit, and the reason it is
            # never capped. They read what you sent and asked for you.
            #
            # Their note about timing is printed as they wrote it and is not
            # turned into an appointment: nothing in this product holds a slot
            # on her calendar, and a parsed "Thursday" that lands on the wrong
            # Thursday is worse than the sentence it came from.
            subject = f"They want you to call — {who}"
            body = (
                "They looked at the options and asked you to ring them. "
                "Nothing is booked; this is their own note about when.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Area", lead.zone)
                + _line(
                    "They wrote",
                    (listing_request.callback_text if listing_request else None),
                )
                + _line("Calculator", _calculator_line(lead))
            )
        elif origin == "handover":
            # The moment Clara stops, not the messages after it. `waiting` below
            # covers somebody who writes AGAIN; this covers the turn where she
            # spends her last reply and tells them a person will follow up.
            #
            # Measured on lead 1279 (2026-09-20): her last reply promised "a
            # member of our team will get back to you with options" and NOBODY
            # was told, because the classifier had read the message as not
            # asking for listings. A promise made to a stranger with nobody
            # behind it is the worst thing this product can do, and it was
            # silent — the panel had the row and no inbox had the news.
            #
            # Not capped, for the same reason `waiting` is not: this is not a
            # stranger arriving, it is a conversation being handed over.
            subject = f"This one is yours now — {who}"
            body = (
                "Clara has just written her last automated reply to this "
                "person and told them someone from the team would follow up. "
                "From here it is you.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Wants", lead.intent.value if lead.intent else None)
                + _line("Area", lead.zone)
                + _line("Timeline", lead.urgency)
                + _line("They wrote", (inbound.content if inbound else None))
                + _line("Calculator", _calculator_line(lead))
            )
        elif origin == "waiting":
            # Clara has spent her two replies and this person wrote again. The
            # notice is NOT capped with the stranger origins: somebody who has
            # already been told a human would call and is still writing is the
            # opposite of a stranger, and the cost of missing them is a lead who
            # was promised a call and heard nothing.
            #
            # Sent every time they write, while the sentence they get back is
            # sent at most once a day. That asymmetry is the point: the person
            # must not be echoed at, and she must not be kept in the dark.
            subject = f"They are waiting for you — {who}"
            body = (
                "Clara has stopped answering this one — she has used the two "
                "replies she is allowed, and they have written again since. "
                "They were told you would be in touch as soon as possible.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Area", lead.zone)
                + _line("They wrote", (inbound.content if inbound else None))
                + _line("Calculator", _calculator_line(lead))
            )
        elif origin == "qualified":
            # The handoff. Sent once per lead, the moment Clara has an intent, a
            # zone and a figure — not on a score threshold, which a chatty
            # tyre-kicker also crosses.
            #
            # NO BUDGET LINE, and that absence is the point. Measured on lead
            # 1269, the first real run: someone wrote "renting at $2,400 and I
            # have around $35,000 saved" and the classifier filed
            # budget_min = budget_max = 35000. That is the DOWN PAYMENT. Our own
            # calculator puts what they can buy at $315,399 — an order of
            # magnitude out, on the one line an agent would act on.
            #
            # So the figure still opens the gate (someone who names money is
            # someone who has thought about it) and never gets a label the
            # product cannot stand behind. What goes in its place is what they
            # actually wrote, which cannot be wrong about itself.
            #
            # The real budget is `solve_price()` over rent/savings/credit, and it
            # arrives in v0.135.0. Until it does, silence beats a confident
            # number: an agent who reads "Budget: $35,000" shows $35,000 houses.
            subject = f"Ready for you — {who}"
            body = (
                "Clara has an intent, an area and a timeline on this one. The "
                "money they mentioned is in their own words below — we are not "
                "turning it into a price range yet.\n\n"
                + _line("Name", lead.name)
                + _line("Phone", phone)
                + _line("Email", email)
                + _line("Wants", lead.intent.value if lead.intent else None)
                + _line("Area", lead.zone)
                + _line("Timeline", lead.urgency)
                + _line("Score", f"{lead.score}/100")
                + _line("They wrote", (inbound.content if inbound else None))
                + _line("Calculator", _calculator_line(lead))
                + "\nThe whole conversation is in the panel.\n"
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
        owner_ok = False
        try:
            # `return_exceptions=True` on top of the per-transport handlers: a
            # raise escaping here would cost the whole notice AND leave the row
            # unwritten, which is worse than either transport failing.
            #
            # The operator's copy rides the SAME budget rather than adding its
            # own: it is concurrent with the other two, so it costs no extra
            # wall-clock inside the form's POST.
            #
            # The budget is PER LEG, not one clock around the three. A single
            # `wait_for` over the gather cancels every child when it fires, so a
            # slow leg discarded the result of one that had already succeeded:
            # the agency was told at two seconds, the operator's copy stalled,
            # and the row said FAILED — with `send_attempts` spent — about a
            # mail that went out. They run concurrently, so three eight-second
            # budgets are still eight seconds of wall-clock.
            mail_result, telegram_result, owner_result = await asyncio.gather(
                asyncio.wait_for(
                    _notify_agency_by_email(to, subject, body, lead.id),
                    timeout=NOTICE_TIMEOUT_SECONDS,
                )
                if to
                else _not_attempted((None, "no booking_contact_email in Settings")),
                asyncio.wait_for(
                    _notify_agency_by_telegram(subject, body, lead.id),
                    timeout=NOTICE_TIMEOUT_SECONDS,
                ),
                asyncio.wait_for(
                    _notify_owner_by_email(owner, subject, body, lead.id, to),
                    timeout=NOTICE_TIMEOUT_SECONDS,
                )
                if owner
                else _not_attempted(False),
                return_exceptions=True,
            )
            if isinstance(mail_result, tuple):
                external_id, failure = mail_result
            elif isinstance(mail_result, TimeoutError):
                failure = "the email provider did not answer within 8s"
                log.error("Lead %d: the agency's mail timed out", lead.id)
            else:
                failure = str(mail_result)[:500]
            telegram_ok = telegram_result is True
            owner_ok = owner_result is True
        except Exception as exc:  # noqa: BLE001 — the row must still be written
            failure = f"the notice transports raised: {exc}"[:500]
            log.error("Lead %d: notice transports raised: %s", lead.id, exc)

        # The row states whether a human was reachable AT ALL, not whether the
        # mail worked. Recording FAILED while Telegram carried the notice would
        # send somebody chasing an outage that did not happen; recording SENT
        # when neither arrived is the lie this whole module exists to prevent.
        delivered = bool(external_id) or telegram_ok or owner_ok
        if not to:
            # FIRST, ahead of the transport branches below. Telegram goes to the
            # OPERATOR's chat, never to the agency, so it succeeds in exactly
            # this case and used to overwrite the reason with "telegram carried
            # the notice" — which reads as a provider hiccup on a row the agency
            # opens in their own panel, about a message that was never addressed
            # to them at all.
            failure = (
                "NOBODY at the agency was told: booking_contact_email is empty "
                "in Settings"
                + ("; the operator's copy went out" if owner_ok else "")
            )
        elif failure and telegram_ok:
            failure = f"email failed ({failure}); telegram carried the notice"
        elif failure and owner_ok:
            # Said plainly, because it is the one shape a human must not read as
            # "sent": somebody was told, and it was not the agency.
            failure = f"the agency was NOT reached ({failure}); the operator's copy went out"
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
