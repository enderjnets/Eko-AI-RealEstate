"""Nobody gets a message after they asked us to stop. Not even by hand.

Every automated path already refused: the follow-up sweep, the delivery retry,
the dispatch gate, the booking route. The one that did not was the one where a
person types a message and clicks send — which is the path most likely to be
used on a lead who has gone quiet, and the reason they have gone quiet may be
that they opted out.

Measured before the guard was written: a lead who texted STOP got HTTP 200 and
the message was delivered. Under the TCPA that is $500, or $1,500 where it is
willful — and having recorded the opt-out and sent anyway is what the word
willful is for.
"""
import ast
import inspect
import pathlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Conversation, ConversationStatus, Lead, Message
from app.models.lead import LeadStatus
from app.services.tenant_context import org_scope


@pytest.fixture
def database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


def _session(database_url: str):
    engine = create_async_engine(database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _lead_with(database_url: str, *, opted_out: bool) -> tuple[int, int]:
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with Session() as s:
                extra = (
                    {
                        "opted_out_at": datetime.now(UTC),
                        "opted_out_keyword": "STOP",
                        "opted_out_channel": "sms",
                    }
                    if opted_out
                    else {}
                )
                lead = Lead(
                    org_id=1,
                    phone=f"+1720T{uuid.uuid4().hex[:8].upper()}",
                    status=LeadStatus.QUALIFIED,
                    **extra,
                )
                s.add(lead)
                await s.flush()
                conv = Conversation(
                    org_id=1,
                    lead_id=lead.id,
                    channel="sms",
                    status=ConversationStatus.ACTIVE,
                )
                s.add(conv)
                await s.commit()
                return lead.id, conv.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_person_cannot_message_someone_who_said_stop(database_url: str) -> None:
    lead_id, conversation_id = await _lead_with(database_url, opted_out=True)
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with await _client() as c:
                r = await c.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "Hi again"})
            assert r.status_code == 409, r.text
            assert "opted_out" in r.text

            async with Session() as s:
                written = (
                    await s.execute(
                        select(func.count())
                        .select_from(Message)
                        .where(Message.conversation_id == conversation_id)
                    )
                ).scalar_one()
            assert written == 0, "a message was recorded for someone who opted out"
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
                await s.commit()


@pytest.mark.asyncio
async def test_an_ordinary_lead_is_unaffected(database_url: str) -> None:
    # The guard must not cost the normal case: this is the realtor's main way
    # of talking to people.
    lead_id, conversation_id = await _lead_with(database_url, opted_out=False)
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with await _client() as c:
                r = await c.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "Hi"})
            assert r.status_code == 200, r.text

            async with Session() as s:
                written = (
                    await s.execute(
                        select(func.count())
                        .select_from(Message)
                        .where(Message.conversation_id == conversation_id)
                    )
                ).scalar_one()
            assert written == 1
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
                await s.commit()


def test_every_function_that_sends_consults_the_opt_out() -> None:
    """The sweep that found it, kept as a test.

    Guarding the path in front of me while its sibling keeps the defect is the
    single most repeated mistake in this codebase. This walks every function
    that reaches a send and fails if one of them cannot see the opt-out.
    """
    senders = {"_dispatch_send", "send_whatsapp", "send_sms", "send_email"}
    # Allowed to send without checking, each for a stated reason:
    exempt = {
        # The low-level sender itself — it is what the others guard.
        "_dispatch_send",
        # Replying to a message the person just sent us. Answering someone who
        # wrote to us is not an unsolicited message, and refusing to reply
        # would be its own failure; it checks the opt-out separately to decide
        # whether to say anything automated.
        "handle_inbound_message",
    }
    unguarded = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in exempt:
                continue
            names = {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            } | {
                n.func.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            if not (names & senders):
                continue
            source = ast.dump(node)
            aware = "opted_out_at" in source or "may_send_automated" in names
            if not aware:
                unguarded.append(f"{path}::{node.name}")
    assert not unguarded, (
        f"these reach a send without consulting the opt-out: {unguarded}. "
        "Opt-out is revoked consent — it outranks everything else on record."
    )


def test_the_sweep_is_actually_looking_at_something() -> None:
    # A sweep that matches nothing passes silently, which is the failure it was
    # written to catch in the first place.
    from app.services import conversation

    assert "_dispatch_send" in inspect.getsource(conversation)
