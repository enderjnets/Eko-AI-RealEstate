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
import re
from datetime import UTC, datetime
from html import escape, unescape
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ListingRequest, ListingRequestStatus
from app.models.listing_request import CALLBACK_TEXT_MAX, MAX_SELECTED, new_token
from app.services.email_html import document as _document

log = logging.getLogger("app.listing_requests")

__all__ = [
    "CALLBACK_TEXT_MAX",
    "MAX_SELECTED",
    "build_options_email",
    "clean_callback_text",
    "open_callback_link",
    "open_request",
    "options_url",
    "send_options_email",
    "strip_tags",
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


#: How much of a "why" survives. Long enough for the real thing — "under your
#: ceiling, 2 bd, garage for 2, in DTC" — and short enough that the box cannot
#: become a paragraph nobody screened properly on its way to a stranger.
REASON_TEXT_MAX = 240


def clean_reason_text(raw: str | None) -> str | None:
    """A line about why this listing was picked, made safe to send.

    Same treatment as `clean_callback_text` and for a mirrored reason: that one
    protects the realtor's inbox from the client, this one protects the
    client's inbox from whatever ends up in a form field on our side. Flattened
    and cut; never parsed, never handed to a model.
    """
    if raw is None:
        return None
    flat = " ".join(str(raw).split())
    return flat[:REASON_TEXT_MAX] or None


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


async def open_link(lead_id: int, *, origin: str) -> tuple[str | None, int | None, bool]:
    """`(url, request id, created)` for this lead's open request, opening one.

    The caller gets `created` back instead of a notice, and that split is the
    whole reason this function exists. A turn needs the URL BEFORE it generates
    its reply — the model is told whether there is a link — but the notice that
    goes with a new request writes `leads.meta` from a second session, and
    doing that while the turn's own transaction still holds that row deadlocks
    the turn against itself.

    Not a fear: it hung a run for two minutes, and `pg_stat_activity` named
    both sides — one connection `idle in transaction`, the other waiting on
    `UPDATE leads SET meta = …`. Opening the row is safe in the same place,
    because the foreign key takes a share lock that does not fight the turn's
    own update of the lead. So the row opens early and the notice waits for the
    commit.

    `origin` decides which notice the agency eventually gets. It matters here
    because a lead may hold only ONE open request — a partial unique index on
    `lead_id WHERE status = 'open'` — so whoever opens it first names it.
    """
    request_id, created = await open_request(lead_id, origin=origin)
    if request_id is None:
        return None, None, False
    from app.db.base import get_session_factory

    async with get_session_factory()() as db:
        token = (
            await db.execute(
                select(ListingRequest.token).where(ListingRequest.id == request_id)
            )
        ).scalar_one_or_none()
    return (options_url(token) if token else None), request_id, created


async def open_callback_link(lead_id: int) -> str | None:
    """A public URL where this person can say when they want to be called.

    Reuses the options request row rather than growing a second table: the row
    already IS "the ask, as something a person can work", it already carries a
    token, a public page, a 200-character field for their own words and a
    status of `callback_requested`, and the notice it produces already leaves
    out the picker link — because when somebody asks for a call there is
    nothing to pick.

    Returns None when a link cannot be made, and the caller is expected to say
    the same thing without one rather than print a broken address.
    """
    url, _request_id, _created = await open_link(lead_id, origin="callback")
    return url


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


def _safe_url(raw: object) -> str | None:
    """An `http(s)` link, or nothing.

    The value arrives from another brokerage's MLS row and now ends up inside
    an `href`. In plain text a `javascript:` or `data:` URL is inert rubbish;
    rendered as an anchor it is a link a client can click. Anything that is not
    plainly http or https is dropped rather than printed, on both halves — a
    scheme we do not recognise is not a tour.
    """
    url = (str(raw).strip() if raw is not None else "")
    if not url:
        return None
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return None
    return url if scheme in ("http", "https") else None


def _tour_host(url: str) -> str:
    """`my.matterport.com` out of the full link, `www.` dropped.

    Printed beside the link on purpose. The MLS field is called *unbranded* and
    the branded variant does not even exist in the export — but the page on the
    other end is still somebody else's, and measured on the first real import
    one of the eight was a listing agent's own YouTube channel, Subscribe
    button and all. We cannot see through the link, so we say where it goes.
    """
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _option_fields(
    prop: object, index: int, *, reason: str | None = None
) -> dict[str, object]:
    """One listing reduced to the handful of facts a client may see.

    An ALLOW-LIST — see the module docstring for what is on the other side of
    it — and the single source both renderings read. Text and HTML that each
    assembled their own would be two places for a Fair Housing screen to miss.
    """
    # Colorado Rule 6.10.A.4: the advertisement names the brokerage. On a
    # listing that belongs to another firm this is not a courtesy, it is the
    # condition on which we are allowed to put it in front of a consumer at all.
    from app.services.listings import listing_broker

    raw = getattr(prop, "raw", None)
    office = raw.get("list_office_name") if isinstance(raw, dict) else None
    return {
        "n": index,
        "address": _address_of(prop),
        "facts": _facts_line(prop),
        "broker": listing_broker(office, getattr(prop, "source", None)) or None,
        "url": _safe_url(getattr(prop, "url", None)),
        # Why this one. Always a key, never conditionally absent: the allow-list
        # only holds if every field that can be printed is named here, and a
        # `fields.get("reason")` somewhere downstream is how operator-written
        # text eventually reaches a template nobody screened.
        "reason": reason or None,
    }


def _option_lines(
    prop: object, index: int, *, reason: str | None = None
) -> list[str]:
    """One listing, as the client will read it in a text-only mail client."""
    f = _option_fields(prop, index, reason=reason)
    lines = [f"{f['n']}. {f['address']}"]
    if f["facts"] is not None:
        lines.append(f"   {f['facts']}")
    if f["broker"]:
        lines.append(f"   Listed by {f['broker']}")
    # Above the tour link on purpose: the reason is why they should open it.
    if f["reason"]:
        lines.append(f"   Why: {f['reason']}")
    if f["url"]:
        lines.append(f"   {f['url']}")
    return lines


def _option_html(prop: object, index: int, *, reason: str | None = None) -> str:
    """The same listing for the HTML half. Every value escaped.

    These strings came out of another firm's MLS row and are about to be
    rendered as a document: an address or a brokerage name carrying a `<` is
    not an attack anyone planned, it is just data, and either way it must not
    become markup.
    """
    f = _option_fields(prop, index, reason=reason)
    rows = [
        f'<div style="font-weight:600;">{f["n"]}. {escape(str(f["address"]))}</div>'
    ]
    if f["facts"] is not None:
        rows.append(
            f'<div style="color:#444;">{escape(str(f["facts"]))}</div>'
        )
    if f["broker"]:
        rows.append(
            '<div style="font-size:12px;color:#6b6b6b;font-style:italic;">'
            f'Listed by {escape(str(f["broker"]))}</div>'
        )
    if f["reason"]:
        # Escaped like everything else here. This string may have been typed by
        # a person into a form, which is exactly the input that must not become
        # markup on its way to somebody else's inbox.
        rows.append(
            '<div style="margin-top:6px;font-size:13px;color:#7a1f3d;">'
            f'{escape(str(f["reason"]))}</div>'
        )
    if f["url"]:
        url = str(f["url"])
        host = _tour_host(url)
        where = f" <span style=\"color:#8a8a8a;\">({escape(host)})</span>" if host else ""
        rows.append(
            f'<div style="font-size:13px;"><a href="{escape(url, quote=True)}" '
            f'style="color:#7a1f3d;">Virtual tour</a>{where}</div>'
        )
    return (
        '<div style="margin:0 0 18px 0;padding:12px 14px;'
        'border-left:3px solid #e6d9c2;background:#fbfaf8;">'
        + "".join(rows)
        + "</div>"
    )


def strip_tags(html: str) -> str:
    """The words out of an HTML body, for screening it as if it were text."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(div|p|tr|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(text)


def build_options_email(
    *,
    lead_name: str | None,
    zone: str | None,
    properties: list,
    agent_name: str | None,
    page_url: str | None,
    reasons: dict[int, str] | None = None,
) -> tuple[str, str, str]:
    """`(subject, text, html)` for the shortlist. No footer — the caller adds it.

    Kept separate from the send so the whole text can be screened, asserted on
    and read in a test without a mail provider anywhere near it.

    Two bodies, one set of facts. The HTML exists because the plain-text half
    has to print every link in full, and a message that ends in two seventy
    character URLs reads like a machine wrote it — which is the opposite of
    what this message claims, that a person went through the listings. Both are
    sent: `send_email` puts `text` and `html` in the same request, so a client
    that renders neither HTML nor our styling still gets the whole message.
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
    greeting = f"Hi {who}," if who else "Hi,"
    intro = f"{opening}{f' in {where}' if where else ''}."

    parts = [greeting, "", intro, ""]
    blocks = [
        f'<p style="margin:0 0 6px 0;">{escape(greeting)}</p>',
        f'<p style="margin:0 0 20px 0;">{escape(intro)}</p>',
    ]
    why = reasons or {}
    for index, prop in enumerate(properties, start=1):
        reason = why.get(int(getattr(prop, "id", 0) or 0))
        parts.extend(_option_lines(prop, index, reason=reason))
        parts.append("")
        blocks.append(_option_html(prop, index, reason=reason))

    if page_url:
        ask = "Not what you had in mind, or would you rather talk it through?"
        parts.extend([ask, "Both from here:", page_url, ""])
        link = _safe_url(page_url)
        if link:
            blocks.append(
                f'<p style="margin:22px 0 0 0;">{escape(ask)}<br>'
                f'<a href="{escape(link, quote=True)}" style="color:#7a1f3d;">'
                "Both from here</a>.</p>"
            )
        else:
            blocks.append(f'<p style="margin:22px 0 0 0;">{escape(ask)}</p>')

    return subject, "\n".join(parts), "".join(blocks)


async def send_options_email(
    request_id: int,
    property_ids: list[int],
    *,
    agent_name: str | None = None,
    reasons: dict[int, str] | None = None,
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
        build_footer_html,
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
        # What each listing is doing on the list. The operator's own words when
        # she wrote any, the generated line otherwise, and nothing at all for a
        # property she picked by hand from outside the ranking — inventing a
        # reason for one is the one thing this must never do.
        stored = {
            int(item.get("property_id", 0)): item.get("reason")
            for item in (row.suggestions or [])
            if isinstance(item, dict)
        }
        edited = {int(k): v for k, v in (reasons or {}).items()}
        effective: dict[int, str] = {}
        for pid in ids:
            text_for = clean_reason_text(edited.get(pid)) or clean_reason_text(
                stored.get(pid)
            )
            if text_for:
                effective[pid] = text_for

        # Screened one by one BEFORE the body is assembled, so a rejection can
        # name the box. The whole-body screen below still runs — this is an
        # earlier, more specific check and not a replacement for it.
        per_property = [
            {"property_id": pid, "flags": found}
            for pid, line in effective.items()
            if (found := find_violations(line, None))
        ]
        if per_property:
            log.error(
                "Lead %d: a reason was blocked by Fair Housing: %s", lead.id, per_property
            )
            return {
                "status": "blocked_fair_housing",
                "flags": [f for item in per_property for f in item["flags"]],
                "per_property": per_property,
            }

        subject, body, html_body = build_options_email(
            lead_name=lead.name,
            zone=lead.zone,
            properties=properties,
            reasons=effective,
            # Whoever pressed the button, when the route knows. There is no
            # agent name in Settings and inventing one from `agency_name` would
            # put a company where a person belongs — the sentence says a human
            # went through the listings, and it has to be true.
            agent_name=agent_name,
            page_url=options_url(row.token),
        )

        brokerage = getattr(cfg, "brokerage_line", None) or None
        try:
            footer = build_footer(
                lead_id=lead.id, brokerage_line=brokerage, lang=None
            )
            footer_html = build_footer_html(
                lead_id=lead.id, brokerage_line=brokerage, lang=None
            )
        except MissingPostalAddress as exc:
            log.error("Lead %d: no options email — %s", lead.id, exc)
            return {"status": "blocked_no_postal_address"}
        body = f"{body}\n{footer}"
        html_body = _document(html_body + footer_html)

        # Screened on BOTH halves, not on the one the gate happens to read. The
        # text body is what `Message.content` stores and what every existing
        # test inspects; the HTML is what most people will actually see. A
        # phrase that reached only one of them would be a phrase that reached
        # the reader, so the two are checked and the flags are merged.
        flags = find_violations(body, None) + [
            f for f in find_violations(strip_tags(html_body), None)
            if f not in find_violations(body, None)
        ]
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
                body_html=html_body,
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
            # In the SAME commit as the ids and only when the provider answered.
            # Written earlier it would be a record of a send that did not
            # happen, which is the mistake this function's own docstring warns
            # about for the `Message` row.
            row.sent_reasons = {str(k): v for k, v in effective.items()}
            row.sent_at = datetime.now(UTC)
        await db.commit()

        if not external_id:
            return {"status": "send_failed", "error": failure}
        return {"status": "sent", "count": len(properties), "message_id": external_id}


# ── The preselection ──────────────────────────────────────────────────────

#: How many the system proposes. More than the six she may send, because the
#: point of a proposal is that she can throw two away without going hunting.
SUGGEST_LIMIT = 8


def _jsonable(value: object) -> object:
    """Decimals into strings, recursively. JSONB will not take a Decimal.

    Strings rather than floats: these are prices and half-baths, and the whole
    reason `baths_min` is NUMERIC(3,1) is that this codebase has already paid
    for float arithmetic on money once.
    """
    from decimal import Decimal as _D

    if isinstance(value, _D):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


async def _already_sent_ids(lead_id: int, db) -> set[int]:
    """Everything this lead has already been emailed, across every request.

    Without it a "show me a different set" hands back the same six, which is
    the one answer guaranteed to read as nobody having looked.
    """
    rows = (
        await db.execute(
            select(ListingRequest.selected_property_ids).where(
                ListingRequest.lead_id == lead_id,
                ListingRequest.status != ListingRequestStatus.OPEN,
            )
        )
    ).scalars().all()
    out: set[int] = set()
    for ids in rows:
        for i in ids or []:
            if isinstance(i, int):
                out.add(i)
    return out


async def suggest_for_request(request_id: int) -> None:
    """Rank what is active against what they asked for, and store it. Never raises.

    ⚠️ NOT called from `open_request`. That runs inside the turn's own
    transaction — the requirements the classifier just extracted are not yet
    visible to any other session — so scoring there would rank against a lead
    as it was before the message. This is called at the points where the agency
    is told, after the commit, and again after a CSV import.

    A failure here costs the proposal and nothing else: the request is already
    filed and the notice still goes out, saying honestly that nothing matched.
    """
    from dataclasses import asdict  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415

    from sqlalchemy import func  # noqa: PLC0415

    from app.models import Lead, Property, PropertyStatus  # noqa: PLC0415
    from app.services.listing_match import (  # noqa: PLC0415
        reason_text,
        requirements_of,
        score_property,
        unmet_summary,
    )
    from app.services.listings import candidate_pool  # noqa: PLC0415

    try:
        from app.db.base import get_session_factory  # noqa: PLC0415

        async with get_session_factory()() as db:
            row = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            lead = (
                await db.execute(select(Lead).where(Lead.id == row.lead_id))
            ).scalar_one_or_none()
            if lead is None:
                return

            req = requirements_of(lead)
            pool = await candidate_pool(lead, db)
            active_total = (
                await db.execute(
                    select(func.count())
                    .select_from(Property)
                    .where(Property.status == PropertyStatus.ACTIVE)
                )
            ).scalar_one()

            skip = await _already_sent_ids(lead.id, db)
            scored = []
            for prop in pool:
                if prop.id in skip:
                    continue
                score, checks = score_property(prop, req)
                scored.append((score, prop, checks))
            scored.sort(key=lambda t: (-t[0], t[1].price or Decimal(0)))
            top = scored[:SUGGEST_LIMIT]

            # Reassigned wholesale, never mutated: SQLAlchemy does not see a
            # list that changed under it.
            row.suggestions = [
                {
                    "property_id": prop.id,
                    "score": score,
                    "reason": reason_text(checks),
                    "checks": [
                        {"key": c.key, "status": c.status, "detail": c.detail}
                        for c in checks
                    ],
                }
                for score, prop, checks in top
            ]
            row.requirements_snapshot = _jsonable(asdict(req))
            row.match_summary = {
                "matched": len(pool),
                "active": int(active_total),
                "unmet": unmet_summary([c for _, _, c in top], req),
            }
            row.suggested_at = datetime.now(UTC)
            await db.commit()
            log.info(
                "Request %d: %d suggestions from %d in the area, %d active",
                request_id, len(top), len(pool), active_total,
            )
    except Exception as exc:  # noqa: BLE001 — the ask is already filed
        log.error("Request %d: could not build a preselection: %s", request_id, exc)
