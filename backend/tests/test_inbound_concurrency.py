"""What happens when two inbound messages arrive at the same instant.

An audit ran four concurrent webhooks against a fresh tenant and three leads
never appeared. Nothing looked wrong: every request answered 200, the provider
was told the delivery succeeded and never retried, and the log said "idempotent
skip". The cause was that all four raced to bootstrap the same singleton row,
one won, and the losers' IntegrityError destroyed a transaction that by then
also held their brand-new lead, conversation and message.

These tests reproduce that shape. They are slow-ish and use real concurrent
sessions on purpose — a serial test cannot see any of it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.organization import DEFAULT_ORG_ID
from app.services import tenant_resolver
from app.services._common import ParsedMessage
from app.services.conversation import handle_inbound_message
from app.services.tenant_context import org_scope

TENANT_ID = 720
TENANT_SLUG = "concurrency-agency"


async def _make_tenant() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, :n, :s, 'active', 'pilot') ON CONFLICT (id) DO NOTHING"
            ),
            {"i": TENANT_ID, "n": TENANT_SLUG, "s": TENANT_SLUG},
        )
        # Deliberately no agent_settings row: a brand-new agency has none, and
        # bootstrapping it is what the concurrent messages collide on.
        await db.execute(
            text("DELETE FROM agent_settings WHERE org_id = :i"), {"i": TENANT_ID}
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _drop_tenant() -> None:
    async with get_bypass_session_factory()() as db:
        for table in (
            "messages",
            "conversations",
            "follow_ups",
            "visits",
            "leads",
            "agent_settings",
            "user_activity",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE org_id = :i"), {"i": TENANT_ID}
            )
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": TENANT_ID})
        await db.commit()
    tenant_resolver.reset_cache()


async def _inbound_count(org_id: int) -> int:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text(
                    "SELECT count(*) FROM messages "
                    "WHERE org_id = :i AND direction = 'inbound'"
                ),
                {"i": org_id},
            )
        ).scalar_one()


async def _count(table: str, org_id: int) -> int:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text(f"SELECT count(*) FROM {table} WHERE org_id = :i"), {"i": org_id}
            )
        ).scalar_one()


def _message(phone: str, external_id: str) -> ParsedMessage:
    return ParsedMessage(
        channel="sms",
        external_id=external_id,
        from_identifier=phone,
        from_name=None,
        content="Hi, I saw a listing in Wash Park. Is it still available?",
    )


async def _deliver(msg: ParsedMessage, org_id: int) -> str:
    """One webhook delivery: its own session, its own transaction, its own org."""
    with org_scope(org_id):
        async with get_session_factory()() as db:
            try:
                await handle_inbound_message(msg, db)
                await db.commit()
                return "ok"
            except Exception as exc:  # noqa: BLE001 — the point is to see these
                await db.rollback()
                return f"error: {type(exc).__name__}: {exc}"


@pytest.fixture(autouse=True)
async def _tenant() -> object:
    await _make_tenant()
    yield
    await _drop_tenant()


@pytest.fixture(autouse=True)
def _no_llm() -> object:
    """Stub the two model calls. Without this each delivery waits out a real
    provider timeout, and the race being tested is over in milliseconds."""
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.llm import LLMResult

    intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.9,
        entities=IntentEntities(zone="Wash Park"),
    )
    reply = LLMResult(
        text="Yes, it is. Would you like to see it this week?",
        provider="stub", model="stub", input_tokens=1, output_tokens=1,
    )
    with patch("app.services.conversation.classify_intent", AsyncMock(return_value=intent)), \
         patch("app.services.conversation.generate_reply", AsyncMock(return_value=reply)):
        yield


@pytest.mark.asyncio
async def test_four_simultaneous_first_contacts_create_four_leads() -> None:
    """The reproduction. Four different people text a brand-new agency at once.

    Before the fix this produced one lead: all four raced to create the
    singleton `agent_settings` row for the org, three lost the unique index, and
    their leads went down with the transaction — reported to the provider as a
    successful, idempotent delivery.
    """
    phones = [f"+1303555{n:04d}" for n in range(4)]
    outcomes = await asyncio.gather(
        *(_deliver(_message(p, f"ext-{p}"), TENANT_ID) for p in phones)
    )

    leads = await _count("leads", TENANT_ID)
    assert leads == 4, (
        f"{4 - leads} lead(s) silently lost. Outcomes: {outcomes}"
    )
    assert await _count("agent_settings", TENANT_ID) == 1
    # Each lead must keep its own inbound message, not just exist as a row.
    assert await _count("messages", TENANT_ID) >= 4


@pytest.mark.asyncio
async def test_two_messages_from_one_person_at_once_keep_both() -> None:
    """Someone sends two texts in the same breath — extremely common.

    One lead, one conversation, and *both* messages. The loser of the lead race
    used to die on the unique index with its own message still uncommitted, so
    the second text simply never existed. Asserting "one lead" alone would pass
    against that bug, which is why the message count and the outcomes are here.
    """
    phone = "+13035557777"
    outcomes = await asyncio.gather(
        _deliver(_message(phone, "ext-a"), TENANT_ID),
        _deliver(_message(phone, "ext-b"), TENANT_ID),
    )

    assert outcomes == ["ok", "ok"], outcomes
    assert await _count("leads", TENANT_ID) == 1
    assert await _inbound_count(TENANT_ID) == 2, (
        f"one of the two texts was dropped. Outcomes: {outcomes}"
    )


@pytest.mark.asyncio
async def test_the_database_refuses_a_second_active_conversation() -> None:
    """The model's docstring has always said one active conversation per lead
    and channel; until migration 022 nothing enforced it.

    Two of them make the lookup — which uses `scalar_one_or_none()` — raise
    MultipleResultsFound on *every* later message from that person: a permanent,
    unexplained break for one lead. This asserts the constraint itself rather
    than staging a race, because with the lead get-or-create in place the two
    deliveries serialise behind the lead row and the second finds the first's
    conversation. The index is the guarantee that holds when they do not.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models import Conversation, Lead
    from app.models.conversation import ConversationStatus

    with org_scope(TENANT_ID):
        async with get_session_factory()() as db:
            lead = Lead(phone="+13035554444")
            db.add(lead)
            await db.flush()
            for _ in range(2):
                db.add(
                    Conversation(
                        lead_id=lead.id,
                        channel="sms",
                        status=ConversationStatus.ACTIVE,
                    )
                )
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()

    # Archived ones are history and may pile up: a lead who returns months later
    # legitimately gets a fresh conversation.
    with org_scope(TENANT_ID):
        async with get_session_factory()() as db:
            lead = Lead(phone="+13035554445")
            db.add(lead)
            await db.flush()
            db.add(
                Conversation(
                    lead_id=lead.id, channel="sms", status=ConversationStatus.ARCHIVED
                )
            )
            db.add(
                Conversation(
                    lead_id=lead.id, channel="sms", status=ConversationStatus.ARCHIVED
                )
            )
            db.add(
                Conversation(
                    lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_the_loser_of_an_insert_race_adopts_the_winners_row() -> None:
    """`first_or_create` must absorb the violation it exists for, not re-raise it.

    Eight sessions ask for the same lead at once. Every one of them issues its
    SELECT before any INSERT can commit — the SELECT is the first await, so the
    event loop has them all in flight together — which means seven are certain
    to take the losing branch. All eight must come back with the same row.
    """
    from sqlalchemy import select

    from app.db.base import first_or_create
    from app.models import Lead

    phone = "+13035553333"
    stmt = select(Lead).where(Lead.phone == phone)

    async def _claim() -> int:
        with org_scope(TENANT_ID):
            async with get_session_factory()() as db:
                lead = await first_or_create(db, stmt, lambda: Lead(phone=phone))
                await db.commit()
                return lead.id

    ids = await asyncio.gather(*(_claim() for _ in range(8)))

    assert len(set(ids)) == 1, f"the racers ended up on different leads: {ids}"
    assert await _count("leads", TENANT_ID) == 1


@pytest.mark.asyncio
async def test_a_redelivered_message_is_skipped_without_losing_anything() -> None:
    """The ordinary redelivery: the provider sends the same message twice.

    This is the path the idempotency check handles, and it must stay cheap and
    lossless. The flush-level collision behind it — where two copies both get
    past the check before either writes — is covered by a savepoint rather than
    by a test; see the note on `test_a_savepoint_keeps_a_failed_insert_local`.
    """
    phone = "+13035558888"
    assert await _deliver(_message(phone, "ext-same"), TENANT_ID) == "ok"
    assert await _deliver(_message(phone, "ext-same"), TENANT_ID) == "ok"

    assert await _count("leads", TENANT_ID) == 1
    assert await _inbound_count(TENANT_ID) == 1


@pytest.mark.asyncio
async def test_a_savepoint_keeps_a_failed_insert_local() -> None:
    """The transaction shape the duplicate handlers rely on, tested directly.

    The race that reaches those handlers cannot be staged deterministically:
    the idempotency check and the insert it guards are adjacent, so forcing a
    commit between them would need a seam that exists only for the test. What
    *can* be pinned down is the property the fix depends on — that a violation
    inside `begin_nested()` costs only its own statement, and that the session
    can still commit afterwards.

    The first version of this test added the colliding row *inside* the
    savepoint and nowhere checked that production did the same. Production
    added it **before**, and `begin_nested()` flushes pending work before
    issuing the SAVEPOINT — so the violation escaped the savepoint entirely,
    the transaction went inactive, and the `commit()` in the handler raised
    PendingRollbackError. Nine audit rounds and a green suite missed it because
    this test exercised the shape that works. Both shapes are asserted now: the
    one production uses must behave, and the broken one must be visibly broken,
    so reverting the fix fails here rather than in a customer's inbox.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models import Conversation, Lead, Message
    from app.models.conversation import ConversationStatus
    from app.models.message import MessageDirection, MessageSender

    def _inbound(conv_id: int) -> Message:
        return Message(
            conversation_id=conv_id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content="hi",
            external_id="collide",
        )

    with org_scope(TENANT_ID):
        async with get_session_factory()() as db:
            lead = Lead(phone="+13035551111")
            db.add(lead)
            await db.flush()
            conv = Conversation(
                lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE
            )
            db.add(conv)
            await db.flush()
            db.add(_inbound(conv.id))
            await db.flush()

            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(_inbound(conv.id))
                    await db.flush()

            await db.commit()

    assert await _count("leads", TENANT_ID) == 1, "the savepoint took the lead with it"
    assert await _inbound_count(TENANT_ID) == 1


@pytest.mark.asyncio
async def test_concurrent_messages_stay_inside_their_own_agency() -> None:
    """The whole point of the isolation work: concurrency must not cross tenants.

    Same phone number texting two different agencies at the same moment — a
    genuinely common case, since one person can be shopping with two realtors.
    """
    phone = "+13035556666"
    before_default = await _count("leads", DEFAULT_ORG_ID)

    await asyncio.gather(
        _deliver(_message(phone, "ext-agency-a"), DEFAULT_ORG_ID),
        _deliver(_message(phone, "ext-agency-b"), TENANT_ID),
    )

    assert await _count("leads", TENANT_ID) == 1
    assert await _count("leads", DEFAULT_ORG_ID) == before_default + 1

    async with get_bypass_session_factory()() as db:
        owners = (
            await db.execute(
                text("SELECT org_id FROM leads WHERE phone = :p ORDER BY org_id"),
                {"p": phone},
            )
        ).scalars().all()
    assert owners == [DEFAULT_ORG_ID, TENANT_ID]

    # The default org is not covered by `_drop_tenant`, and this is the only
    # test that writes into it. Leaving the row behind made a later test that
    # used the same number collide on `leads.phone`, which is unique per org —
    # a failure in a file that had nothing to do with this one.
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT c.id FROM conversations c JOIN leads l ON l.id = c.lead_id "
                " WHERE l.phone = :p AND l.org_id = :o)"
            ),
            {"p": phone, "o": DEFAULT_ORG_ID},
        )
        await db.execute(
            text(
                "DELETE FROM conversations WHERE lead_id IN "
                "(SELECT id FROM leads WHERE phone = :p AND org_id = :o)"
            ),
            {"p": phone, "o": DEFAULT_ORG_ID},
        )
        await db.execute(
            text("DELETE FROM leads WHERE phone = :p AND org_id = :o"),
            {"p": phone, "o": DEFAULT_ORG_ID},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_a_duplicate_inbound_message_leaves_the_turn_committable() -> None:
    """The production shape, end to end, with the collision forced.

    A message is added and flushed inside the savepoint; the savepoint rolls
    back on the violation; and the session must still commit the lead and
    conversation created earlier in the same call. That last step is what
    PendingRollbackError used to break — turning a duplicate into a 500 the
    provider retries, and losing the lead with it.
    """
    from sqlalchemy.exc import IntegrityError, PendingRollbackError

    from app.models import Conversation, Lead, Message
    from app.models.conversation import ConversationStatus
    from app.models.message import MessageDirection, MessageSender

    def _inbound(conv_id: int) -> Message:
        return Message(
            conversation_id=conv_id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content="hi",
            external_id="prod-shape-collide",
        )

    with org_scope(TENANT_ID):
        async with get_session_factory()() as db:
            winner = Lead(phone="+13035552222")
            db.add(winner)
            await db.flush()
            conv = Conversation(
                lead_id=winner.id, channel="sms", status=ConversationStatus.ACTIVE
            )
            db.add(conv)
            await db.flush()
            db.add(_inbound(conv.id))
            await db.commit()

        async with get_session_factory()() as db:
            # The turn creates its own rows first, exactly as the handler does.
            latecomer = Lead(phone="+13035552223")
            db.add(latecomer)
            await db.flush()
            second = Conversation(
                lead_id=latecomer.id, channel="sms", status=ConversationStatus.ACTIVE
            )
            db.add(second)
            await db.flush()

            try:
                async with db.begin_nested():
                    db.add(_inbound(second.id))
                    await db.flush()
                raise AssertionError("the duplicate did not collide")
            except IntegrityError:
                pass

            try:
                await db.commit()
            except PendingRollbackError as exc:  # pragma: no cover - the defect
                raise AssertionError(
                    "the savepoint did not contain the violation, so the whole "
                    f"turn was lost: {exc}"
                ) from exc

    # The latecomer's lead survived the duplicate message.
    assert await _count("leads", TENANT_ID) == 2


def test_no_savepoint_guards_work_that_was_already_pending() -> None:
    """Every `begin_nested()` block must do its own writing.

    This is a static check because the runtime one cannot be staged: the
    idempotency SELECT and the insert it guards are adjacent, so forcing a
    competing commit between them needs a seam that exists only for a test.
    What can be pinned is the invariant that was violated — `begin_nested()`
    flushes pending work *before* issuing the SAVEPOINT, so anything added
    beforehand runs in the outer transaction and its violation escapes the
    savepoint entirely, leaving the session unusable and the following
    `commit()` raising PendingRollbackError.

    Three blocks in this module had exactly that shape and nine audit rounds
    read past them, because the only test of the pattern wrote inside the
    savepoint while production wrote outside.
    """
    import ast
    import inspect

    from app.services import conversation

    tree = ast.parse(inspect.getsource(conversation))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncWith):
            continue
        opens_savepoint = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin_nested"
            for item in node.items
        )
        if not opens_savepoint:
            continue
        checked += 1
        writes = [
            stmt
            for stmt in node.body
            if isinstance(stmt, ast.Assign)
            or (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr in {"add", "add_all"}
            )
        ]
        assert writes, (
            f"the savepoint at conversation.py:{node.lineno} only flushes — "
            "whatever it is meant to protect was made pending before it, so "
            "the violation will escape and take the transaction with it"
        )

    assert checked >= 3, f"expected the three known savepoints, found {checked}"
