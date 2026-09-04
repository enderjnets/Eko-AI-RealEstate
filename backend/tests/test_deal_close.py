"""Closing a deal, and whether the appointment happened.

Two gaps this file closes, and both were measured in production before the
phase was written: **zero** leads had ever reached `won` or `lost`, and **no
code path anywhere wrote `completed` or `no_show`** — every visit ever booked
sat at `scheduled` for ever. So "we set 40 appointments" had no honest second
half, and "we won 3" could not say what kind of business those three were.

The rule the tests exist to hold: `won` without a kind is refused. It is the
only field in this product that is refused rather than defaulted, because a
column of nulls here cannot be filled in afterwards — nobody remembers, three
months later, whether a particular close was a listing or a rental.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import Lead, LeadEvent, LeadIntent, LeadStatus, Visit, VisitStatus

ORG_A = 1
MARKER = "+1998000"


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "DELETE FROM leads WHERE phone LIKE :m"
            ),
            {"m": f"{MARKER}%"},
        )
        await db.commit()


async def _lead(suffix: str, **over: object) -> int:
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG_A,
            phone=f"{MARKER}{suffix}",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            **over,
        )
        db.add(lead)
        await db.commit()
        return lead.id


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _events(lead_id: int) -> list[LeadEvent]:
    async with get_bypass_session_factory()() as db:
        rows = await db.execute(
            select(LeadEvent).where(LeadEvent.lead_id == lead_id).order_by(LeadEvent.id)
        )
        return list(rows.scalars())


# ── Closing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_won_without_a_kind_is_refused() -> None:
    lead_id = await _lead("001")
    try:
        async with await _client() as client:
            resp = await client.patch(f"/api/v1/leads/{lead_id}", json={"status": "won"})
        assert resp.status_code == 422
        assert "won_kind_required" in resp.text

        async with get_bypass_session_factory()() as db:
            row = await db.get(Lead, lead_id)
            assert row.status == LeadStatus.NEW, "and nothing was written"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_closing_records_the_kind_the_date_and_the_history() -> None:
    lead_id = await _lead("002")
    try:
        async with await _client() as client:
            resp = await client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"status": "won", "won_kind": "listing_sold", "won_value": 12500},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["won_kind"] == "listing_sold"
        # Filled in rather than demanded: the date a deal closed is the day it
        # was marked, and asking for it again is a field nobody fills honestly.
        assert body["won_at"] is not None

        types = [e.type for e in await _events(lead_id)]
        assert "deal_closed" in types
        assert "status_changed" in types
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_that_already_carries_a_kind_can_be_reclosed() -> None:
    """The check reads the lead, not just the patch. Re-saving a closed lead
    to correct a typo elsewhere must not demand the kind again."""
    lead_id = await _lead("003", won_kind="rental")
    try:
        async with await _client() as client:
            resp = await client.patch(f"/api/v1/leads/{lead_id}", json={"status": "won"})
        assert resp.status_code == 200, resp.text
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_invented_kind_is_refused_by_the_schema() -> None:
    lead_id = await _lead("004")
    try:
        async with await _client() as client:
            resp = await client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"status": "won", "won_kind": "crypto_flip"},
            )
        assert resp.status_code == 422
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_reason_a_lead_was_lost_lands_on_the_status_change() -> None:
    """Beside it rather than inside it would mean joining two rows by timestamp
    to answer "why do we lose them", which is the report this enables."""
    lead_id = await _lead("005")
    try:
        async with await _client() as client:
            resp = await client.patch(
                f"/api/v1/leads/{lead_id}",
                json={"status": "lost", "lost_reason": "bought with another agent"},
            )
        assert resp.status_code == 200, resp.text

        changed = [e for e in await _events(lead_id) if e.type == "status_changed"]
        assert changed and changed[-1].meta == {"reason": "bought with another agent"}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_amount_is_admin_only_and_the_rest_of_the_close_is_not() -> None:
    """A commission is the one number on a lead not everyone is entitled to.
    Hiding the whole close instead would mean an advisor cannot see that the
    lead they are about to call is already won.

    `dependency_overrides` and not `monkeypatch`: the role arrives through
    `Depends(current_role)`, which FastAPI resolved by reference when the route
    was defined — patching the module attribute afterwards changes nothing, and
    the test passes while proving nothing, which is how it failed first.
    """
    from app.api.v1.auth import current_role

    lead_id = await _lead("006", won_kind="buyer_purchase", won_value=9000)
    try:
        for role, visible in (("member", False), ("admin", True)):
            app.dependency_overrides[current_role] = lambda role=role: role
            async with await _client() as client:
                body = (await client.get(f"/api/v1/leads/{lead_id}")).json()
            assert (body["won_value"] is not None) is visible, role
            assert body["won_kind"] == "buyer_purchase", "never hidden"
    finally:
        app.dependency_overrides.clear()
        await _cleanup()


# ── Did the appointment happen ───────────────────────────────────────────


async def _visit(lead_id: int, status: VisitStatus = VisitStatus.SCHEDULED) -> int:
    from datetime import UTC, datetime, timedelta

    async with get_bypass_session_factory()() as db:
        visit = Visit(
            org_id=ORG_A,
            lead_id=lead_id,
            calendar_provider="manual",
            external_booking_id=f"test-{lead_id}-{status.value}",
            status=status,
            scheduled_at=datetime.now(UTC) - timedelta(hours=2),
            duration_minutes=45,
            timezone="America/Denver",
        )
        db.add(visit)
        await db.commit()
        return visit.id


@pytest.mark.asyncio
async def test_marking_an_appointment_held_writes_a_status_nothing_wrote_before() -> None:
    lead_id = await _lead("007")
    try:
        visit_id = await _visit(lead_id)
        async with await _client() as client:
            resp = await client.post(
                f"/api/v1/visits/{visit_id}/outcome", json={"outcome": "completed"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "completed"

        outcomes = [e for e in await _events(lead_id) if e.type == "appointment_outcome"]
        assert outcomes and outcomes[-1].meta["outcome"] == "completed"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_nobody_turned_up_is_recorded_as_such() -> None:
    lead_id = await _lead("008")
    try:
        visit_id = await _visit(lead_id)
        async with await _client() as client:
            resp = await client.post(
                f"/api/v1/visits/{visit_id}/outcome", json={"outcome": "no_show"}
            )
        assert resp.status_code == 200 and resp.json()["status"] == "no_show"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_outcome_only_means_something_on_a_visit_still_standing() -> None:
    """Re-marking a cancelled visit as held is not a correction, it is a second
    story about the same afternoon."""
    lead_id = await _lead("009")
    try:
        for status in (VisitStatus.CANCELLED, VisitStatus.COMPLETED):
            visit_id = await _visit(lead_id, status)
            async with await _client() as client:
                resp = await client.post(
                    f"/api/v1/visits/{visit_id}/outcome", json={"outcome": "completed"}
                )
            assert resp.status_code == 409, f"{status} should be closed to outcomes"
            assert "visit_not_open" in resp.text
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_outcome_that_is_not_one_of_the_two_is_refused() -> None:
    lead_id = await _lead("010")
    try:
        visit_id = await _visit(lead_id)
        async with await _client() as client:
            resp = await client.post(
                f"/api/v1/visits/{visit_id}/outcome", json={"outcome": "maybe"}
            )
        assert resp.status_code == 422
    finally:
        await _cleanup()
