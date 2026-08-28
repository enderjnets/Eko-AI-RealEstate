"""Cancelling a visit has to reach the people, not just the row.

The machinery to say "this appointment is off" was written and unreachable.
`send_visit_invitation` accepted `cancelled`, `icalendar.build_visit_ics` emitted
METHOD:CANCEL with a comment explaining that a matching UID is how a client
REMOVES an event it already accepted — and the only two callers in the codebase
were bookings. `cancel_visit` marked the row and sent nothing, so the appointment
stayed in the lead's calendar and in the agent's, and both would have shown up.

What these tests pin, in order of how expensive the mistake is:

  * The words and the attachment must agree. `cancelled` used to reach the .ics
    and the MIME `method=` and leave the copy alone, so the mail said "Your
    visit is confirmed" while carrying a file that cancels it.
  * Same UID, HIGHER SEQUENCE. RFC 5546 lets a client ignore a CANCEL whose
    sequence does not exceed what it already accepted, and Outlook does. A
    correct-looking cancellation that silently leaves the event in place is the
    worst of both worlds.
  * A send that fails must not un-cancel the visit.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.main import app
from app.models.agent_settings import AgentSettings
from app.models.lead import Lead, LeadStatus
from app.models.message import Message
from app.models.visit import Visit, VisitStatus
from app.services.delivery import MAX_ATTEMPTS
from app.services.tenant_context import org_scope
from app.services.visit_invite import send_visit_invitation

ORG = 1
PHONE = "+19995550777"
LEAD_EMAIL = "cancel-probe@example.com"
AGENCY_EMAIL = "cancel-probe-agency@example.com"
BOOKING_REF = "cancel-probe-visit"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """The agency copy only exists when `booking_contact_email` is set, and the
    value is restored: a probe address left behind silently redirects every
    other test's agency notification."""
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
        ).scalar_one_or_none()
        created = row is None
        if created:
            row = AgentSettings(org_id=ORG)
            db.add(row)
        previous = row.booking_contact_email
        row.booking_contact_email = AGENCY_EMAIL
        await db.commit()
    try:
        yield
    finally:
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            if row is not None:
                if created:
                    await db.delete(row)
                else:
                    row.booking_contact_email = previous
                await db.commit()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM visits WHERE external_booking_id = :r"), {"r": BOOKING_REF}
        )
        await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": PHONE})
        await db.commit()


async def _seed(*, email: str | None = LEAD_EMAIL, opted_out: bool = False) -> tuple[int, int]:
    await _cleanup()
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            name="Cancel Probe",
            phone=PHONE,
            email=email,
            status=LeadStatus.NEW,
            opted_out_at=datetime.now(UTC) if opted_out else None,
        )
        db.add(lead)
        await db.flush()
        visit = Visit(
            org_id=ORG,
            lead_id=lead.id,
            calendar_provider="calcom",
            external_booking_id=BOOKING_REF,
            status=VisitStatus.SCHEDULED,
            scheduled_at=datetime.now(UTC) + timedelta(days=4),
            duration_minutes=45,
            timezone="America/Denver",
            property_address="900 Broadway, Denver, CO",
        )
        db.add(visit)
        await db.commit()
        return lead.id, visit.id


def _sender(*ids: str) -> AsyncMock:
    """One Resend id per message, never repeated — a shared id trips
    `uq_messages_external_id` and the failure looks like the code's."""
    return AsyncMock(side_effect=[{"id": i} for i in ids])


async def _notify(lead_id: int, visit_id: int, sender: AsyncMock, *, cancelled: bool) -> None:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
            with patch("app.services.visit_invite.send_email", sender):
                await send_visit_invitation(db, visit, lead, language="en", cancelled=cancelled)


def _ics_of(call) -> str:
    """The .ics text of one recorded send_email call."""
    attachments = call.kwargs["attachments"]
    return attachments[0].content.decode("utf-8")


async def _rows(visit_id: int) -> list[Message]:
    async with get_bypass_session_factory()() as db:
        return list(
            (
                await db.execute(
                    select(Message).where(Message.content.like(f"%{visit_id}%"))
                )
            ).scalars()
        )


