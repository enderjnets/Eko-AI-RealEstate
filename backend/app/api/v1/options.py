"""The realtor's side of the options circuit: see the ask, pick, send.

One screen, three calls. It exists because this product has no MLS API — the
data leaves Matrix by hand — so the step in the middle is a person, and the
software's job is to carry the ask to her and the answer back.

**The budget is deliberately not a filter here.** `match_properties_for_lead`
excludes anything above `budget_max * 1.10`, and on 2026-09-19 that field was
measured holding a DOWN PAYMENT: lead 1269 said "$35,000 saved" and the
classifier filed it as the purchase budget, which excludes every house in
Denver. Filtering the picker on a number we know to be wrong would hand her an
empty screen and call it "nothing available". Until `solve_price()` runs over
rent/savings/credit, she is the filter — so this narrows by intent and area,
shows the price, and lets a person decide.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import (
    Lead,
    LeadIntent,
    ListingRequest,
    ListingRequestStatus,
    Property,
    PropertyStatus,
)
from app.models.listing_request import MAX_SELECTED
from app.services.listing_requests import send_options_email

router = APIRouter()


class RequestOut(BaseModel):
    id: int
    status: str
    origin: str
    lead_id: int
    lead_name: str | None
    lead_email: str | None
    lead_zone: str | None
    lead_intent: str | None
    lead_urgency: str | None
    #: Their own words, so she is choosing against what they said rather than
    #: against four fields a model extracted from it.
    they_wrote: str | None
    selected_property_ids: list
    callback_text: str | None
    created_at: str | None
    sent_at: str | None


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[union-attr]


async def _they_wrote(lead_id: int, db: AsyncSession) -> str | None:
    from app.models import Conversation
    from app.models.message import Message, MessageDirection

    return (
        await db.execute(
            select(Message.content)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.lead_id == lead_id,
                Message.direction == MessageDirection.INBOUND,
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _as_out(row: ListingRequest, db: AsyncSession) -> RequestOut:
    lead = (await db.execute(select(Lead).where(Lead.id == row.lead_id))).scalar_one_or_none()
    return RequestOut(
        id=int(row.id),
        status=row.status.value,
        origin=row.origin,
        lead_id=int(row.lead_id),
        lead_name=getattr(lead, "name", None),
        lead_email=getattr(lead, "email", None),
        lead_zone=getattr(lead, "zone", None),
        lead_intent=(lead.intent.value if lead and lead.intent else None),
        lead_urgency=getattr(lead, "urgency", None),
        they_wrote=await _they_wrote(int(row.lead_id), db),
        selected_property_ids=list(row.selected_property_ids or []),
        callback_text=row.callback_text,
        created_at=_iso(row.created_at),
        sent_at=_iso(row.sent_at),
    )


@router.get("", response_model=list[RequestOut])
async def list_requests(
    status_filter: str | None = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[RequestOut]:
    """Everything waiting on her, newest first. `?status=all` for the history."""
    stmt = select(ListingRequest).order_by(ListingRequest.created_at.desc()).limit(limit)
    if status_filter and status_filter != "all":
        try:
            wanted = ListingRequestStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail="unknown_status") from None
        stmt = stmt.where(ListingRequest.status == wanted)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _as_out(r, db) for r in rows]


class CandidateOut(BaseModel):
    id: int
    address: str | None
    city: str | None
    zone: str | None
    price: Decimal | None
    bedrooms: int | None
    bathrooms: Decimal | None
    sqft: int | None
    url: str | None
    listing_broker: str | None


class RequestDetailOut(BaseModel):
    request: RequestOut
    candidates: list[CandidateOut]
    max_selected: int = MAX_SELECTED


@router.get("/{request_id}", response_model=RequestDetailOut)
async def get_request(
    request_id: int,
    limit: int = Query(default=40, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> RequestDetailOut:
    row = (
        await db.execute(select(ListingRequest).where(ListingRequest.id == request_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown_request")
    lead = (await db.execute(select(Lead).where(Lead.id == row.lead_id))).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="unknown_lead")

    from app.services.listings import listing_broker, zone_matches

    rows = (
        await db.execute(select(Property).where(Property.status == PropertyStatus.ACTIVE))
    ).scalars().all()
    want_rent = lead.intent == LeadIntent.RENT
    candidates: list[Property] = []
    for p in rows:
        listing_type = (p.raw or {}).get("listing_type", "sale")
        if want_rent != (listing_type == "rent"):
            continue
        # `zone_matches`, not a substring test. "Wash Park" is what a person
        # writes and "Washington Park" is what REcolorado files, and neither
        # contains the other — measured in production with eight listings
        # loaded and this screen returning zero.
        if not zone_matches(lead.zone, p.zone):
            continue
        candidates.append(p)
    candidates.sort(key=lambda p: (p.price if p.price is not None else Decimal("0")))

    def _broker(p: Property) -> str | None:
        raw = p.raw if isinstance(p.raw, dict) else {}
        return listing_broker(raw.get("list_office_name"), p.source)

    return RequestDetailOut(
        request=await _as_out(row, db),
        candidates=[
            CandidateOut(
                id=int(p.id),
                address=p.address,
                city=p.city,
                zone=p.zone,
                price=p.price,
                bedrooms=p.bedrooms,
                bathrooms=p.bathrooms,
                sqft=p.sqft,
                url=p.url,
                listing_broker=_broker(p),
            )
            for p in candidates[:limit]
        ],
    )


class SendIn(BaseModel):
    property_ids: list[int] = Field(min_length=1, max_length=MAX_SELECTED)


@router.post("/{request_id}/send")
async def send_selection(
    request_id: int, body: SendIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    """Mail what she ticked, in the order she ticked it.

    The ceiling is enforced by the schema AND again inside the service. Two
    checks for one rule because they answer different questions: this one keeps
    a malformed request out, and the other keeps the rule true for every caller
    that ever reaches the service — including the next route somebody adds.
    """
    row = (
        await db.execute(select(ListingRequest).where(ListingRequest.id == request_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown_request")
    if row.status == ListingRequestStatus.SENT:
        # Not an error to shout about, but not a second email either: a double
        # click on a phone must not mail the same person twice.
        raise HTTPException(status_code=409, detail="already_sent")

    # Whose name the email says went through the listings. A courtesy, and it
    # must never be the reason a send fails — hence the swallow.
    from app.api.v1.auth import _token_from_request
    from app.services.auth import token_email

    try:
        who = token_email(_token_from_request(request))
    except Exception:  # noqa: BLE001
        who = None

    result = await send_options_email(request_id, body.property_ids, agent_name=who)
    status = result.get("status")
    if status == "sent":
        return result
    if status in {"opted_out", "no_email", "nothing_selected"}:
        raise HTTPException(status_code=409, detail=str(status))
    if status == "blocked_fair_housing":
        raise HTTPException(status_code=422, detail=result)
    if status == "blocked_no_postal_address":
        raise HTTPException(status_code=503, detail=str(status))
    raise HTTPException(status_code=502, detail=result)
