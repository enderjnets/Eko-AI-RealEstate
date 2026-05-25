"""Smoke test for Phase 1 DB schema.

Runs against the live Postgres of the dev compose stack (DATABASE_URL from env).
Creates a Lead with a uniquely-suffixed phone number to avoid colliding with real
data, attaches a Conversation + 2 Messages, asserts the relationships, and cleans
up by deleting the Lead (cascade removes the rest).

Why not transactional rollback fixture: the simple create+verify+delete pattern is
easier to read for a smoke test, and FKs with ON DELETE CASCADE make cleanup safe.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    AgentSettings,
    Conversation,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — smoke test requires live Postgres")
    return url


@pytest.mark.asyncio
async def test_lead_conversation_message_roundtrip(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    # Unique suffix protects from collisions when test runs repeatedly.
    suffix = uuid.uuid4().hex[:8].upper()
    test_phone = f"+34666TEST{suffix}"

    try:
        # ── create ──────────────────────────────────────────────────
        async with Session() as s:
            lead = Lead(phone=test_phone, name="Smoke Test")
            s.add(lead)
            await s.flush()

            conv = Conversation(lead_id=lead.id, channel="whatsapp")
            s.add(conv)
            await s.flush()

            s.add_all(
                [
                    Message(
                        conversation_id=conv.id,
                        direction=MessageDirection.INBOUND,
                        sender=MessageSender.LEAD,
                        content="Hola, busco piso en alquiler en Madrid centro.",
                        wa_message_id=f"wamid.test_in_{suffix}",
                        wa_status=MessageStatus.DELIVERED,
                    ),
                    Message(
                        conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND,
                        sender=MessageSender.AGENT,
                        content="¡Hola! ¿Qué presupuesto manejas?",
                        wa_message_id=f"wamid.test_out_{suffix}",
                        wa_status=MessageStatus.SENT,
                        llm_provider="kimi",
                        llm_model="kimi-for-coding",
                    ),
                ]
            )
            await s.commit()
            lead_id = lead.id

        # ── read back ───────────────────────────────────────────────
        async with Session() as s:
            loaded = (
                await s.execute(select(Lead).where(Lead.phone == test_phone))
            ).scalar_one()
            assert loaded.id == lead_id
            assert loaded.name == "Smoke Test"
            assert len(loaded.conversations) == 1

            conv_loaded = loaded.conversations[0]
            assert conv_loaded.channel == "whatsapp"
            assert len(conv_loaded.messages) == 2

            inbound = next(m for m in conv_loaded.messages if m.direction == MessageDirection.INBOUND)
            outbound = next(m for m in conv_loaded.messages if m.direction == MessageDirection.OUTBOUND)
            assert inbound.sender == MessageSender.LEAD
            assert inbound.content.startswith("Hola")
            assert outbound.sender == MessageSender.AGENT
            assert outbound.llm_provider == "kimi"
            assert outbound.wa_status == MessageStatus.SENT
    finally:
        # ── cleanup (cascade drops conv + messages) ─────────────────
        async with Session() as s:
            result = await s.execute(select(Lead).where(Lead.phone == test_phone))
            stale = result.scalar_one_or_none()
            if stale is not None:
                await s.delete(stale)
                await s.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_settings_singleton(database_url: str) -> None:
    """Verify defaults bake into AgentSettings on first insert."""
    engine = create_async_engine(database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with Session() as s:
            existing = (await s.execute(select(AgentSettings).where(AgentSettings.id == 1))).scalar_one_or_none()
            created = existing is None
            if created:
                s.add(AgentSettings(id=1, agency_name="Test Agency"))
                await s.commit()

        async with Session() as s:
            settings_row = (await s.execute(select(AgentSettings).where(AgentSettings.id == 1))).scalar_one()
            assert settings_row.agency_name in ("Test Agency", "Inmobiliaria")
            assert "es" in settings_row.languages
            assert settings_row.agent_persona  # non-empty default applied
            assert settings_row.business_hours.get("monday", {}).get("open") == "09:00"

        if created:
            async with Session() as s:
                row = (await s.execute(select(AgentSettings).where(AgentSettings.id == 1))).scalar_one()
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()
