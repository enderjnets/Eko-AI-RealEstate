"""Leads API — list + detail + PATCH (Phase 2 dashboard needs)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import current_email
from app.db.base import get_db
from app.models import (
    CallLog,
    CallOutcome,
    Conversation,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
)
from app.models.lead import PreferredChannel
from app.services._common import ParsedMessage
from app.services.calls import CallUpdates, register_call
from app.services.conversation import (
    generate_reply_suggestions,
    handle_inbound_message,
    send_human_message,
)
from app.services.scoring import rescore_all, rescore_lead

router = APIRouter()


class LeadPatch(BaseModel):
    """Partial update for a lead. Any omitted field is left unchanged.

    Phase 2 dashboard uses this for: toggling `human_takeover` (pauses the AI
    reply), manually setting `status` (e.g., mark as WON / LOST after a visit),
    or correcting `name` / `zone` / `budget_*` typed by the human realtor.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    status: LeadStatus | None = None
    intent: LeadIntent | None = None
    zone: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    property_type: str | None = None
    urgency: str | None = None
    human_takeover: bool | None = None


class LeadCreate(BaseModel):
    """Body for POST /leads — a realtor manually adding a lead.

    Two uses, one path: (1) a live demo where the realtor poses as a client to
    experience the agent, (2) real CRM entry of a referral / contact. Either way
    the lead enters the same pipeline as auto-captured ones (scoring, intent,
    matching, follow-ups). An optional `first_message` is injected as an inbound
    turn so the AI classifies it, replies, and sends through `channel` — exactly
    the path a real inbound webhook takes. `phone` is the channel identifier
    (phone for sms, email address for email); it is stored on `Lead.phone`.
    """
    model_config = ConfigDict(extra="forbid")

    phone: str
    name: str | None = None
    intent: LeadIntent | None = None
    zone: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    property_type: str | None = None
    urgency: str | None = None
    # Only the text channels that work today. Voice (Phase 13) and WhatsApp
    # (deferred) are intentionally excluded so a request can't create a
    # conversation we can't deliver.
    channel: Literal["sms", "email"] = "sms"
    first_message: str | None = None


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    # Usually null — a WhatsApp lead gives a phone and nothing else — but it is
    # what makes the booking confirmation reach the client rather than only the
    # agency, so the realtor needs to see whether they have it.
    email: str | None
    name: str | None
    status: LeadStatus
    intent: LeadIntent | None
    budget_min: Decimal | None
    budget_max: Decimal | None
    zone: str | None
    property_type: str | None
    urgency: str | None
    human_takeover: bool
    # Surfaced so a realtor can SEE that this person asked us to stop. The
    # suppression is enforced server-side either way, but without it on screen
    # the dashboard looks identical for a lead who opted out and one who did
    # not — and the realtor is the one who would otherwise wonder why the
    # nurture sequence went quiet, or worse, text them by hand assuming the
    # system simply had nothing to say.
    opted_out_at: datetime | None = None
    consent_at: datetime | None = None
    score: int
    score_breakdown: dict
    needs_response: bool = False
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadListOut(BaseModel):
    total: int
    items: list[LeadOut]


class RescoreResult(BaseModel):
    rescored: int


