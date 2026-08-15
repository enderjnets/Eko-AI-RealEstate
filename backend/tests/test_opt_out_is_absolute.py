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


# The real primitives, taken from where they are defined rather than from a
# list I typed. The first version of this sweep named `send_whatsapp`, which
# exists nowhere in this codebase, and `send_email`, which every caller imports
# under an alias — so two of its four names never matched anything and the
# sweep was blind to WhatsApp and email entirely. A guard-of-guards with the
# defect it was written to catch.
SENDING_PRIMITIVES = {
    "send_text_message",  # app/services/whatsapp.py
    "send_sms",           # app/services/sms.py
    "send_email",         # app/services/email.py
}

# Functions allowed to reach a send without consulting the opt-out, each for a
# reason that has been checked:
SEND_EXEMPT = {
    # The funnel every other sender goes through — it is the thing guarded.
    "_dispatch_send",
    # Answering someone who has just written to us. It sends only the STOP/START
    # confirmation the carriers require and then returns; any later message is
    # refused further down as `opted_out_no_reply`.
    "handle_inbound_message",
    # The adapters themselves: they are the primitive.
    "send_text_message",
    "send_sms",
    "send_email",
}

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _reaching_functions() -> tuple[list[str], int]:
    """Every function that can reach a send, following aliases and one hop.

    Aliased imports (`send_text_message as whatsapp_send`) are resolved per
    module, because the alias is what appears at the call site and matching on
    the original name finds nothing.
    """
    reaching, walked = [], 0
    for path in sorted(APP.rglob("*.py")):
        walked += 1
        tree = ast.parse(path.read_text())

        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for name in node.names:
                    if name.name in SENDING_PRIMITIVES:
                        aliases[name.asname or name.name] = name.name

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in SEND_EXEMPT:
                continue
            called = {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            } | {
                n.func.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            sends = called & (SENDING_PRIMITIVES | set(aliases) | {"_dispatch_send"})
            if not sends:
                continue
            source = ast.dump(node)
            aware = "opted_out_at" in source or "may_send_automated" in called
            if not aware:
                reaching.append(f"{path.relative_to(APP.parent)}::{node.name}")
    return reaching, walked


def test_every_function_that_sends_consults_the_opt_out() -> None:
    """The sweep that found the defect, kept so it cannot come back.

    Guarding the path in front of me while its sibling keeps the defect is the
    single most repeated mistake in this codebase; this enumerates the paths
    instead of relying on me to remember them.
    """
    unguarded, _ = _reaching_functions()
    assert not unguarded, (
        f"these reach a send without consulting the opt-out: {unguarded}. "
        "Opt-out is revoked consent — it outranks everything else on record."
    )


def test_the_sweep_is_actually_looking_at_something() -> None:
    """A sweep that matches nothing passes silently.

    The previous canary asserted a string was present in a module — true
    regardless of whether the sweep had walked a single file. Run from the repo
    root rather than `backend/`, the sweep's relative path resolved to nothing,
    it walked zero files, found zero problems, and both tests went green. The
    path is absolute now and this counts what was actually examined.
    """
    unguarded, walked = _reaching_functions()
    assert walked > 50, f"the sweep only walked {walked} files — has the path moved?"

    # And it can still see a sender: prove the matching works rather than
    # trusting that an empty result means a clean codebase.
    seen = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                called = {
                    n.func.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                }
                if called & (SENDING_PRIMITIVES | {"_dispatch_send"}):
                    seen.append(node.name)
    assert seen, "the sweep matched no sender at all — the names must be wrong"


@pytest.mark.asyncio
async def test_the_same_person_typed_differently_is_still_opted_out(
    database_url: str,
) -> None:
    """The opt-out has to attach to a person, not to a string.

    `+17205558217` and `720-555-8217` are one handset. They were two leads, so
    a STOP recorded against one said nothing about the other: re-add somebody
    from your own notes with the number typed differently and the system would
    message a person who had asked it to stop. No bad intent required — a
    hyphen is enough.
    """
    engine, Session = _session(database_url)
    canonical = "+17205559911"
    try:
        with org_scope(1):
            async with Session() as s:
                s.add(
                    Lead(
                        org_id=1,
                        phone=canonical,
                        status=LeadStatus.QUALIFIED,
                        opted_out_at=datetime.now(UTC),
                        opted_out_keyword="STOP",
                        opted_out_channel="sms",
                    )
                )
                await s.commit()

            async with await _client() as c:
                for typed in ("720-555-9911", "(720) 555-9911", "7205559911"):
                    r = await c.post(
                        "/api/v1/leads",
                        json={"phone": typed, "first_message": "Checking in!"},
                    )
                    assert r.status_code == 409, (
                        f"{typed!r} created a second lead for someone who opted out: {r.text}"
                    )

            async with Session() as s:
                count = (
                    await s.execute(
                        select(func.count())
                        .select_from(Lead)
                        .where(Lead.phone.like("%5559911"))
                    )
                ).scalar_one()
            assert count == 1, "the same person exists as more than one lead"
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(
                    text("DELETE FROM leads WHERE phone LIKE :p"), {"p": "%5559911"}
                )
                await s.commit()
