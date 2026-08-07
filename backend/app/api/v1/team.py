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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_bypass_db, get_db
from app.models import Account, AllowedUser, UserActivity
from app.models.organization import DEMO_ORG_ID
from app.services.auth import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER

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
    try:
        await db.commit()
    except IntegrityError as exc:
        # The duplicate check above runs on the RLS-scoped session, so it cannot
        # see a row this email already has in another organization — but email
        # is globally unique, because login has to resolve one person before it
        # knows their org. Without this the admin got an opaque 500.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This email already belongs to another organization on this platform.",
        ) from exc
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


# ─── Self-registered demo (view-only "viewer") accounts ────────────────────
# Read-only accounts created from the public /register form. Admins view the
# captured profile here (sales follow-up) and can delete test/abandoned signups.
#
# These three run on the bypass session, scoped explicitly to the demo org.
# /register always writes into DEMO_ORG_ID while every admin session resolves
# to DEFAULT_ORG_ID, so on an RLS-scoped session the list was permanently
# empty — including the only way to revoke a demo account. The explicit
# where() is what keeps 'bypass' from meaning 'every organization'.


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None
    company: str | None
    address: str | None
    state: str | None
    country: str | None
    role: str
    created_at: datetime


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(db: AsyncSession = Depends(get_bypass_db)) -> list[AccountOut]:
    """All self-registered demo (viewer) accounts, newest first."""
    rows = (
        await db.execute(
            select(Account)
            .where(Account.org_id == DEMO_ORG_ID)
            .order_by(Account.created_at.desc())
        )
    ).scalars().all()
    return [AccountOut.model_validate(r) for r in rows]


class AccountRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A self-registered account can be upgraded from read-only "viewer" to a full
    # "member" (read + write). Admin access stays managed via the allow-list.
    role: Literal["viewer", "member"]


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account_role(
    account_id: int, body: AccountRoleIn, db: AsyncSession = Depends(get_bypass_db)
) -> AccountOut:
    """Change a demo account's access level (viewer ↔ member)."""
    row = (
        await db.execute(
            select(Account).where(
                Account.id == account_id, Account.org_id == DEMO_ORG_ID
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    row.role = ROLE_VIEWER if body.role == "viewer" else ROLE_MEMBER
    await db.commit()
    await db.refresh(row)
    return AccountOut.model_validate(row)


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: int, db: AsyncSession = Depends(get_bypass_db)) -> dict[str, bool]:
    """Delete a self-registered demo account (e.g. a test or abandoned signup)."""
    row = (
        await db.execute(
            select(Account).where(
                Account.id == account_id, Account.org_id == DEMO_ORG_ID
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ─── Per-user engagement stats (admin) ──────────────────────────────────────


class ActivityOut(BaseModel):
    email: str
    source: str | None
    first_seen: datetime
    last_seen: datetime
    login_count: int
    request_count: int
    active_days: int
    top_sections: list[dict]  # [{"section": "leads", "count": 42}, ...] desc
    device: str | None
    last_ip: str | None


@router.get("/activity", response_model=list[ActivityOut])
async def list_activity(db: AsyncSession = Depends(get_db)) -> list[ActivityOut]:
    """Engagement stats for every tracked user (by email), most-recently-active first."""
    rows = (
        await db.execute(select(UserActivity).order_by(UserActivity.last_seen.desc()))
    ).scalars().all()
    out: list[ActivityOut] = []
    for r in rows:
        sections = sorted(
            ({"section": k, "count": v} for k, v in (r.sections or {}).items()),
            key=lambda x: x["count"],
            reverse=True,
        )
        out.append(
            ActivityOut(
                email=r.email,
                source=r.source,
                first_seen=r.first_seen,
                last_seen=r.last_seen,
                login_count=r.login_count,
                request_count=r.request_count,
                active_days=r.active_days,
                top_sections=sections,
                device=r.device,
                last_ip=r.last_ip,
            )
        )
    return out


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
