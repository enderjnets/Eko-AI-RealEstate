"""Opening an options request, and mailing the shortlist a person picked.

The circuit this serves, end to end:

    someone asks for places  →  ListingRequest(open)  →  notice to the realtor
    →  she ticks up to six in the panel  →  this module mails them
    →  the client presses "more" or "call me"  →  back to the top

Three properties hold it together, and each one exists because of something
that has already gone wrong here:

**The email carries the listings; the web page carries none.** REcolorado's
rules let a Participant reproduce and distribute listing information to a
prospective purchaser (§11.2) and forbid displaying or publishing it without
prior written consent. An email to the person who asked is distribution. A URL
anyone can open is publishing. So `build_options_email` prints the facts and
`public.py`'s options page prints two buttons.

**Only named fields ever leave.** The Full export we read on 2026-09-19 carries
394 columns, and `Private Remarks` (9 of 10 rows), `Showing Contact Phone` (10),
`List Agent Email` (10), `Contract Min Earnest` (10) and `Exclusions` (10) are
notes between brokers about somebody else's client. `_option_lines` names what
it prints. A deny-list would have been one careless template away from mailing
the other side's negotiating position to a consumer.

**`Public Remarks` is not among them**, and that is deliberate twice over: it is
marketing copy written by another brokerage, and it is exactly where a listing
agent writes "great schools" — a phrase this product's own Fair Housing screen
blocks on the email lane since v0.135.0. We would be blocking ourselves over
someone else's sentence.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ListingRequest, ListingRequestStatus
from app.models.listing_request import CALLBACK_TEXT_MAX, MAX_SELECTED, new_token

log = logging.getLogger("app.listing_requests")

__all__ = [
    "CALLBACK_TEXT_MAX",
    "MAX_SELECTED",
    "build_options_email",
    "clean_callback_text",
    "open_request",
    "options_url",
    "send_options_email",
]


def options_url(token: str) -> str | None:
    """The client's page for one request, or None when no public URL is set.

    None rather than a broken link, the same posture `_panel_link` takes: an
    email whose only call to action is `https:///options/ab12` is worse than an
    email with none, because the reader believes they clicked something.
    """
    from app.config import get_settings

    base = (get_settings().CONTENT_CTA_URL or "").strip().rstrip("/")
    return f"{base}/api/v1/public/options/{token}" if base else None


def clean_callback_text(raw: str | None) -> str | None:
    """What the client typed about when to call, made safe to store and quote.

    Newlines collapse and the whole thing is cut to `CALLBACK_TEXT_MAX`. Both
    are about the realtor's inbox rather than about safety in the abstract: the
    field is reachable by anyone holding a link we emailed, and an unbounded,
    multi-line value would let that person compose a message with its own fake
    headers inside her notice.

    Not sanitised further, and not parsed at all. It is quoted to her under
    "They wrote" and never reaches a model or a calendar.
    """
    if raw is None:
        return None
    flat = " ".join(str(raw).split())
    return flat[:CALLBACK_TEXT_MAX] or None


async def open_request(lead_id: int, *, origin: str = "message") -> tuple[int | None, bool]:
    """Open an options request for this lead, or hand back the open one.

    Returns `(request id, created)`. Never raises: a lead who asked for
    listings is already captured and answered, and a failure to file the task
    must not cost the conversation that produced it.

    `created` is what the caller keys the notice off, so a second email from
    the same person in the same afternoon reaches Natalia once. The database
    has the same rule under it — a partial unique index on `lead_id WHERE
    status = 'open'` — because this function can run twice at once and a check
    followed by an insert is not a decision, it is a race.
    """
    from app.db.base import get_session_factory

    try:
        async with get_session_factory()() as db:
            existing = (
                await db.execute(
                    select(ListingRequest).where(
                        ListingRequest.lead_id == lead_id,
                        ListingRequest.status == ListingRequestStatus.OPEN,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing.id), False

            row = ListingRequest(
                lead_id=lead_id,
                token=new_token(),
                status=ListingRequestStatus.OPEN,
                origin=origin,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                # The index bit. Somebody else opened one between the select
                # above and this insert, which is the ordinary outcome when two
                # emails land together — not an error to report, just a request
                # that already exists.
                await db.rollback()
                other = (
                    await db.execute(
                        select(ListingRequest).where(
                            ListingRequest.lead_id == lead_id,
                            ListingRequest.status == ListingRequestStatus.OPEN,
                        )
                    )
                ).scalar_one_or_none()
                return (int(other.id), False) if other is not None else (None, False)
            log.info("Lead %d: options request %d opened (%s)", lead_id, row.id, origin)
            return int(row.id), True
    except Exception as exc:  # noqa: BLE001 — the conversation already happened
        log.error("Lead %d: could not open an options request: %s", lead_id, exc)
        return None, False


def _money(value: object) -> str | None:
    try:
        return f"${int(float(value)):,}"
    except (TypeError, ValueError):
        return None


def _address_of(prop: object) -> str:
    """The one line that identifies the place.

    Falls back to the title when there is no address, because a numbered entry
    with no identity at all is worse than a marketing headline.
    """
    address = (getattr(prop, "address", None) or "").strip()
    city = (getattr(prop, "city", None) or "").strip()
    state = (getattr(prop, "state", None) or "").strip()
    zip_code = (getattr(prop, "zip_code", None) or "").strip()
    tail = " ".join(part for part in (city, state, zip_code) if part)
    if address and tail:
        return f"{address}, {tail}"
    return address or tail or (getattr(prop, "title", None) or "").strip() or "—"


def _facts_line(prop: object) -> str | None:
    """Price, beds, baths, size, year — whichever of them we actually have.

    Assembled from present values rather than printed with blanks: "5 bd · None
    ba" is the kind of detail that makes a reader stop trusting the numbers
    beside it, and this product has already paid for that once, when a null
    reached a video as the literal word "None".
    """
    bits: list[str] = []
    if (price := _money(getattr(prop, "price", None))) is not None:
        bits.append(price)
    beds = getattr(prop, "bedrooms", None)
    if beds:
        bits.append(f"{int(beds)} bd")
    baths = getattr(prop, "bathrooms", None)
    if baths:
        # 2.5 stays 2.5; 3.0 prints as 3. Half-baths are a real distinction in
        # the USA and rounding them away changes what is being offered.
        as_float = float(baths)
        bits.append(f"{as_float:g} ba")
    if sqft := getattr(prop, "sqft", None):
        bits.append(f"{int(sqft):,} sq ft")
    return " · ".join(bits) or None


def _option_lines(prop: object, index: int) -> list[str]:
    """One listing, as the client will read it. An ALLOW-LIST — see the module
    docstring for what is on the other side of it."""
    lines = [f"{index}. {_address_of(prop)}"]
    if (facts := _facts_line(prop)) is not None:
        lines.append(f"   {facts}")
    # Colorado Rule 6.10.A.4: the advertisement names the brokerage. On a
    # listing that belongs to another firm this is not a courtesy, it is the
    # condition on which we are allowed to put it in front of a consumer at all.
    from app.services.listings import listing_broker

    raw = getattr(prop, "raw", None)
    office = raw.get("list_office_name") if isinstance(raw, dict) else None
    if (broker := listing_broker(office, getattr(prop, "source", None))) :
        lines.append(f"   Listed by {broker}")
    if url := (getattr(prop, "url", None) or "").strip():
        lines.append(f"   {url}")
    return lines


def build_options_email(
    *,
    lead_name: str | None,
    zone: str | None,
    properties: list,
    agent_name: str | None,
    page_url: str | None,
) -> tuple[str, str]:
    """`(subject, body)` for the shortlist. No footer — the caller adds it.

    Kept separate from the send so the whole text can be screened, asserted on
    and read in a test without a mail provider anywhere near it.
    """
    who = (lead_name or "").strip().split(" ")[0]
    where = (zone or "").strip()
    count = len(properties)
    subject = (
        f"{count} place{'s' if count != 1 else ''} in {where}" if where
        else f"{count} place{'s' if count != 1 else ''} to look at"
    )
    picked_by = (agent_name or "").strip()
    opening = (
        f"{picked_by} went through what's active and picked these"
        if picked_by
        else "We went through what's active and picked these"
    )
    parts = [
        f"Hi {who}," if who else "Hi,",
        "",
        f"{opening}{f' in {where}' if where else ''}.",
        "",
    ]
    for index, prop in enumerate(properties, start=1):
        parts.extend(_option_lines(prop, index))
        parts.append("")
    if page_url:
        parts.extend(
            [
                "Not what you had in mind, or would you rather talk it through?",
                "Both from here:",
                page_url,
                "",
            ]
        )
    return subject, "\n".join(parts)


async def send_options_email(
    request_id: int, property_ids: list[int], *, agent_name: str | None = None
) -> dict[str, object]:
    """Mail the shortlist to the lead, and record what happened. Never raises.

    The order of the gates below is the order of their costs. Opt-out first,
    because sending to someone who asked us to stop is the one failure with a
    statutory price on it. Then the footer, which refuses rather than degrades —
    no postal address, no send. Then Fair Housing over the finished text, on the
    email lane's blocking setting, because this message is written by us and
    signed with the agency's brokerage line.

    The `Message` row is written AFTER the provider answers. A PENDING row
    written first is what `delivery.py::_still_owed` sweeps up and re-sends,
    which would mail the shortlist twice.
    """
    from app.db.base import get_session_factory
    from app.models import AgentSettings, Conversation, Lead, Property
    from app.models.message import (
        Message,
        MessageDirection,
        MessageSender,
        MessageStatus,
    )
    from app.services.delivery import MAX_ATTEMPTS
    from app.services.email import send_email
    from app.services.email_compliance import (
        MissingPostalAddress,
        build_footer,
        unsubscribe_url,
    )
    from app.services.fair_housing import find_violations
    from app.services.tenant_context import get_org_id

    async with get_session_factory()() as db:
        row = (
            await db.execute(select(ListingRequest).where(ListingRequest.id == request_id))
        ).scalar_one_or_none()
        if row is None:
            return {"status": "unknown_request"}
        lead = (
            await db.execute(select(Lead).where(Lead.id == row.lead_id))
        ).scalar_one_or_none()
        if lead is None:
            return {"status": "unknown_lead"}

        # FIRST. `may_send_automated` reads this same field ahead of everything
        # else for every channel; read directly here so this function's own
        # behaviour is visible to the sweep that checks senders, rather than
        # hidden behind a call.
        if lead.opted_out_at is not None:
            log.info("Lead %d: options email suppressed — they opted out", lead.id)
            return {"status": "opted_out"}

        to = (lead.email or "").strip()
        if not to:
            return {"status": "no_email"}

        ids = [int(i) for i in property_ids][:MAX_SELECTED]
        if not ids:
            return {"status": "nothing_selected"}
        found = (
            await db.execute(select(Property).where(Property.id.in_(ids)))
        ).scalars().all()
        # Her order, not the database's: she ranked them by ticking them.
        by_id = {int(p.id): p for p in found}
        properties = [by_id[i] for i in ids if i in by_id]
        if not properties:
            return {"status": "nothing_selected"}

        cfg = (
            await db.execute(
                select(AgentSettings).where(AgentSettings.org_id == get_org_id())
            )
        ).scalar_one_or_none()
        subject, body = build_options_email(
            lead_name=lead.name,
            zone=lead.zone,
            properties=properties,
            # Whoever pressed the button, when the route knows. There is no
            # agent name in Settings and inventing one from `agency_name` would
            # put a company where a person belongs — the sentence says a human
            # went through the listings, and it has to be true.
            agent_name=agent_name,
            page_url=options_url(row.token),
        )

        try:
            footer = build_footer(
                lead_id=lead.id,
                brokerage_line=(getattr(cfg, "brokerage_line", None) or None),
                lang=None,
            )
        except MissingPostalAddress as exc:
            log.error("Lead %d: no options email — %s", lead.id, exc)
            return {"status": "blocked_no_postal_address"}
        body = f"{body}\n{footer}"

        flags = find_violations(body, None)
        if flags:
            # Blocked, and she is told rather than the message quietly not
            # going. The phrase is almost always in an address or a brokerage
            # name, so a person can clear it in seconds — and the one time it
            # is not, sending would have been the mistake.
            log.error("Lead %d: options email blocked by Fair Housing: %s", lead.id, flags)
            return {"status": "blocked_fair_housing", "flags": flags}

        external_id: str | None = None
        failure: str | None = None
        try:
            result = await send_email(
                to=to,
                subject=subject,
                body_text=body,
                unsubscribe_url=unsubscribe_url(lead.id),
            )
            external_id = (result or {}).get("id")
            if not external_id:
                failure = "the provider accepted the send but returned no id"
        except Exception as exc:  # noqa: BLE001 — the row must still be written
            failure = str(exc)[:500]
            log.error("Lead %d: options email failed: %s", lead.id, exc)

        conv_id = (
            await db.execute(
                select(Conversation.id)
                .where(Conversation.lead_id == lead.id, Conversation.channel == "email")
                .order_by(Conversation.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if conv_id is not None:
            db.add(
                Message(
                    conversation_id=conv_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content=body,
                    subject=subject,
                    external_id=external_id,
                    delivery_status=(
                        MessageStatus.SENT if external_id else MessageStatus.FAILED
                    ),
                    last_error=failure,
                    # Spent when the send failed, for the same reason the
                    # notice spends it: the sweep must not decide on its own to
                    # re-mail a shortlist a person chose by hand.
                    send_attempts=0 if external_id else MAX_ATTEMPTS,
                )
            )
        if external_id:
            row.status = ListingRequestStatus.SENT
            row.selected_property_ids = ids
            row.sent_at = datetime.now(UTC)
        await db.commit()

        if not external_id:
            return {"status": "send_failed", "error": failure}
        return {"status": "sent", "count": len(properties), "message_id": external_id}
