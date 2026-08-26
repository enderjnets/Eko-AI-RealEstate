"""Agency settings API — read + update the singleton AgentSettings row (id=1).

One deploy = one inmobiliaria, so there is exactly one settings row. The
orchestrator reads `agent_persona`, `agency_name`, `greeting_template`,
`languages`, and `business_hours` from it at request time (see
`app/services/conversation.py`). This endpoint backs the Phase 6 branding
panel: a realtor opens `/settings` in the dashboard and configures how their
AI agent introduces itself and which languages it answers in.

GET auto-creates the singleton with sensible Spanish defaults if it does not
exist yet, so a freshly installed instance always returns a usable config.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.models import AgentSettings
from app.services.tenant_context import get_org_id

router = APIRouter()



class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agency_name: str
    # The Colorado-required brokerage identification, burned into every
    # rendered clip and checked again at publish time (content_render.py,
    # content_studio.py). Nullable: an unset value is what keeps both gates
    # closed, and is a fact the dashboard has to be able to show.
    brokerage_line: str | None
    agency_phone: str | None
    booking_contact_email: str | None
    agent_persona: str
    greeting_template: str
    languages: list[str]
    timezone: str
    business_hours: dict
    created_at: datetime
    updated_at: datetime


class SettingsPatch(BaseModel):
    """Partial update — any omitted field is left unchanged.

    `extra="forbid"` so a typo'd field 400s instead of silently no-op'ing.
    """
    model_config = ConfigDict(extra="forbid")

    agency_name: str | None = Field(default=None, min_length=1, max_length=160)
    # No min_length: sending "" is how a broker clears it, which must be
    # possible without a special endpoint — the render/publish gates already
    # treat blank-or-whitespace as "not set" (see content_render.py:279).
    brokerage_line: str | None = Field(default=None, max_length=200)
    agency_phone: str | None = Field(default=None, max_length=32)
    # Where Cal.com sends the confirmation for a lead who only gave a
    # phone number, which is most of them.
    # Not EmailStr: that pulls in an optional dependency the image does not
    # carry, and a wrong address here fails visibly at the first booking rather
    # than silently.
    booking_contact_email: str | None = Field(default=None, max_length=255)
    agent_persona: str | None = Field(default=None, min_length=1)
    greeting_template: str | None = Field(default=None, min_length=1)
    languages: list[str] | None = Field(default=None, min_length=1)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    business_hours: dict | None = None


async def _get_or_create(db: AsyncSession) -> AgentSettings:
    row = (
        await db.execute(select(AgentSettings).where(AgentSettings.org_id == _acting_org()))
    ).scalar_one_or_none()
    if row is None:
        # No pinned id: there is one settings row per organization now, and
        # forcing id=1 made the second tenant collide on the primary key.
        # org_id is stamped on flush from the acting org.
        row = AgentSettings()
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("", response_model=SettingsOut)
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)) -> SettingsOut:
    """Return the agency config, creating the singleton with defaults if absent."""
    row = await _get_or_create(db)
    return SettingsOut.model_validate(row)


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    """Apply a partial update to the agency config. PUT is idempotent here.

    Used by the dashboard branding panel. Only fields present in the request
    are written; the rest keep their current value.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "languages" in updates:
        # Normalize to lowercase 2-letter codes, drop blanks + dupes (order-stable).
        seen: set[str] = set()
        cleaned: list[str] = []
        for code in updates["languages"]:
            c = str(code).strip().lower()
            if c and c not in seen:
                seen.add(c)
                cleaned.append(c)
        if not cleaned:
            raise HTTPException(status_code=400, detail="`languages` cannot be empty")
        updates["languages"] = cleaned

    if "brokerage_line" in updates and updates["brokerage_line"] is not None:
        # Normalised here rather than trusted, because both consumers strip
        # before deciding (`content_render.py`, `content_studio.py`) and a
        # whitespace-only value would therefore render the Settings box as
        # FILLED while every gate treats it as empty. On a field whose whole
        # job is a legal obligation, a silent false "yes, it is set" is the
        # expensive direction to be wrong in. Trailing spaces would also be
        # burned into the video verbatim.
        updates["brokerage_line"] = updates["brokerage_line"].strip() or None

    if "timezone" in updates:
        tz = str(updates["timezone"]).strip()
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz}") from exc
        updates["timezone"] = tz

    row = await _get_or_create(db)
    for field, value in updates.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return SettingsOut.model_validate(row)


def _acting_org() -> int:
    """The org whose settings row applies to this call."""
    org_id = get_org_id()
    if org_id is None:
        # Was `or DEFAULT_ORG_ID`. It fails closed today because these paths run
        # on the RLS session — an unset org reads nothing and cannot write — but
        # the fallback is one `get_bypass_db` away from silently reading and
        # overwriting client zero's row, and there are six of these. Say so
        # instead of guessing.
        raise RuntimeError(
            "no acting organization is bound; refusing to fall back to the "
            "default one"
        )
    return org_id
