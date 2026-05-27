"""Team / access API — admin-only management of the Google Sign In access list.

Backs the Settings → Team panel: admins add Gmail addresses, set each to admin
or member, promote, or remove. The whole router is mounted under require_admin in
main.py.

Two safety guards keep an office from locking itself out:
  - env-pinned admins (GOOGLE_ADMIN_EMAILS) are immutable — can't be demoted or
    removed here;
  - the API refuses to remove or demote the *last* admin.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models import AllowedUser
from app.services.auth import ROLE_ADMIN, ROLE_MEMBER

router = APIRouter()


def _norm_email(value: str) -> str:
    email = (value or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    return email


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    role: str
    added_by: str | None
    created_at: datetime
    immutable: bool = False


class TeamAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    role: Literal["admin", "member"] = ROLE_MEMBER


class TeamRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "member"]


async def _other_admins_remain(db: AsyncSession, *, excluding: str) -> bool:
    """True if at least one admin would remain after excluding `email` — counting
    env-pinned admins (always present) plus other DB admin rows."""
    pinned = {e for e in get_settings().google_admin_emails_list if e != excluding}
    if pinned:
        return True
    rows = (await db.execute(select(AllowedUser.email).where(AllowedUser.role == ROLE_ADMIN))).all()
    return any(r[0] != excluding for r in rows)


@router.get("", response_model=list[TeamMemberOut])
async def list_team(db: AsyncSession = Depends(get_db)) -> list[TeamMemberOut]:
    pinned = set(get_settings().google_admin_emails_list)
    rows = (
        await db.execute(select(AllowedUser).order_by(AllowedUser.role, AllowedUser.email))
    ).scalars().all()
    out: list[TeamMemberOut] = []
    for r in rows:
        m = TeamMemberOut.model_validate(r)
        m.immutable = r.email in pinned
        out.append(m)
    return out


@router.post("", response_model=TeamMemberOut, status_code=201)
async def add_member(body: TeamAddIn, db: AsyncSession = Depends(get_db)) -> TeamMemberOut:
    email = _norm_email(body.email)
    existing = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already on the list")
    row = AllowedUser(email=email, role=body.role, added_by="admin")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    m = TeamMemberOut.model_validate(row)
    m.immutable = email in set(get_settings().google_admin_emails_list)
    return m


@router.patch("/{email}", response_model=TeamMemberOut)
async def update_role(
    email: str, body: TeamRoleIn, db: AsyncSession = Depends(get_db)
) -> TeamMemberOut:
    email = _norm_email(email)
    pinned = set(get_settings().google_admin_emails_list)
    if email in pinned and body.role != ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="Cannot demote a pinned admin")
    row = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not on the list")
    if row.role == ROLE_ADMIN and body.role != ROLE_ADMIN and not await _other_admins_remain(
        db, excluding=email
    ):
        raise HTTPException(status_code=400, detail="Cannot demote the last admin")
    row.role = body.role
    await db.commit()
    await db.refresh(row)
    m = TeamMemberOut.model_validate(row)
    m.immutable = email in pinned
    return m


@router.delete("/{email}")
async def remove_member(email: str, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    email = _norm_email(email)
    if email in set(get_settings().google_admin_emails_list):
        raise HTTPException(status_code=400, detail="Cannot remove a pinned admin")
    row = (
        await db.execute(select(AllowedUser).where(AllowedUser.email == email))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not on the list")
    if row.role == ROLE_ADMIN and not await _other_admins_remain(db, excluding=email):
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
