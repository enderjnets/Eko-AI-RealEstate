"""The form promises a call back — so somebody has to hear the phone ring.

The interim funnel is: visitor fills the public form → the agency's booking
mailbox gets one email with everything needed to make the call. These tests
pin the three properties that make that honest:

  * exactly ONE email per real submission — a double-submit must not nag;
  * a notice failure costs the notice, never the capture (the lead is
    committed first, and the 202 stands);
  * the trace lands in the lead's thread as `internal=True`, which is what
    keeps the delivery sweep and the LLM away from it (the v0.60 mechanism).

Everything drives the real ASGI stack, same as test_public_capture, so the
notice is proven to fire from the actual endpoint, not from a helper handed a
pre-bound tenant.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.api.v1.public import reset_rate_limits
from app.db.base import get_bypass_session_factory
from app.main import app
from app.services.delivery import MAX_ATTEMPTS

ORG = 1
AGENCY_EMAIL = "notice-probe-agency@example.com"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _clean_rate_limits() -> None:
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """The notice only exists when `booking_contact_email` is set. Restored
    afterwards — leaving a probe address behind would redirect real notices."""
    from app.models.agent_settings import AgentSettings
    from app.services.tenant_context import org_scope

    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(AgentSettings).where(AgentSettings.org_id == ORG)
                )
            ).scalar_one_or_none()
            created = row is None
            if created:
                row = AgentSettings(org_id=ORG)
                db.add(row)
            previous = row.booking_contact_email
            row.booking_contact_email = AGENCY_EMAIL
            await db.commit()
    yield
    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(AgentSettings).where(AgentSettings.org_id == ORG)
                )
            ).scalar_one_or_none()
            if row is not None:
                if created:
                    await db.delete(row)
                else:
                    row.booking_contact_email = previous
                await db.commit()


async def _post(payload: dict) -> int:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/public/leads", json=payload)
    return response.status_code


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM leads WHERE email LIKE :pat"), {"pat": "%@notice.test"}
        )
        await db.commit()


async def _thread_rows(lead_email: str) -> list[dict]:
    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT m.direction, m.internal, m.subject, m.content, "
                    "m.external_id, m.delivery_status, m.send_attempts, c.channel "
                    "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                    "JOIN leads l ON l.id = c.lead_id WHERE l.email = :e "
                    "ORDER BY m.id"
                ),
                {"e": lead_email},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


@pytest.mark.asyncio
async def test_a_form_submission_tells_the_agency() -> None:
    """One submission → one email to the booking mailbox, with the facts the
    call needs in the body, and an internal SENT row in the web thread."""
    sender = AsyncMock(return_value={"id": "re_notice_1"})
    try:
        with patch("app.services.lead_notify.send_email", sender):
            status = await _post(
                {
                    "name": "Notice Probe",
                    "email": "first@notice.test",
                    "phone": "+13035550177",
                    "message": "I'm interested in selling my home.",
                    "utm": {"utm_source": "youtube", "landing_variant": "landing"},
                }
            )
        assert status == 202
        assert sender.await_count == 1
        kwargs = sender.await_args.kwargs
        assert kwargs["to"] == AGENCY_EMAIL
        assert "Notice Probe" in kwargs["subject"]
        for fact in (
            "+13035550177",
            "first@notice.test",
            "selling my home",
            "utm_source=youtube",
        ):
            assert fact in kwargs["body_text"], f"the call needs {fact!r} in hand"

        rows = await _thread_rows("first@notice.test")
        internal = [r for r in rows if r["internal"]]
        assert len(internal) == 1, "the notice must be filed exactly once"
        note = internal[0]
        assert note["channel"] == "web"
        assert note["direction"] == "outbound"
        assert note["external_id"] == "re_notice_1"
        assert note["delivery_status"] == "sent"
        # And nothing OUTBOUND that is not internal: the notice is the agency's
        # copy, never a message to the lead.
        assert not [
            r for r in rows if r["direction"] == "outbound" and not r["internal"]
        ]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_duplicate_submission_notifies_once() -> None:
    """A double-submit is one inquiry, not two phone calls to make."""
    sender = AsyncMock(return_value={"id": "re_notice_dup"})
    payload = {
        "name": "Twice Probe",
        "email": "twice@notice.test",
        "message": "Same message, pressed twice.",
    }
    try:
        with patch("app.services.lead_notify.send_email", sender):
            assert await _post(payload) == 202
            assert await _post(payload) == 202
        assert sender.await_count == 1, "the duplicate must not email the agency again"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_notice_failure_never_costs_the_capture() -> None:
    """Resend down → the lead is still captured (202, row present), and the
    thread records the truth: FAILED, attempts spent so the sweep stays away —
    a blind retry would be dispatched to the LEAD."""
    sender = AsyncMock(side_effect=RuntimeError("resend down"))
    try:
        with patch("app.services.lead_notify.send_email", sender):
            status = await _post(
                {"name": "Broken Probe", "email": "broken@notice.test"}
            )
        assert status == 202
        rows = await _thread_rows("broken@notice.test")
        assert rows, "the capture itself must have gone through"
        internal = [r for r in rows if r["internal"]]
        assert len(internal) == 1
        assert internal[0]["delivery_status"] == "failed"
        assert internal[0]["external_id"] is None
        assert internal[0]["send_attempts"] == MAX_ATTEMPTS
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_empty_mailbox_skips_the_send_and_still_captures() -> None:
    """No `booking_contact_email` → nothing to send, nothing breaks."""
    from app.models.agent_settings import AgentSettings

    sender = AsyncMock(return_value={"id": "re_should_not_exist"})
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
        ).scalar_one()
        row.booking_contact_email = ""
        await db.commit()
    try:
        with patch("app.services.lead_notify.send_email", sender):
            status = await _post({"email": "quiet@notice.test"})
        assert status == 202
        assert sender.await_count == 0
    finally:
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(AgentSettings).where(AgentSettings.org_id == ORG)
                )
            ).scalar_one()
            row.booking_contact_email = AGENCY_EMAIL
            await db.commit()
        await _cleanup()
