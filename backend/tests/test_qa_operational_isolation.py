"""QA remains inspectable without becoming the agency's work or an alert."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_session_factory
from app.main import app
from app.models import AgentSettings, Conversation, Lead, Message
from app.models.message import MessageDirection, MessageSender
from app.services.lead_notify import _send_and_record


@pytest.fixture
async def records():
    ids = []
    async with get_session_factory()() as db:
        cfg = (await db.execute(select(AgentSettings))).scalar_one_or_none()
        created = cfg is None
        if created:
            cfg = AgentSettings(booking_contact_email="agency@example.com")
            db.add(cfg)
        previous = cfg.booking_contact_email
        cfg.booking_contact_email = "agency@example.com"
        await db.commit()

    async def make(meta):
        async with get_session_factory()() as db:
            lead = Lead(phone=f"qa-isolation-{uuid4().hex}@example.com", meta=meta,
                        name="Isolation test", score=90,
                        last_message_at=datetime.now(UTC) - timedelta(days=10))
            db.add(lead)
            await db.flush()
            ids.append(lead.id)
            conv = Conversation(lead_id=lead.id, channel="web")
            db.add(conv)
            await db.flush()
            message = Message(conversation_id=conv.id, content="Looking to buy",
                              direction=MessageDirection.INBOUND, sender=MessageSender.LEAD)
            db.add(message)
            await db.commit()
            return lead.id, message.id

    yield make
    async with get_session_factory()() as db:
        for lead in (await db.execute(select(Lead).where(Lead.id.in_(ids)))).scalars():
            await db.delete(lead)
        cfg = (await db.execute(select(AgentSettings))).scalar_one()
        if created:
            await db.delete(cfg)
        else:
            cfg.booking_contact_email = previous
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("attribution", [
    {"traffic_class": "test"},
    {"traffic_class": "automated"},
    {"utm_source": "eko_qa", "utm_medium": "test"},
])
async def test_noncommercial_lead_stays_inspectable_but_not_in_work_queues(records, attribution):
    qa, _ = await records({"attribution": attribution})
    real, _ = await records({"attribution": {"utm_source": "instagram"}})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for endpoint, key in [("/api/v1/leads?limit=200", "items"),
                              ("/api/v1/inbox?filter=all", "items"),
                              ("/api/v1/console/today", "untouched_hot")]:
            response = await client.get(endpoint)
            assert response.status_code == 200, response.text
            rows = response.json()[key]
            found = {row.get("lead_id", row.get("id")) for row in rows}
            assert real in found, endpoint
            assert qa not in found, endpoint
        digest = (await client.get("/api/v1/leads/digest")).json()
        assert real in {row["id"] for row in digest}
        assert qa not in {row["id"] for row in digest}
        detail = await client.get(f"/api/v1/leads/{qa}")
        assert detail.status_code == 200
        assert detail.json()["id"] == qa


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["form", "call", "message", "qualified", "options", "callback", "handover", "waiting"])
@pytest.mark.parametrize("attribution", [
    {"traffic_class": "test"},
    {"traffic_class": "automated"},
    {"utm_source": "eko_qa", "utm_medium": "test"},
])
async def test_qa_never_notifies_agency_owner_or_telegram(records, origin, attribution):
    lead, message = await records({"attribution": attribution})
    email = AsyncMock(return_value={"id": "mail-test"})
    telegram = AsyncMock(return_value={"ok": True})
    with patch("app.services.lead_notify.send_email", email), \
         patch("app.services.lead_notify.send_operator_telegram", telegram), \
         patch.object(get_settings(), "OWNER_NOTICE_EMAIL", "owner@example.com"):
        await _send_and_record(lead, message, origin=origin)
    assert email.await_count == 0
    assert telegram.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {}, {"attribution": "legacy"},
    {"attribution": {"utm_source": "eko_qa", "utm_medium": "social"}},
    {"attribution": {"utm_source": "youtube", "utm_medium": "test"}},
    {"traffic_class": "test", "attribution": {"utm_source": "instagram"}},
    {"attribution": {"utm_source": "instagram"},
     "attribution_later": [{"traffic_class": "test", "utm_source": "eko_qa", "utm_medium": "test"}]},
])
async def test_normal_and_legacy_leads_still_notify(records, meta):
    lead, message = await records(meta)
    email = AsyncMock(return_value={"id": "mail-test"})
    telegram = AsyncMock(return_value={"ok": True})
    with patch("app.services.lead_notify.send_email", email), \
         patch("app.services.lead_notify.send_operator_telegram", telegram):
        await _send_and_record(lead, message)
    assert email.await_count == 1
    assert email.await_args.kwargs["to"] == "agency@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/leads?limit=200")
    assert response.status_code == 200
    assert lead in {row["id"] for row in response.json()["items"]}
