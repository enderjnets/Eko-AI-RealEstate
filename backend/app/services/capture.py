"""Turn a public form submission into a lead.

The one thing that makes this different from every other way a lead arrives:
there is no session and no provider signature, so nothing about the request
proves who is asking or which agency it belongs to. Two consequences run through
this whole module.

First, the tenant is resolved from the form key through `channel_routes`, the
same table that attributes an inbound SMS to the agency whose number was texted.
The caller does that before touching this module — nothing here writes until an
organization is bound, and under default-deny RLS a forgotten binding writes
nothing rather than writing into the wrong tenant.

Second, every field is hostile input. Values are capped, unknown attribution
keys are dropped, and a repeat submission merges instead of raising: `leads` is
unique on (org_id, phone), so the second time somebody fills in the form the
naive insert is a 500 and a lost lead.

No reply is generated here. `web` is not in SENDABLE_CHANNELS — nothing can be
delivered to a form — so an auto-reply would be an LLM call whose output goes to
a dispatcher that fails and then retries five times against a channel that does
not exist. The submission lands in the Inbox and a person answers it, which is
also what §9 of the content plan asks for in the first weeks.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import first_or_create
from app.models.channel_route import CHANNEL_WEB
from app.models.conversation import Conversation, ConversationStatus
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.scoring import rescore_lead

log = logging.getLogger(__name__)

# ── Input limits ─────────────────────────────────────────────────────────
# `leads.meta` is an unbounded JSON column and this endpoint is unauthenticated,
# so without caps the form is free storage for anyone who finds it. The numbers
# are generous for a human and useless for an abuser.
MAX_NAME = 160
MAX_MESSAGE = 5_000
MAX_CONSENT_TEXT = 1_000
MAX_ATTRIBUTION_VALUE = 200
# Exactly the size of ATTRIBUTION_KEYS, asserted below rather than eyeballed.
# It was 12 against a 10-key whitelist, so the guard it looked like it provided
# could never fire — the same "cap applied to nothing" shape as the message
# length bug this module already paid for once.
MAX_ATTRIBUTION_KEYS = 10
MAX_LATER_TOUCHES = 10

# A double-click, a flaky connection, a browser resubmitting on back — all send
# the same text twice within seconds. Deduplicated against the DATABASE, not an
# in-process set, because a restart empties the set and the duplicate survives.
DEDUPE_WINDOW = timedelta(minutes=5)

# Only these reach `meta`. A whitelist rather than a blocklist: the field exists
# to answer "which video produced this lead", and anything else arriving in it
# is either a mistake or somebody using the column as a notepad.
ATTRIBUTION_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "gclid",
        "fbclid",
        "landing_variant",
        "tier",
        "referrer",
    }
)

# A whitelist and its cap cannot drift: a cap larger than the list is a guard
# that can never fire, and one smaller silently drops legitimate attribution.
assert MAX_ATTRIBUTION_KEYS == len(ATTRIBUTION_KEYS)

# Used only when the visitor types a national number with no country code.
# Denver is +1, but the value is here as a named constant rather than inline so
# a non-US install has one place to change, and so the assumption is visible
# instead of buried in a slice.
DEFAULT_CALLING_CODE = "1"

# The channels TCPA reaches: automated calls and texts. Email is governed by
# CAN-SPAM instead, which asks for a working unsubscribe rather than prior
# consent, so gating it here would suppress legitimate mail and protect nobody.
_CONSENT_GATED_CHANNELS = frozenset({"sms", "whatsapp", "voice"})

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class CaptureRejected(Exception):
    """The submission cannot become a lead. Carries a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FormSubmission:
    """One public form post, already parsed but not yet validated."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str | None = None
    consent: bool = False
    consent_text: str | None = None
    attribution: dict[str, str] = field(default_factory=dict)
    ip: str | None = None
    user_agent: str | None = None


def clean_text(value: str | None, limit: int) -> str | None:
    """Collapse whitespace, cap length, and turn an empty result into None."""
    if value is None:
        return None
    collapsed = " ".join(str(value).split())
    if not collapsed:
        return None
    return collapsed[:limit]


def normalize_email(value: str | None) -> str | None:
    """A lowercase address, or None when it is not structurally an address.

    Deliberately structural rather than deliverability-checking: a form that
    rejects a real address because a regex disagrees with the RFC loses a lead,
    which costs more than storing one that bounces.
    """
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > 254:
        return None
    return cleaned if _EMAIL.match(cleaned) else None


def normalize_phone(value: str | None) -> str | None:
    """E.164, or None.

    The same person must land on the same lead whether they type
    "(303) 555-1234" into the form or text us from +13035551234 — otherwise the
    form manufactures a duplicate of every lead who later replies by SMS, and
    the realtor sees half a history in each. That is the whole reason this
    normalises to E.164 instead of storing what was typed.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None

    if raw.startswith("+"):
        candidate = digits
    elif digits.startswith("00"):
        candidate = digits[2:]
    elif len(digits) == 10:
        # A national number typed the way people say it out loud.
        candidate = DEFAULT_CALLING_CODE + digits
    else:
        candidate = digits

    # E.164 allows 15 digits; below 8 it is not a reachable number, it is a
    # typo or a honeypot probe.
    if not 8 <= len(candidate) <= 15:
        return None
    return "+" + candidate


