"""A provider replaying a message id must not cost the turn.

`messages` carries UNIQUE (org_id, external_id), and stamping the id a provider
hands back can collide: a provider replaying one, or two replies landing on the
same id. The reply really was sent by then, and the same transaction holds the
lead, the conversation and the inbound message — none of which may be thrown
away because a bookkeeping column would not fit. `conversation.py` opens a
savepoint for exactly that reason.

The recovery did not work. A savepoint rollback EXPIRES every object it
touched, so the handler's own `log.warning` — which reads `outbound.id` — became
a synchronous lazy load inside async code and raised MissingGreenlet. That is
not an IntegrityError, so it escaped to the outer `except Exception`, whose
first act is to read `outbound.id` again. The turn died, and the lead got
nothing.

The lesson was already written down in this repo, in `followups.py:423-427`:
"even `fu.id` becomes a synchronous lazy load and raises MissingGreenlet outside
every handler here, which is the batch dying again by another route."
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.message import Message, MessageDirection, MessageStatus
from app.services.tenant_context import org_scope

AGENCY = 941


async def _make_agency() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, 'Dup Agency', 'dup-agency', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": AGENCY},
        )
        await db.commit()


async def _clear() -> None:
    async with get_bypass_session_factory()() as db:
        for table in (
            "follow_ups", "messages", "conversations", "visits",
            "leads", "agent_settings", "channel_routes",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE org_id = :o"), {"o": AGENCY}
            )
        await db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": AGENCY})
        await db.commit()
    from app.services import tenant_resolver

    tenant_resolver.reset_cache()


async def _turn(phone: str, external_id: str, body: str) -> None:
    """One inbound turn whose outbound send returns `external_id`."""
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    async def _reply(**kwargs: object) -> LLMResult:
        return LLMResult(
            text="Of course, happy to help.", provider="kimi", model="k2",
            input_tokens=1, output_tokens=1,
        )

    async def _sent(*a: object, **k: object) -> tuple[str, None]:
        return external_id, None

    arriving = ParsedMessage(
        channel="sms",
        external_id=f"in-{phone}",
        from_identifier=phone,
        from_name="A Lead",
        content=body,
    )
    with org_scope(AGENCY):
        async with get_session_factory()() as db:
            with patch("app.services.conversation.generate_reply", _reply), patch(
                "app.services.conversation._dispatch_send", _sent
            ):
                await handle_inbound_message(arriving, db)


@pytest.mark.asyncio
async def test_a_replayed_provider_id_does_not_cost_the_turn() -> None:
    """The whole point of the savepoint, asserted end to end.

    Before the fix this raised MissingGreenlet out of `handle_inbound_message`,
    so the second lead's turn was lost entirely — no outbound row, no rescore,
    no commit. The reply had already gone out over the wire.
    """
    await _clear()
    await _make_agency()
    try:
        await _turn("+13035552001", "provider-replayed-id", "First lead here.")

        # A different lead, same id back from the provider. This must not raise.
        await _turn("+13035552002", "provider-replayed-id", "Second lead here.")

        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(Message)
                    .where(
                        Message.org_id == AGENCY,
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                    .order_by(Message.id)
                )
            ).scalars().all()

        assert len(rows) == 2, (
            f"the second turn was lost: {len(rows)} outbound rows, expected 2"
        )
        # The first keeps the id; the second gives it up rather than the turn.
        assert rows[0].external_id == "provider-replayed-id"
        assert rows[1].external_id is None, (
            "the colliding id was stamped anyway, which the UNIQUE forbids"
        )
        # Both were really sent — the send happened before the bookkeeping.
        assert all(r.delivery_status is MessageStatus.SENT for r in rows), (
            [r.delivery_status for r in rows]
        )

        # And the rest of the turn survived: the second lead exists with its
        # inbound message, which is what the savepoint was protecting.
        async with get_bypass_session_factory()() as db:
            leads = (
                await db.execute(
                    text("SELECT count(*) FROM leads WHERE org_id = :o"), {"o": AGENCY}
                )
            ).scalar()
            inbound = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM messages WHERE org_id = :o "
                        "AND direction = 'inbound'"
                    ),
                    {"o": AGENCY},
                )
            ).scalar()
        assert leads == 2, f"expected both leads, found {leads}"
        assert inbound == 2, f"expected both inbound messages, found {inbound}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_the_ordinary_path_still_stamps_the_id() -> None:
    """The control. Without it the fix could be "never stamp anything" and pass."""
    await _clear()
    await _make_agency()
    try:
        await _turn("+13035552003", "unique-id-a", "Hello.")
        await _turn("+13035552004", "unique-id-b", "Hello again.")

        async with get_bypass_session_factory()() as db:
            ids = (
                await db.execute(
                    select(Message.external_id)
                    .where(
                        Message.org_id == AGENCY,
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                    .order_by(Message.id)
                )
            ).scalars().all()
        assert ids == ["unique-id-a", "unique-id-b"], ids
    finally:
        await _clear()