# ── El aviso sale ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelling_writes_both_copies(database_url: str) -> None:
    """Same shape as a booking: one row for the lead, one internal for the
    agency. The record of "we told them it was off" matters as much as the
    record of "we told them it was on"."""
    lead_id, visit_id = await _seed()
    try:
        sender = _sender("re_cx_lead", "re_cx_agency")
        await _notify(lead_id, visit_id, sender, cancelled=True)
        assert sender.await_count == 2

        async with get_bypass_session_factory()() as db:
            conv_ids = [
                c for (c,) in await db.execute(
                    text(
                        "SELECT id FROM conversations WHERE lead_id = :l"
                    ),
                    {"l": lead_id},
                )
            ]
            rows = list(
                (
                    await db.execute(
                        select(Message).where(Message.conversation_id.in_(conv_ids))
                    )
                ).scalars()
            )
        assert len(rows) == 2, f"expected the lead copy and the internal note, got {len(rows)}"
        assert sorted(r.internal for r in rows) == [False, True]
        assert all(r.external_id for r in rows)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_words_say_cancelled_not_confirmed(database_url: str) -> None:
    """The defect this file was written for.

    `cancelled` reached the .ics and the MIME method and left the copy alone, so
    the recipient read "Your visit is confirmed" over an attachment that removes
    it. Subject and body are asserted for BOTH recipients."""
    lead_id, visit_id = await _seed()
    try:
        sender = _sender("re_w1", "re_w2")
        await _notify(lead_id, visit_id, sender, cancelled=True)
        for call in sender.await_args_list:
            subject = call.kwargs["subject"]
            body = call.kwargs["body_text"]
            assert "cancel" in subject.lower(), subject
            assert "cancel" in body.lower(), body
            assert "confirmed" not in body.lower(), body
            assert "is booked" not in subject.lower(), subject
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_ics_can_actually_remove_the_event(database_url: str) -> None:
    """Same UID and a HIGHER sequence, or the client keeps the appointment.

    The UID identifies which event to remove; RFC 5546 lets a client ignore a
    CANCEL whose SEQUENCE does not exceed the one it accepted, and Outlook does
    exactly that. Both halves are asserted against the booking's own .ics, not
    against a hard-coded string, so a change to the UID scheme fails here."""
    lead_id, visit_id = await _seed()
    try:
        # The SAME visit, booked then cancelled. Re-seeding between the two
        # would compare the UIDs of two different rows, which differ by
        # construction and would prove nothing.
        booking = _sender("re_b1", "re_b2")
        await _notify(lead_id, visit_id, booking, cancelled=False)
        invite_ics = _ics_of(booking.await_args_list[0])

        cancel = _sender("re_c1", "re_c2")
        await _notify(lead_id, visit_id, cancel, cancelled=True)
        cancel_ics = _ics_of(cancel.await_args_list[0])

        def field(text_: str, name: str) -> str:
            for line in text_.splitlines():
                if line.startswith(f"{name}:"):
                    return line.split(":", 1)[1]
            raise AssertionError(f"{name} missing from the .ics")

        assert field(cancel_ics, "UID") == field(invite_ics, "UID")
        assert "METHOD:CANCEL" in cancel_ics
        assert field(cancel_ics, "STATUS") == "CANCELLED"
        assert int(field(cancel_ics, "SEQUENCE")) > int(field(invite_ics, "SEQUENCE"))
        assert "method=CANCEL" in cancel.await_args_list[0].kwargs["attachments"][0].content_type
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_failed_send_is_not_retried_blind(database_url: str) -> None:
    """A cancellation that could not be delivered is recorded as failed and
    parked, exactly like the invitation: the retry sweep would resend the body
    WITHOUT the .ics, which is a cancellation that cancels nothing."""
    # WITH an email: `_record_in_thread` only opens an email thread for a lead
    # that has an address, so a phone-only lead with no prior conversation has
    # nowhere to record and writes nothing — correct, and not what this test is
    # about.
    lead_id, visit_id = await _seed()
    try:
        boom = AsyncMock(side_effect=RuntimeError("resend is down"))
        await _notify(lead_id, visit_id, boom, cancelled=True)
        async with get_bypass_session_factory()() as db:
            conv_ids = [
                c for (c,) in await db.execute(
                    text("SELECT id FROM conversations WHERE lead_id = :l"), {"l": lead_id}
                )
            ]
            rows = list(
                (
                    await db.execute(
                        select(Message).where(Message.conversation_id.in_(conv_ids))
                    )
                ).scalars()
            )
        assert len(rows) == 2, "both copies failed, so both must be on record"
        for row in rows:
            assert row.external_id is None
            assert row.send_attempts == MAX_ATTEMPTS, (
                "a row the sweep can still pick up would be re-sent WITHOUT the "
                "attachment — a cancellation that cancels nothing"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opted_out_lead_is_not_written_to(database_url: str) -> None:
    """STOP is absolute and a cancellation is no exception — but the agency
    still gets its copy, so the agent knows the slot is free."""
    lead_id, visit_id = await _seed(opted_out=True)
    try:
        sender = _sender("re_optout_agency")
        await _notify(lead_id, visit_id, sender, cancelled=True)
        assert sender.await_count == 1
        assert sender.await_args_list[0].kwargs["to"] == AGENCY_EMAIL
    finally:
        await _cleanup()


# ── El endpoint, que es donde vivía el agujero ───────────────────────────────


@pytest.mark.asyncio
async def test_the_cancel_endpoint_actually_sends(database_url: str) -> None:
    """The test the whole file exists for.

    Everything above exercises `send_visit_invitation(cancelled=True)`, and all
    of it passed BEFORE this change too — the function was always correct, it
    was simply never called. `POST /visits/{id}/cancel` is the surface a realtor
    touches, and until now it sent nothing at all. Deleting the call restored in
    `visits.py` must turn THIS red; nothing else in this file would notice.

    `calendar_provider="manual"` so the endpoint skips the Cal.com round-trip:
    this asserts the notice, not the provider.
    """
    lead_id, visit_id = await _seed()
    async with get_bypass_session_factory()() as db:
        visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
        visit.calendar_provider = "manual"
        await db.commit()
    try:
        sender = _sender("re_ep_lead", "re_ep_agency")
        with patch("app.services.visit_invite.send_email", sender):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.post(f"/api/v1/visits/{visit_id}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cancelled"

        assert sender.await_count == 2, (
            "the endpoint cancelled the row and told nobody — the appointment "
            "stays in the lead's calendar and in the agent's"
        )
        for call in sender.await_args_list:
            assert "cancel" in call.kwargs["subject"].lower()
            assert "METHOD:CANCEL" in _ics_of(call)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_notice_that_fails_does_not_un_cancel_the_visit(database_url: str) -> None:
    """The cancellation is the fact; announcing it is best effort.

    Rolling back a recorded cancellation because an email bounced would put an
    appointment back that the agent already treats as dead — and they will not
    be at it."""
    lead_id, visit_id = await _seed()
    async with get_bypass_session_factory()() as db:
        visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
        visit.calendar_provider = "manual"
        await db.commit()
    try:
        boom = AsyncMock(side_effect=RuntimeError("resend is down"))
        with patch("app.services.visit_invite.send_email", boom):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.post(f"/api/v1/visits/{visit_id}/cancel")
        assert r.status_code == 200, r.text
        async with get_bypass_session_factory()() as db:
            visit = (
                await db.execute(select(Visit).where(Visit.id == visit_id))
            ).scalar_one()
        assert visit.status == VisitStatus.CANCELLED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_broken_language_guess_still_sends_the_notice(database_url: str) -> None:
    """The guess is a nicety; the notice is the point.

    `_lead_language` reads settings and the lead's history, so it has more ways
    to fail than the send it decorates. Letting it throw would mean an
    appointment cancelled in the panel and nobody told — the exact failure this
    whole phase exists to remove — over the question of which language to use.
    English, and carry on.
    """
    lead_id, visit_id = await _seed()
    async with get_bypass_session_factory()() as db:
        visit = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one()
        visit.calendar_provider = "manual"
        await db.commit()
    try:
        sender = _sender("re_lang_lead", "re_lang_agency")
        boom = AsyncMock(side_effect=RuntimeError("settings unavailable"))
        with patch("app.services.visit_invite.send_email", sender), patch(
            "app.services.followups._lead_language", boom
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.post(f"/api/v1/visits/{visit_id}/cancel")
        assert r.status_code == 200, r.text
        assert sender.await_count == 2, "the notice was lost to a language lookup"
        assert "cancel" in sender.await_args_list[0].kwargs["subject"].lower()
    finally:
        await _cleanup()