def clean_attribution(raw: dict | None) -> dict[str, str]:
    """Whitelisted, trimmed, capped. Everything else is discarded silently."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in ATTRIBUTION_KEYS:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        cleaned = clean_text(str(value), MAX_ATTRIBUTION_VALUE)
        if cleaned:
            out[key] = cleaned
        if len(out) >= MAX_ATTRIBUTION_KEYS:
            break
    return out


def _summary(message: str | None, name: str | None) -> str:
    """What the realtor reads in the Inbox.

    The lead's own words when they wrote any, and otherwise a plain statement of
    what the form knows — never an empty message, which in the Inbox looks like
    a bug rather than like a contact request with no note.

    Takes the CLEANED message, never `sub.message`: reading the raw field here
    is how the 5,000-character cap ends up applying to nothing at all.
    """
    if message:
        return message
    who = name or "Someone"
    return f"{who} submitted the contact form and left no message."


def validate_submission(sub: FormSubmission) -> None:
    """Reject a submission that cannot become a lead. No database, no tenant.

    Separate from `capture_lead` so the caller can run it BEFORE resolving the
    organization. Ordering it after resolution made the endpoint an enumeration
    oracle: a probe with no contact details answered 422 for a live form key
    and 404 for one that named nothing, and because it wrote no lead the scan
    left no trace in any inbox.
    """
    if normalize_phone(sub.phone) is None and normalize_email(sub.email) is None:
        raise CaptureRejected(
            "contact_required", "Give either an email address or a phone number."
        )
    if sub.consent and not clean_text(sub.consent_text, MAX_CONSENT_TEXT):
        # A ticked box with no record of the wording is the indefensible
        # timestamp the consent columns exist to avoid. Refuse it at the door
        # rather than store something that looks like proof and is not.
        raise CaptureRejected(
            "consent_text_required",
            "A consent record needs the exact wording that was shown.",
        )


async def capture_lead(sub: FormSubmission, db: AsyncSession) -> dict[str, object]:
    """Create or merge the lead, record the submission, return a small status.

    The caller has already bound the organization and is responsible for the
    commit — same contract as `handle_inbound_message`.
    """
    name = clean_text(sub.name, MAX_NAME)
    email = normalize_email(sub.email)
    phone = normalize_phone(sub.phone)
    message = clean_text(sub.message, MAX_MESSAGE)
    attribution = clean_attribution(sub.attribution)

    # The identifier is what `leads.phone` holds on every channel: a number when
    # we have one, the address otherwise. Preferring the number matters — it is
    # the identifier an SMS or WhatsApp arrival will use, so choosing the
    # address when both are present would split the same person in two the
    # moment they reply.
    # Re-run even though the route already did: this function is called
    # directly by tests and by anything added later, and a validation that only
    # runs in one caller is a validation that will eventually not run.
    validate_submission(sub)
    identifier = phone or email
    assert identifier is not None  # validate_submission guarantees it

    lead, is_new, by_address = await _lead_for(identifier, email, db)

    if name and not lead.name:
        lead.name = name
    if email and not lead.email:
        lead.email = email

    now = datetime.now(UTC)
    _record_attribution(lead, attribution, now)
    _record_consent(lead, sub, now, reached_by_address=by_address)

    conv = await first_or_create(
        db,
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.channel == CHANNEL_WEB,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .limit(1),
        lambda: Conversation(
            lead_id=lead.id,
            channel=CHANNEL_WEB,
            status=ConversationStatus.ACTIVE,
        ),
    )

    content = _summary(message, name)
    if await _already_said(conv.id, content, now, db):
        log.info("Duplicate web submission for lead %d ignored", lead.id)
        return {
            "status": "duplicate",
            "lead_id": lead.id,
            "is_new_lead": False,
            "message_id": None,
        }

    inbound = Message(
        conversation_id=conv.id,
        direction=MessageDirection.INBOUND,
        sender=MessageSender.LEAD,
        content=content,
        delivery_status=MessageStatus.DELIVERED,
    )
    db.add(inbound)
    await db.flush()

    conv.last_at = now
    lead.last_message_at = now
    # Explicitly NOT setting inbox_handled_at: a form submission is unhandled by
    # definition, and that is what puts it in front of the realtor.

    # Score it. The Inbox is sorted by priority, so a lead left at the default
    # zero sinks below every old WhatsApp thread — the newest lead from the
    # channel we just built would be the last one anybody looks at. Committed
    # by the caller, like everything else here.
    await rescore_lead(lead, db, commit=False)

    log.info(
        "Web capture: lead=%d new=%s consent=%s source=%s",
        lead.id,
        is_new,
        lead.consent_at is not None,
        attribution.get("utm_source", "-"),
    )
    return {
        "status": "ok",
        "lead_id": lead.id,
        "is_new_lead": is_new,
        "message_id": inbound.id,
    }


async def _lead_for(
    identifier: str, email: str | None, db: AsyncSession
) -> tuple[Lead, bool, bool]:
    """The lead this submission belongs to, created if this is a first contact.

    Returns (lead, is_new, reached_by_address). The third flag says the lead was
    found through the email-merge branch rather than by its own identifier —
    which means the submitter proved nothing about the identifier this lead is
    actually messaged on, and the caller must not write consent for it.

    The merge rule is deliberately the same one `handle_inbound_message` uses,
    and for the same reason: prefer the lead keyed on this exact identifier, and
    only when there is none adopt a lead carrying this address — and only when
    there is exactly one. Two leads sharing an address is `info@`, or a family
    mailbox, and merging them would put one person's conversation in front of
    another.
    """
    by_identifier = select(Lead).where(Lead.phone == identifier)
    stmt = by_identifier
    reached_by_address = False

    if email is not None and (await db.execute(by_identifier)).scalars().first() is None:
        matches = (
            (await db.execute(select(Lead).where(Lead.email == email))).scalars().all()
        )
        if len(matches) == 1:
            stmt = select(Lead).where(Lead.id == matches[0].id)
            reached_by_address = True
        elif len(matches) > 1:
            log.warning(
                "%d leads share the address %s; keeping this capture separate",
                len(matches),
                email,
            )

    existing = (await db.execute(stmt)).scalars().first()
    is_new = existing is None
    lead = await first_or_create(
        db,
        stmt,
        lambda: Lead(phone=identifier, email=email),
    )
    return lead, is_new, reached_by_address and not is_new


def _record_attribution(lead: Lead, attribution: dict[str, str], now: datetime) -> None:
    """First touch wins; later touches are kept beside it, not on top of it.

    The question this data exists to answer is which video produced the lead, so
    overwriting on a second submission would credit whichever piece of content
    they happened to see last — usually the retargeting ad, never the video that
    actually found them.

    Reassigns `lead.meta` rather than mutating it: the column is plain JSON with
    no mutation tracking, so an in-place edit is simply not written.
    """
    if not attribution:
        return
    meta = dict(lead.meta or {})
    stamped = {**attribution, "captured_at": now.isoformat()}
    if not meta.get("attribution"):
        meta["attribution"] = stamped
    else:
        later = list(meta.get("attribution_later") or [])
        if len(later) < MAX_LATER_TOUCHES:
            later.append(stamped)
            meta["attribution_later"] = later
    lead.meta = meta


def _record_consent(
    lead: Lead, sub: FormSubmission, now: datetime, *, reached_by_address: bool
) -> None:
    """Write the consent record once. Never clear it.

    Consent is a historical fact: the person did tick the box on that day
    looking at that wording. A later submission with the box unticked does not
    unsay it — and treating it as a revocation would be worse than useless,
    because the revocation people actually use is STOP, and a form submission
    is not where that arrives.

    Revocation is NOT handled here. It arrives as an inbound message on a
    messaging channel, is recognised by keyword in `app/services/optout.py`,
    and is honoured by `may_send_automated` above — which checks it before
    anything else.

    `reached_by_address` blocks the one case where the submitter has proved
    nothing about the identifier that will actually be messaged. The email
    merge is there so the same person writing from two places becomes one
    lead; it also means anyone who knows an address reaches the CRM record
    behind it. Without this guard an anonymous POST carrying only a known
    address could stamp consent onto a WhatsApp lead who never opted in — and
    since consent is never overwritten, it could equally pre-plant junk wording
    so the person's real consent could never be recorded. Any web form lets a
    stranger assert consent for contact details they typed; none of them should
    let a stranger assert it for details they did not.
    """
    if reached_by_address:
        if sub.consent:
            log.warning(
                "Ignoring a consent claim for lead %d: this submission reached "
                "it by matching an email address, not by its own identifier",
                lead.id,
            )
        return
    if not sub.consent or lead.consent_at is not None:
        return
    lead.consent_at = now
    lead.consent_text = clean_text(sub.consent_text, MAX_CONSENT_TEXT)
    lead.consent_ip = clean_text(sub.ip, 45)
    lead.consent_user_agent = clean_text(sub.user_agent, 400)


async def may_send_automated(lead: Lead, channel: str, db: AsyncSession) -> bool:
    """Whether an automated message may go to this lead on this channel.

    TCPA governs automated calls and texts, and it is satisfied two ways. Either
    the consumer gave prior express written consent — the form's checkbox, with
    the wording they read stored beside it — or the consumer initiated contact
    on that channel, which is why every lead who has ever texted us keeps
    receiving nurture messages exactly as before.

    Email is not gated here: it answers to CAN-SPAM, whose requirement is a
    working unsubscribe, not prior consent.

    The case this actually catches is the one that looks innocent. A web lead
    fills in the form without ticking the box, the agent sends them one manual
    SMS — which creates an SMS conversation — and from that moment the nurture
    worker would have a perfectly sendable channel and no permission to use it.
    Nothing else in the system would have objected.

    An opt-out outranks both branches and is checked FIRST. It has to be: the
    consumer-initiated branch below is satisfied by *any* inbound message on the
    channel, and the word people send to make it stop is itself an inbound
    message. Checked second, "STOP" would have flipped a correctly blocked lead
    to sendable — the gate inverted by precisely the input it exists to obey.
    """
    if lead.opted_out_at is not None:
        return False
    if channel not in _CONSENT_GATED_CHANNELS:
        return True
    if lead.consent_at is not None:
        return True
    row = await db.execute(
        select(Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.channel == channel,
            Message.direction == MessageDirection.INBOUND,
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def _already_said(
    conversation_id: int, content: str, now: datetime, db: AsyncSession
) -> bool:
    """Whether this exact text already arrived on this conversation just now."""
    row = await db.execute(
        select(Message.id)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
            Message.content == content,
            Message.created_at >= now - DEDUPE_WINDOW,
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None
