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
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
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

    # Two validators, split by whether the COLUMN is nullable, and the split is
    # load-bearing. A single "trim, and None if empty" rule would turn
    # `agency_name=" "` into None, which the handler's blind `setattr` writes
    # straight into a NOT NULL column: a 500 where a 422 belongs.
    #
    # Both are `mode="before"` so the `Field` constraints above judge the
    # ALREADY-TRIMMED value. As an `after` validator — or as the handler-side
    # `.strip()` this replaces — `min_length=1` sees the raw string, so " "
    # passes validation and is persisted verbatim. That is how `agency_name`
    # came to hold "Ashly " and every greeting read "assistant at Ashly .".
    # Same ordering lesson as `leads.CallIn._email_shape`.

    @field_validator("agency_name", "agent_persona", "greeting_template", "timezone",
                     mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        """NOT NULL columns: trim only. Empty is refused by `min_length=1`.

    Accepts `bytes` as well as `str`: Pydantic coerces bytes to str AFTER a
    `mode="before"` validator runs, so an `isinstance(value, str)` guard alone
    lets `b"  x  "` through untrimmed. Not reachable over JSON, which has no
    byte string — but a guard with a hole in it is how the next caller gets
    surprised.
        """
        return value.strip() if isinstance(value, str) else value

    @field_validator("brokerage_line", "agency_phone", "booking_contact_email",
                     mode="before")
    @classmethod
    def _trim_or_clear(cls, value: object) -> object:
        """Nullable columns: trim, and treat whitespace-only as "clear it".

        For `brokerage_line` this is not cosmetic. Both gates strip before
        deciding (`content_render.py`, `content_studio.py`), so a
        whitespace-only value renders the Settings box as FILLED while every
        gate treats it as empty — a silent false "yes, it is set" on a field
        whose whole job is a legal obligation.

        (An earlier version of this note also claimed trailing spaces would be
        burned into the video verbatim. They would not: `content_render.py:310`
        strips before writing the frame. The gate argument above is the real
        one and stands on its own.)
        """
        if not isinstance(value, str):
            return value
        return value.strip() or None


@lru_cache(maxsize=1)
def _not_nullable_fields() -> frozenset[str]:
    """Patchable fields whose column refuses NULL, read off the table itself."""
    required = {c.name for c in AgentSettings.__table__.columns if not c.nullable}
    return frozenset(required & set(SettingsPatch.model_fields))


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

    # An explicit `null` on a NOT NULL column reached the blind `setattr` below
    # and came back as a 500 from Postgres — a stack trace where the caller
    # needed a field name. `exclude_unset` cannot catch it: a null that was
    # sent IS set, it just has no legal value here. The trimming validators
    # never produce None for these fields, so this only fires on a caller who
    # asked for it.
    #
    # DERIVED from the table, not typed out. The hand-written version listed
    # four of the six NOT NULL columns this schema can write, so `languages`
    # still raised a TypeError in the loop below and `business_hours` still
    # reached Postgres — the same defect, left half-fixed inside the function
    # that fixed it. A list of column names kept in sync by hand beside another
    # list of column names kept in sync by hand is the shape that drifts, and
    # this one had drifted before it shipped.
    blanked = [
        f
        for f in _not_nullable_fields()
        if f in updates and updates[f] is None
    ]
    if blanked:
        raise HTTPException(
            status_code=422,
            detail=f"These fields cannot be cleared: {', '.join(sorted(blanked))}",
        )

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

    if "timezone" in updates:
        # No `.strip()`: the schema validator already trimmed it, and the guard
        # above refuses an explicit null before this runs. It used to earn its
        # place by turning `None` into the string "None" and 400ing on it —
        # that path is now a named 422, so this was left doing nothing.
        tz = str(updates["timezone"])
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
