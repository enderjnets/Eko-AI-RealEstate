"""The appointment invitation has to leave a trace, and the trace has to be safe.

Two emails go out when a visit is booked: one to the lead, one to the agency's
booking mailbox. Until now neither appeared anywhere — the panel showed a visit
and no evidence that anybody had been told about it, which is a hole in the
record at the single most commercially important moment of the funnel.

Writing them down is easy. Writing them down WITHOUT breaking two machines that
walk this table by shape is the actual work, and it is what these tests pin:

  * `delivery.py::_still_owed` re-sends outbound rows with no `external_id`.
    The agency's note landing there would be delivered TO THE LEAD, carrying
    their own name, phone and what they asked for.
  * `conversation.py` builds the LLM's context from the conversation. An
    internal note read as a turn is a note the model can quote back at them.

Both are guarded by `internal IS false`, and both guards have a mutation behind
them below.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.channel_route import CHANNEL_EMAIL
from app.models.conversation import Conversation, ConversationStatus
from app.models.lead import Lead, LeadStatus
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.models.visit import Visit, VisitStatus
from app.services.delivery import MAX_ATTEMPTS
from app.services.tenant_context import org_scope
from app.services.visit_invite import send_visit_invitation

ORG = 1
PHONE = "+19995550401"
LEAD_EMAIL = "record-probe@example.com"
BOOKING_REF = "record-probe-visit"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


AGENCY_EMAIL = "record-probe-agency@example.com"


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """The agency copy only exists when `booking_contact_email` is set.

    Restored afterwards: leaving a probe address behind would silently redirect
    every other test's agency notification, and it took a failing run to notice
    the column was empty here in the first place.
    """
    from app.models.agent_settings import AgentSettings

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
    """A lead with NO email conversation yet, and a visit for them.

    No thread on purpose: a lead who booked from the web form or over the phone
    has never sent us an email, and that is precisely the case a look-up-only
    helper would skip in silence.
    """
    await _cleanup()
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            name="Record Probe",
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
            scheduled_at=datetime.now(UTC) + timedelta(days=3),
            duration_minutes=45,
            timezone="America/Denver",
            property_address="1234 S Downing St, Denver, CO",
        )
        db.add(visit)
        await db.commit()
        return lead.id, visit.id


async def _seed_thread(
    lead_id: int, channel: str = "sms", *, with_inbound: bool = False
) -> int:
    """An existing ACTIVE conversation, optionally with an unanswered inbound."""
    async with get_bypass_session_factory()() as db:
        conv = Conversation(
            org_id=ORG,
            lead_id=lead_id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
        )
        db.add(conv)
        await db.flush()
        if with_inbound:
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="Is Saturday still possible?",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
        await db.commit()
        return conv.id


async def _conversations(lead_id: int) -> list[Conversation]:
    async with get_bypass_session_factory()() as db:
        return list(
            (
                await db.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalars().all()
        )


async def _messages(lead_id: int) -> list[Message]:
    async with get_bypass_session_factory()() as db:
        rows = await db.execute(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id == lead_id)
            .order_by(Message.id)
        )
        return list(rows.scalars().all())


def _sender(*ids: str) -> AsyncMock:
    """A stub that behaves like Resend: one id per message, never repeated.

    A single `return_value` gave both emails the same id and tripped
    `uq_messages_external_id` (unique per org) — the stub, not the code. Worth
    keeping as a named helper so the next test cannot reintroduce it.
    """
    return AsyncMock(side_effect=[{"id": i} for i in ids])


async def _invite(lead_id: int, visit_id: int, sender: AsyncMock) -> None:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.id == lead_id))
            ).scalar_one()
            visit = (
                await db.execute(select(Visit).where(Visit.id == visit_id))
            ).scalar_one()
            with patch("app.services.visit_invite.send_email", sender):
                await send_visit_invitation(db, visit, lead, language="en")


# ── El registro ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_copies_land_in_the_thread(database_url: str) -> None:
    """One row for the lead, one internal for the agency — in a thread that did
    not exist before this booking."""
    lead_id, visit_id = await _seed()
    try:
        await _invite(lead_id, visit_id, _sender("re_lead_1", "re_agency_1"))
        rows = await _messages(lead_id)
        assert len(rows) == 2, f"expected the lead copy and the agency note, got {len(rows)}"

        lead_copy = [m for m in rows if not m.internal]
        note = [m for m in rows if m.internal]
        assert len(lead_copy) == 1 and len(note) == 1

        for m in rows:
            assert m.direction is MessageDirection.OUTBOUND
            assert m.sender is MessageSender.AGENT
            assert m.delivery_status is MessageStatus.SENT
            assert m.external_id, "no provider id recorded — the row is sweep-eligible"
            assert m.subject

        # The agency's copy carries the lead's own details; that is the point of
        # it, and the reason it must never be deliverable to them.
        assert PHONE in note[0].content
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_thread_is_created_when_the_lead_never_wrote(database_url: str) -> None:
    """The case a look-up-only helper would drop: no email conversation yet."""
    lead_id, visit_id = await _seed()
    try:
        async with get_bypass_session_factory()() as db:
            before = (
                await db.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalars().all()
        assert before == [], "the fixture is wrong: this lead should have no thread"

        await _invite(lead_id, visit_id, _sender("re_lead_2", "re_agency_2b"))

        async with get_bypass_session_factory()() as db:
            convs = (
                await db.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalars().all()
        assert len(convs) == 1
        assert convs[0].channel == CHANNEL_EMAIL
        assert convs[0].status is ConversationStatus.ACTIVE
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_with_no_email_files_the_note_in_their_existing_thread(
    database_url: str,
) -> None:
    """Phone-only lead with a live SMS thread: the note rides in THAT thread.

    Creating an `email` conversation here was the audited defect B2: born with
    the newest `last_at`, it became the "primary" conversation — the composer
    flipped to a channel this lead cannot receive, and the suggestions endpoint
    started answering `empty_conversation` for a lead with a real SMS history.
    """
    lead_id, visit_id = await _seed(email=None)
    conv_id = await _seed_thread(lead_id, "sms")
    try:
        await _invite(lead_id, visit_id, _sender("re_agency_only"))
        rows = await _messages(lead_id)
        assert len(rows) == 1
        assert rows[0].internal is True
        assert rows[0].conversation_id == conv_id, "the note did not reuse the live thread"
        convs = await _conversations(lead_id)
        assert [c.channel for c in convs] == ["sms"], (
            f"an extra conversation was created: {[c.channel for c in convs]}"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_bare_lead_with_no_email_and_no_thread_records_nothing(
    database_url: str,
) -> None:
    """No conversation and no email address: nothing to safely attach to.

    The alternative — inventing an email conversation for a lead with no email
    — is what hijacked the composer. Skipping with a log is the status quo of
    every invitation sent before this feature existed."""
    lead_id, visit_id = await _seed(email=None)
    try:
        await _invite(lead_id, visit_id, _sender("re_agency_bare"))
        assert await _messages(lead_id) == []
        assert await _conversations(lead_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_recording_reuses_the_existing_thread_and_leaves_primary_alone(
    database_url: str,
) -> None:
    """A lead with email whose live thread is WhatsApp keeps WhatsApp primary:
    both records ride the existing conversation and no email one appears."""
    lead_id, visit_id = await _seed()
    conv_id = await _seed_thread(lead_id, "whatsapp")
    try:
        await _invite(lead_id, visit_id, _sender("re_l_wa", "re_a_wa"))
        rows = await _messages(lead_id)
        assert len(rows) == 2
        assert {m.conversation_id for m in rows} == {conv_id}
        convs = await _conversations(lead_id)
        assert [c.channel for c in convs] == ["whatsapp"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_internal_note_does_not_answer_the_lead(database_url: str) -> None:
    """The audited defect B1, pinned from the Inbox's side.

    A phone-only lead asked a question nobody answered. Booking their visit
    writes ONLY the internal note — and that note must not become "the last
    word": unfiltered, `needs_response` flipped to False and the waiting lead
    silently left the triage queue."""
    from app.services.inbox import (
        _last_message_per_lead,
        _last_reaching_message_per_lead,
    )

    lead_id, visit_id = await _seed(email=None)
    await _seed_thread(lead_id, "sms", with_inbound=True)
    try:
        await _invite(lead_id, visit_id, _sender("re_note_b1"))
        rows = await _messages(lead_id)
        assert [m.internal for m in rows] == [False, True], "fixture drifted"

        with org_scope(ORG):
            async with get_session_factory()() as db:
                reaching = await _last_reaching_message_per_lead(db)
                shown = await _last_message_per_lead(db)
        assert reaching[lead_id].direction is MessageDirection.INBOUND, (
            "the internal note counted as the last word — this lead just "
            "dropped out of the triage queue while still waiting for an answer"
        )
        assert "Saturday" in shown[lead_id].content, (
            "the inbox preview shows the agency's note as the last thing said"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_failing_first_record_costs_neither_the_second_nor_the_caller(
    database_url: str,
) -> None:
    """Recording runs on its own session, so a failure in the lead-copy record
    cannot poison the agency note's, and the CALLER's objects stay live — the
    booking handler reads `visit` attributes right after this returns, and an
    expired instance there turns a committed booking into a 500."""
    lead_id, visit_id = await _seed()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                lead = (
                    await db.execute(select(Lead).where(Lead.id == lead_id))
                ).scalar_one()
                visit = (
                    await db.execute(select(Visit).where(Visit.id == visit_id))
                ).scalar_one()
                # `find_violations` runs only for the lead-facing record, so
                # one raise fails exactly the first record and nothing else.
                with patch("app.services.visit_invite.send_email",
                           _sender("re_f1", "re_f2")), patch(
                    "app.services.fair_housing.find_violations",
                    side_effect=RuntimeError("screening blew up"),
                ):
                    await send_visit_invitation(db, visit, lead, language="en")
                # The caller's session must still answer without a refresh.
                assert visit.scheduled_at is not None
                assert lead.email == LEAD_EMAIL
        rows = await _messages(lead_id)
        assert [m.internal for m in rows] == [True], (
            "the agency note was lost to the lead copy's failure"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opted_out_lead_gets_no_copy_but_the_agency_note_is_filed(
    database_url: str,
) -> None:
    """Opt-out is revoked consent and outranks a booking. The agent still needs
    to know, and still needs it in the file."""
    lead_id, visit_id = await _seed(opted_out=True)
    try:
        await _invite(lead_id, visit_id, _sender("re_agency_optout"))
        rows = await _messages(lead_id)
        assert [m.internal for m in rows] == [True], (
            "an opted-out lead was written an outbound row"
        )
    finally:
        await _cleanup()


# ── El fallo se dice, no se disfraza ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_send_is_recorded_and_never_retried(database_url: str) -> None:
    """FAILED with the attempts spent, so the sweep leaves it alone.

    Blind retry is not an option: the sweep re-sends through `_dispatch_send`,
    which knows nothing about attachments — the lead would get the invitation
    text with no `.ics`, which is the only part that matters.
    """
    lead_id, visit_id = await _seed()
    try:
        await _invite(lead_id, visit_id, AsyncMock(side_effect=RuntimeError("resend 500")))
        rows = await _messages(lead_id)
        assert len(rows) == 2
        for m in rows:
            assert m.delivery_status is MessageStatus.FAILED
            assert m.external_id is None
            assert m.send_attempts == MAX_ATTEMPTS, (
                "attempts not spent — the delivery sweep would re-send this "
                "without the calendar attachment"
            )
            assert m.last_error

        from app.services.delivery import retry_pending_sends

        with org_scope(ORG):
            async with get_session_factory()() as db:
                result = await retry_pending_sends(db)
        assert result["sent"] == 0, f"the sweep picked up an invitation row: {result}"
    finally:
        await _cleanup()


# ── Las dos defensas ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_delivery_sweep_never_touches_an_internal_note(
    database_url: str,
) -> None:
    """The one that protects the lead.

    Built by hand in the exact shape the sweep looks for — OUTBOUND, PENDING,
    no external_id, attempts left, old enough to count as abandoned — so the
    only thing keeping it out is the `internal` filter itself.
    """
    lead_id, visit_id = await _seed()
    try:
        await _invite(lead_id, visit_id, _sender("re_ok_a", "re_ok_b"))
        async with get_bypass_session_factory()() as db:
            conv = (
                await db.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalars().first()
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Who: Record Probe / Phone: +19995550401",
                    internal=True,
                    delivery_status=MessageStatus.PENDING,
                    external_id=None,
                    send_attempts=0,
                    created_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            await db.commit()

        from app.services.delivery import retry_pending_sends

        dispatch = AsyncMock(return_value=("re_sent", None))
        with patch("app.services.conversation._dispatch_send", dispatch):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    await retry_pending_sends(db)
        assert dispatch.await_count == 0, (
            "the internal note was dispatched — the lead would have received "
            "the agency's copy of their own details"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_llm_never_reads_an_internal_note(database_url: str) -> None:
    """The one that protects the conversation.

    An internal note in the history arrives as an ordinary assistant turn, and
    a model that sees "Who: … Phone: …" in its own past output will happily
    produce more of it.
    """
    lead_id, visit_id = await _seed()
    marker = "INTERNAL-MARKER-DO-NOT-QUOTE"
    try:
        await _invite(lead_id, visit_id, _sender("re_ok_2a", "re_ok_2b"))
        async with get_bypass_session_factory()() as db:
            conv = (
                await db.execute(
                    select(Conversation).where(Conversation.lead_id == lead_id)
                )
            ).scalars().first()
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content=marker,
                    internal=True,
                    delivery_status=MessageStatus.SENT,
                    external_id="re_internal",
                )
            )
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="Can we move it to Friday?",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
            await db.commit()
            conv_id = conv.id

        from app.services import conversation as conv_mod

        captured: dict[str, object] = {}

        async def _fake_generate(messages, **kwargs):  # noqa: ANN001, ANN202
            captured["messages"] = messages
            from app.services.llm import LLMResult

            return LLMResult(
                text="Sure.", provider="kimi", model="t", input_tokens=1, output_tokens=1
            )

        with patch.object(conv_mod, "generate_reply", _fake_generate):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    await conv_mod.generate_reply_suggestions(lead_id, db)

        turns = captured.get("messages")
        assert turns is not None, "the suggestion path did not reach the model"
        blob = " ".join(str(m.get("content", "")) for m in turns)
        assert marker not in blob, (
            f"the internal note reached the model's context (conversation {conv_id})"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_repeated_provider_id_costs_one_row_and_raises_nothing(
    database_url: str,
) -> None:
    """`messages.external_id` is unique per org. Resend never repeats an id, so
    this is a provider anomaly rather than a real case — but the failure mode
    is worth pinning: the first row survives, the second is logged and dropped,
    and the booking is never affected."""
    lead_id, visit_id = await _seed()
    try:
        await _invite(lead_id, visit_id, _sender("re_same", "re_same"))
        rows = await _messages(lead_id)
        assert len(rows) == 1, "a collision cost more than the colliding row"
        assert rows[0].external_id == "re_same"
    finally:
        await _cleanup()
