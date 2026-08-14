"""`call_logs` is a tenant-owned table, so it needs the same default-deny
isolation every other one has. A new table without a policy is readable by
every agency on the install, and nothing about that failure is visible from
the outside — the queries just quietly return more than they should.

Mirrors tests/test_tenant_isolation.py deliberately: same shape, same guard
against the app role being a superuser (which would turn all of this green
while isolating nothing).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import CallLog, CallOutcome, Lead
from app.models.lead import LeadStatus
from app.services.tenant_context import org_scope

ORG_A = 1
ORG_B = 2

MARKER_A = "call-log-isolation-org-a"
MARKER_B = "call-log-isolation-org-b"


async def _seed(note: str, org_id: int, phone: str) -> int:
    """Insert a lead and a call log directly, bypassing RLS, so both orgs have
    something the other could leak."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(phone=phone, status=LeadStatus.NEW, org_id=org_id)
        db.add(lead)
        await db.flush()
        log = CallLog(
            org_id=org_id,
            lead_id=lead.id,
            outcome=CallOutcome.NO_ANSWER,
            note=note,
        )
        db.add(log)
        await db.commit()
        return log.id


async def _cleanup(*phones: str) -> None:
    async with get_bypass_session_factory()() as db:
        for phone in phones:
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
        await db.commit()


@pytest.mark.asyncio
async def test_unfiltered_select_never_returns_another_orgs_call() -> None:
    await _seed(MARKER_A, ORG_A, "+19991110001")
    await _seed(MARKER_B, ORG_B, "+19991110002")
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                # No WHERE clause on purpose: the forgotten-filter case.
                rows = (await db.execute(select(CallLog))).unique().scalars().all()
        notes = {r.note for r in rows}
        assert {r.org_id for r in rows} <= {ORG_A}, "call logs from another org leaked"
        assert MARKER_A in notes, "own call log disappeared"
        assert MARKER_B not in notes, "another agency's call log was visible"
    finally:
        await _cleanup("+19991110001", "+19991110002")


@pytest.mark.asyncio
async def test_no_org_set_sees_no_calls_rather_than_all_of_them() -> None:
    await _seed(MARKER_A, ORG_A, "+19991110003")
    try:
        with org_scope(None):
            async with get_session_factory()() as db:
                rows = (await db.execute(select(CallLog))).unique().scalars().all()
        assert rows == [], f"unset org returned {len(rows)} call logs instead of none"
    finally:
        await _cleanup("+19991110003")


@pytest.mark.asyncio
async def test_cannot_write_a_call_into_another_org() -> None:
    """USING alone filters reads but still permits writes; this covers WITH CHECK."""
    from sqlalchemy.exc import DBAPIError

    lead_id = None
    async with get_bypass_session_factory()() as db:
        lead = Lead(phone="+19991110004", status=LeadStatus.NEW, org_id=ORG_B)
        db.add(lead)
        await db.commit()
        lead_id = lead.id

    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                db.add(
                    CallLog(
                        org_id=ORG_B,
                        lead_id=lead_id,
                        outcome=CallOutcome.NO_ANSWER,
                        note="written across the boundary",
                    )
                )
                with pytest.raises(DBAPIError):
                    await db.commit()
    finally:
        await _cleanup("+19991110004")


@pytest.mark.asyncio
async def test_update_cannot_reach_another_orgs_call() -> None:
    await _seed(MARKER_B, ORG_B, "+19991110005")
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                await db.execute(
                    text("UPDATE call_logs SET note = 'hijacked' WHERE note = :n"),
                    {"n": MARKER_B},
                )
                await db.commit()
        async with get_bypass_session_factory()() as db:
            still = (
                await db.execute(
                    text("SELECT note FROM call_logs WHERE note = :n"), {"n": MARKER_B}
                )
            ).all()
        assert len(still) == 1, "another agency's call log was modified"
    finally:
        await _cleanup("+19991110005")
