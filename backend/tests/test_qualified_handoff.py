"""The handoff notice, and the number it refuses to print.

Lead 1269, the first real run of the email channel on 2026-09-19: someone wrote
*"renting at $2,400 in Wash Park and I have around $35,000 saved"* and the
classifier filed `budget_min = budget_max = 35000`. That is the **down payment**.
Our own calculator, given the same three inputs, puts what they can buy at
**$315,399** — an order of magnitude out, on the single line an agent acts on.

So the notice stopped printing a budget. The figure still opens the gate (naming
money means they have thought about it) but never gets a label the product
cannot stand behind; their own words go in its place, and words cannot be wrong
about themselves.

This is pinned rather than left to good intentions because a missing line looks
exactly like an oversight to the next person, who will helpfully add it back.
The real budget is `solve_price()` over rent/savings/credit, in v0.135.0.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.models import Conversation, Lead, LeadIntent
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.lead_notify import send_new_lead_notice
from app.services.tenant_context import set_org_id

ORG = 1
MARK = "%@handoff.test"
THEIR_WORDS = (
    "I'm renting at $2,400 in Wash Park and I have around $35,000 saved. "
    "What would that actually buy right now?"
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """The notice only exists when `booking_contact_email` is set.

    Restored afterwards, and that is not tidiness: on 2026-09-19 this same
    address was repointed in PRODUCTION to keep a test away from the realtor,
    and a probe address left behind is a real notice that never arrives.
    """
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
            row.booking_contact_email = "handoff-probe-agency@example.com"
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


async def _seed(email: str) -> tuple[int, int]:
    """A lead exactly as lead 1269 came out of the classifier."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            phone=email,
            email=email,
            intent=LeadIntent.BUY,
            zone="Wash Park",
            urgency="months",
            budget_min=35000,
            budget_max=35000,
            score=63,
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
        db.add(conv)
        await db.flush()
        msg = Message(
            org_id=ORG,
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content=THEIR_WORDS,
            delivery_status=MessageStatus.DELIVERED,
        )
        db.add(msg)
        await db.commit()
        return int(lead.id), int(msg.id)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE email LIKE :p"), {"p": MARK})
        await db.commit()


@pytest.mark.asyncio
async def test_the_handoff_never_prints_a_budget_it_cannot_stand_behind(
    database_url: str,
) -> None:
    set_org_id(ORG)
    lead_id, msg_id = await _seed("handoff@handoff.test")
    try:
        sender = AsyncMock(return_value={"id": "resend.h1", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(lead_id, msg_id, origin="qualified")

        assert sender.await_count >= 1
        body = sender.await_args_list[0].kwargs["body_text"]

        # No line of OURS carries a money figure. The number still appears —
        # inside the quote, because they wrote it — and that is the distinction
        # the whole fix rests on: repeating what someone said cannot be wrong,
        # labelling it "Budget" can.
        #
        # This assertion started out as `"35,000" not in body` and failed for
        # the right reason. Kept in this shape rather than deleted: a test that
        # forbids the figure outright would also forbid quoting them.
        ours = [
            ln for ln in body.splitlines()
            if ln.strip() and not ln.startswith("They wrote:")
        ]
        assert not any("Budget" in ln for ln in ours)
        assert not any("35,000" in ln or "35000" in ln for ln in ours)

        # And what replaced it.
        assert THEIR_WORDS.split(".")[0] in body
        # The facts we DO stand behind are still there.
        assert "Wants: buy" in body
        assert "Area: Wash Park" in body
        assert "Timeline: months" in body
        assert "63/100" in body
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_handoff_does_not_claim_to_know_what_they_can_spend(
    database_url: str,
) -> None:
    """The opening line used to say "what they want, what they can spend, and
    where". Two of those three were true."""
    set_org_id(ORG)
    lead_id, msg_id = await _seed("claim@handoff.test")
    try:
        sender = AsyncMock(return_value={"id": "resend.h2", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(lead_id, msg_id, origin="qualified")

        body = sender.await_args_list[0].kwargs["body_text"]
        assert "what they can spend" not in body
    finally:
        await _cleanup()