@router.get("", response_model=LeadListOut)
async def list_leads(
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    intent: LeadIntent | None = Query(default=None),
    sort: str = Query(default="score", pattern="^(score|recent)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> LeadListOut:
    where: list = []
    if status_filter is not None:
        where.append(Lead.status == status_filter)
    if intent is not None:
        where.append(Lead.intent == intent)

    if sort == "recent":
        order = (Lead.last_message_at.desc().nullslast(), Lead.id.desc())
    else:  # score (default) — hottest first, then most recent
        order = (Lead.score.desc(), Lead.last_message_at.desc().nullslast(), Lead.id.desc())

    total = (await db.execute(select(func.count()).select_from(Lead).where(*where))).scalar_one()
    rows = (
        await db.execute(
            select(Lead).where(*where).order_by(*order).limit(limit).offset(offset)
        )
    ).scalars().all()
    pending = await _needs_response_map(db, [r.id for r in rows])
    items = []
    for r in rows:
        out = LeadOut.model_validate(r)
        out.needs_response = pending.get(r.id, False)
        items.append(out)
    return LeadListOut(total=total, items=items)


async def _needs_response_map(db: AsyncSession, lead_ids: list[int]) -> dict[int, bool]:
    """Per lead in `lead_ids`, True when the most recent message (any channel) is
    inbound — i.e. the lead spoke last and is waiting on us. Scoped to the page's
    leads (one grouped query, no N+1). Mirrors the inbox's `needs_response`."""
    if not lead_ids:
        return {}
    rows = (
        await db.execute(
            select(Conversation.lead_id, Message.direction)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id.in_(lead_ids))
            .order_by(Conversation.lead_id, Message.created_at.desc(), Message.id.desc())
            .distinct(Conversation.lead_id)
        )
    ).all()
    return {lead_id: direction == MessageDirection.INBOUND for lead_id, direction in rows}


@router.post("", response_model=LeadOut, status_code=201)
async def create_lead(body: LeadCreate, db: AsyncSession = Depends(get_db)) -> LeadOut:
    """Manually create a lead and (optionally) kick off the first AI turn.

    Dedupes by identifier (`phone`) → 409 if it already exists. When
    `first_message` is present it is injected as an inbound message so the
    orchestrator classifies it, generates a reply, and sends it through `channel`
    — the same path a real webhook takes. The lead is marked `meta.source=manual`
    (NOT a demo flag) so it persists as a first-class lead.
    """
    identifier = (body.phone or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="`phone` is required")

    existing = (
        await db.execute(select(Lead).where(Lead.phone == identifier))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A lead with this contact already exists")

    lead = Lead(
        phone=identifier,
        name=(body.name or None),
        intent=body.intent,
        zone=body.zone,
        budget_min=body.budget_min,
        budget_max=body.budget_max,
        property_type=body.property_type,
        urgency=body.urgency,
        meta={"source": "manual"},
    )
    db.add(lead)
    await db.flush()

    first = (body.first_message or "").strip()
    if first:
        parsed = ParsedMessage(
            channel=body.channel,
            external_id=f"manual:{uuid4().hex}",
            from_identifier=identifier,
            from_name=(body.name or None),
            content=first,
        )
        await handle_inbound_message(parsed, db)  # commits internally
    else:
        await rescore_lead(lead, db, commit=False)
        await db.commit()

    await db.refresh(lead)
    return LeadOut.model_validate(lead)


@router.get("/digest", response_model=list[LeadOut])
async def lead_digest(
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[LeadOut]:
    """Top hot/active leads by score — the 'who to call first' list.

    Excludes closed/paused leads (status gate already zeroes WON/LOST), and only
    returns leads scoring in the warm/hot range so the digest stays actionable.
    """
    rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.status.notin_([LeadStatus.WON, LeadStatus.LOST, LeadStatus.PAUSED]),
                Lead.score > 0,
            )
            .order_by(Lead.score.desc(), Lead.last_message_at.desc().nullslast())
            .limit(limit)
        )
    ).scalars().all()
    return [LeadOut.model_validate(r) for r in rows]


@router.post("/rescore-all", response_model=RescoreResult)
async def rescore_all_leads(db: AsyncSession = Depends(get_db)) -> RescoreResult:
    """Recompute every lead's score (admin / backfill / after a scoring change)."""
    n = await rescore_all(db)
    return RescoreResult(rescored=n)


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db)) -> LeadOut:
    row = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadOut.model_validate(row)


class HumanMessageIn(BaseModel):
    """Body for POST /leads/{id}/messages — the human realtor sending a reply."""
    model_config = ConfigDict(extra="forbid")

    text: str
    subject: str | None = None  # email-only override; otherwise inferred from last inbound
    # Optional explicit channel. Omit to auto-pick the most recently-active
    # conversation. Voice is NOT accepted (Phase 13) — a voice value is a 422.
    channel: Literal["sms", "email", "whatsapp"] | None = None


class HumanMessageResult(BaseModel):
    status: str
    lead_id: int | None = None
    channel: str | None = None
    outbound_id: int | None = None
    outbound_status: str | None = None
    error: str | None = None


@router.post("/{lead_id}/messages", response_model=HumanMessageResult)
async def post_human_message(
    lead_id: int,
    body: HumanMessageIn,
    db: AsyncSession = Depends(get_db),
) -> HumanMessageResult:
    """Send a human-authored reply, optionally choosing the channel.

    Dashboard composer endpoint. With `channel` omitted it auto-picks the most
    recently-active Conversation; with an explicit `channel` it sends on that
    channel (creating the thread if the lead hasn't used it yet). Returns 200 with
    a `status="error"` body when the lead is missing / has no active conversation
    (lets the UI surface a friendly error without parsing HTTP status codes).
    """
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="`text` is required")
    result = await send_human_message(
        lead_id, text, db, subject=body.subject, channel=body.channel
    )
    return HumanMessageResult(**result)  # type: ignore[arg-type]


class SuggestionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = 3


class SuggestionsOut(BaseModel):
    suggestions: list[str]
    provider: str | None = None
    model: str | None = None
    error: str | None = None


@router.post("/{lead_id}/suggestions", response_model=SuggestionsOut)
async def post_suggestions(
    lead_id: int,
    body: SuggestionsIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> SuggestionsOut:
    """Generate N alternative reply texts the human can pick / edit / send.

    Degrades gracefully: an LLM failure returns `{"suggestions": [], "error": "..."}`
    so the UI shows an empty state instead of crashing.
    """
    count = max(1, min(5, body.count if body else 3))
    result = await generate_reply_suggestions(lead_id, db, count=count)
    return SuggestionsOut(
        suggestions=result.get("suggestions") or [],
        provider=result.get("provider"),
        model=result.get("model"),
        error=result.get("error"),
    )


@router.patch("/{lead_id}", response_model=LeadOut)
async def patch_lead(
    lead_id: int,
    body: LeadPatch,
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    """Apply a partial update. Only fields present in the request are written.

    Common dashboard actions:
      - Toggle AI vs human: `{"human_takeover": true}` pauses auto-reply
      - Mark closed: `{"status": "won"}` / `{"status": "lost"}`
      - Correct extracted data: `{"zone": "Madrid centro", "budget_max": 1500}`
    """
    row = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    for field, value in updates.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return LeadOut.model_validate(row)


# ── Call console ───────────────────────────────────────────────────────────
#
# The console's claim is that marking a call is not filing it: one submit
# records what was learned and fires the single action the outcome implies.
# Everything about the shape of these models serves the one-minute rule — if
# logging a call takes longer than that it does not get done, and the data that
# does arrive is worse than none.


class CallIn(BaseModel):
    """Body for POST /leads/{id}/calls.

    Every field except `outcome` is optional. The console pre-fills what is
    already known and the advisor confirms or corrects it, so an omitted field
    means "did not come up" and must leave the lead's value alone — never blank
    it.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: CallOutcome
    note: str | None = None

    intent: LeadIntent | None = None
    urgency: str | None = None
    zone: str | None = None
    property_type: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    preferred_channel: PreferredChannel | None = None
    name: str | None = None
    email: str | None = None

    # Days from now. Capped at two years: a typo in a free-number field should
    # not silently park a lead past the point anyone would look for it.
    follow_up_in_days: int | None = Field(default=None, ge=0, le=730)

    # The advisor confirming the person asked, on the call, to be sent
    # something. This is the only thing that records consent here, and it is
    # deliberately not the same as `preferred_channel`: "text me rather than
    # email me" is a preference about how, not permission to begin.
    asked_for_texts: bool = False


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    outcome: CallOutcome
    note: str | None = None
    logged_by: str | None = None
    created_at: datetime


class CallResultOut(BaseModel):
    call: CallOut
    score: int
    follow_up_scheduled_for: datetime | None = None
    cancelled_follow_ups: int


@router.post("/{lead_id}/calls", response_model=CallResultOut, status_code=201)
async def log_call(
    lead_id: int,
    body: CallIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CallResultOut:
    """Record a call and carry out the one action its outcome implies."""
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await register_call(
        lead,
        body.outcome,
        db,
        logged_by=current_email(request),
        note=body.note,
        updates=CallUpdates(
            intent=body.intent,
            urgency=body.urgency,
            zone=body.zone,
            property_type=body.property_type,
            budget_min=Decimal(str(body.budget_min))
            if body.budget_min is not None
            else None,
            budget_max=Decimal(str(body.budget_max))
            if body.budget_max is not None
            else None,
            preferred_channel=body.preferred_channel,
            name=body.name,
            email=body.email,
        ),
        follow_up_in_days=body.follow_up_in_days,
        asked_for_texts=body.asked_for_texts,
    )
    return CallResultOut(
        call=CallOut.model_validate(result.call),
        score=result.score,
        follow_up_scheduled_for=(
            result.follow_up.scheduled_for if result.follow_up else None
        ),
        cancelled_follow_ups=result.cancelled_follow_ups,
    )


@router.get("/{lead_id}/calls", response_model=list[CallOut])
async def list_calls(
    lead_id: int, db: AsyncSession = Depends(get_db)
) -> list[CallOut]:
    rows = (
        await db.execute(
            select(CallLog)
            .where(CallLog.lead_id == lead_id)
            .order_by(CallLog.created_at.desc())
        )
    ).unique().scalars().all()
    return [CallOut.model_validate(r) for r in rows]
