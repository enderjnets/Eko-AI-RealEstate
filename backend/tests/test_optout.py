"""STOP has to work, because the consent record says it does.

The capture form's disclosure — stored verbatim as the legal record of what the
person agreed to — reads "reply STOP to opt out" in English and "responde STOP
para darte de baja" in Spanish. Until this file existed, nothing implemented
it, and the failure was not a missing feature but an inverted one: the consent
gate treats any inbound message on a channel as consumer-initiated contact, and
STOP is an inbound message. Sending it moved a correctly blocked lead to
sendable.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.conversation import Conversation, ConversationStatus
from app.models.lead import Lead
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.capture import may_send_automated
from app.services.optout import opt_in_keyword, opt_out_keyword

MARK = "+19995552"


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM leads WHERE phone LIKE :m"), {"m": f"{MARK}%"}
        )
        await db.commit()


# ── Recognising the word ─────────────────────────────────────────────────


def test_the_ctia_keywords_are_recognised() -> None:
    for word in ("STOP", "stop", "Stop", "STOPALL", "unsubscribe", "CANCEL", "quit"):
        assert opt_out_keyword(word, "sms") == word.strip().lower(), word


def test_spanish_speakers_can_opt_out_in_spanish() -> None:
    # A bilingual Denver audience types "baja" and "cancelar". An opt-out
    # mechanism that only works in English is not an opt-out mechanism for the
    # half of the audience the product markets to in Spanish.
    for word in ("BAJA", "parar", "detener", "darme de baja"):
        assert opt_out_keyword(word, "sms") is not None, word


def test_punctuation_does_not_defeat_it() -> None:
    # Carriers ignore surrounding punctuation and so must we; "STOP." typed
    # with a full stop is the overwhelmingly common form.
    for word in ("STOP.", " stop ", "(stop)", "STOP!", "¿parar?"):
        assert opt_out_keyword(word, "sms") is not None, word


def test_the_phone_keyboard_does_not_defeat_it() -> None:
    # iOS and Android substitute curly quotes, an ellipsis character and em
    # dashes for what the person typed. A revocation that fails because the
    # keyboard was helpful is a revocation that did not happen.
    for word in ("stop\u2026", "\u201cSTOP\u201d", "STOP\u2014", "\U0001f6d1 STOP", "stop\u00a0"):
        assert opt_out_keyword(word, "sms") is not None, repr(word)


def test_spanish_words_that_mean_an_appointment_are_not_opt_outs() -> None:
    # `CANCEL` is in the CTIA set and has to stay. Its Spanish cognates are
    # required by nobody and are what a bilingual client types about a VIEWING
    # — "cancelar" as a whole message far more often means "cancel Tuesday"
    # than "never contact me again". Silencing a live buyer is the worse error,
    # and it is the one they cannot undo without knowing about START.
    assert opt_out_keyword("cancel", "sms") == "cancel"
    assert opt_out_keyword("cancelar", "sms") is None
    assert opt_out_keyword("eliminar", "sms") is None


def test_the_spaced_and_spanish_long_forms_work() -> None:
    assert opt_out_keyword("opt out", "sms") is not None
    assert opt_out_keyword("darme de baja", "sms") is not None


def test_a_sentence_containing_stop_is_not_an_opt_out() -> None:
    # "Can I stop by the open house on Sunday?" is a live buyer asking for a
    # viewing. Substring matching would silence them permanently.
    for sentence in (
        "Can I stop by the open house on Sunday?",
        "stop by anytime",
        "I want to cancel my Tuesday viewing, can we do Thursday?",
        "please don't stop sending me listings",
    ):
        assert opt_out_keyword(sentence, "sms") is None, sentence


def test_email_is_not_an_opt_out_channel() -> None:
    # Email unsubscribe is a link and a List-Unsubscribe header. Treating a
    # one-word email as revocation would silence someone who wrote "cancel"
    # about an appointment.
    assert opt_out_keyword("STOP", "email") is None
    assert opt_out_keyword("STOP", "web") is None
    assert opt_out_keyword("STOP", "sms") == "stop"


def test_agreement_is_not_re_consent() -> None:
    """"Sí" must not resubscribe anybody.

    `yes`, `si` and `sí` were opt-in words, and they are the most common single
    word a person sends. A lead who had opted out and then answered "Sí" to
    anything at all — a question from the agent, an unrelated thread — silently
    resubscribed themselves to the automated messages they had asked to stop.
    CTIA requires START and UNSTOP; it does not require agreement words, and
    reading agreement as re-consent is exactly backwards.
    """
    for word in ("yes", "YES", "si", "sí", "Sí", "ok", "vale"):
        assert opt_in_keyword(word, "sms") is None, word
    # The real ones still work.
    for word in ("START", "unstop", "ALTA", "resume", "opt in"):
        assert opt_in_keyword(word, "sms") is not None, word


def test_start_words_are_recognised_separately() -> None:
    assert opt_in_keyword("START", "sms") == "start"
    assert opt_in_keyword("ALTA", "sms") == "alta"
    assert opt_in_keyword("STOP", "sms") is None
    assert opt_out_keyword("START", "sms") is None


# ── Honouring it ─────────────────────────────────────────────────────────


async def _lead(db, *, suffix: str, consent: bool, opted_out: bool) -> Lead:
    lead = Lead(
        phone=f"{MARK}{suffix}",
        name="Optout Test",
        consent_at=datetime.now(UTC) - timedelta(days=1) if consent else None,
        consent_text="I agree to receive texts." if consent else None,
        opted_out_at=datetime.now(UTC) if opted_out else None,
        opted_out_channel="sms" if opted_out else None,
        opted_out_keyword="stop" if opted_out else None,
    )
    db.add(lead)
    await db.flush()
    conv = Conversation(
        lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE,
        last_at=datetime.now(UTC),
    )
    db.add(conv)
    await db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content="hello",
            delivery_status=MessageStatus.DELIVERED,
        )
    )
    await db.commit()
    return lead


@pytest.mark.asyncio
async def test_an_opt_out_beats_written_consent() -> None:
    # Consent is permission to start; STOP is an instruction to stop, and it is
    # the more recent statement of what this person wants.
    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="01", consent=True, opted_out=True)
            assert await may_send_automated(lead, "sms", db) is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opt_out_beats_consumer_initiated_contact() -> None:
    # THE regression. This lead has an inbound SMS, which satisfies the
    # consumer-initiated branch — the branch that made STOP itself unlock
    # sending, because STOP arrives as an inbound message on that channel.
    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="02", consent=False, opted_out=True)
            assert await may_send_automated(lead, "sms", db) is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opt_out_stops_every_gated_channel_not_just_the_one_used() -> None:
    # They said stop on SMS. Continuing on WhatsApp because the word arrived
    # over a different transport is the letter of the rule against its point.
    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="03", consent=True, opted_out=True)
            assert await may_send_automated(lead, "whatsapp", db) is False
            assert await may_send_automated(lead, "sms", db) is False
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opt_out_suppresses_automated_email_too() -> None:
    """Broader than the law requires, and deliberately so.

    CAN-SPAM would permit continuing to email someone who only texted STOP, and
    the letter of TCPA is per channel. But "stop" means stop, and the cost of
    reading it broadly is bounded — this gate covers AUTOMATED messages only,
    so a realtor can still write to them personally. Pinned here because the
    behaviour otherwise looks like an accident of check ordering.
    """
    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="08", consent=True, opted_out=True)
            assert await may_send_automated(lead, "email", db) is False
            # And email is NOT gated for anyone who has not opted out — the
            # suppression comes from the opt-out, not from gating email.
            other = await _lead(db, suffix="09b", consent=False, opted_out=False)
            assert await may_send_automated(other, "email", db) is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_who_never_opted_out_is_unaffected() -> None:
    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="04", consent=True, opted_out=False)
            assert await may_send_automated(lead, "sms", db) is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_nurture_worker_holds_an_opted_out_lead() -> None:
    from app.models.follow_up import FollowUp, FollowUpKind, FollowUpStatus
    from app.services.followups import process_due_followups

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="05", consent=True, opted_out=True)
            db.add(
                FollowUp(
                    lead_id=lead.id,
                    visit_id=None,
                    kind=FollowUpKind.REMINDER_24H,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
                )
            )
            await db.commit()

            result = await process_due_followups(db)

            assert result["sent"] == 0
            outbound = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE c.lead_id = :lead AND m.direction = 'outbound'"
                    ),
                    {"lead": lead.id},
                )
            ).scalar_one()
            assert outbound == 0
    finally:
        await _cleanup()


# ── The orchestrator must not answer a revocation ────────────────────────


@pytest.mark.asyncio
async def test_stop_is_answered_with_one_confirmation_and_no_llm_reply() -> None:
    """The whole point, end to end.

    Before this, an inbound STOP went down the ordinary path: history assembled,
    model called, a friendly reply generated and dispatched. An automated text
    to somebody who had just revoked permission — and generated by a model, so
    nobody could predict what it would say.
    """
    from unittest.mock import patch

    from app.services.conversation import ParsedMessage, handle_inbound_message

    called: list[str] = []

    async def _must_not_run(**kwargs: object) -> object:  # pragma: no cover
        called.append("llm")
        raise AssertionError("the model was asked to answer an opt-out")

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="06", consent=True, opted_out=False)

            with patch("app.services.conversation.generate_reply", _must_not_run):
                result = await handle_inbound_message(
                    ParsedMessage(
                        channel="sms",
                        external_id="optout-e2e-1",
                        from_identifier=lead.phone,
                        from_name=None,
                        content="STOP",
                    ),
                    db,
                )

            assert called == []
            assert result["status"] == "opted_out"

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT opted_out_at, opted_out_channel, opted_out_keyword "
                        "FROM leads WHERE phone = :p"
                    ),
                    {"p": f"{MARK}06"},
                )
            ).mappings().one()
            assert row["opted_out_at"] is not None
            assert row["opted_out_channel"] == "sms"
            assert row["opted_out_keyword"] == "stop"

            outbound = (
                await db.execute(
                    text(
                        "SELECT m.content FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "JOIN leads l ON l.id = c.lead_id "
                        "WHERE l.phone = :p AND m.direction = 'outbound'"
                    ),
                    {"p": f"{MARK}06"},
                )
            ).scalars().all()
            # Exactly one, and it is the confirmation CTIA requires — not a
            # model-authored message, and not two.
            assert len(outbound) == 1
            assert "unsubscribed" in outbound[0].lower()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_start_brings_them_back() -> None:
    from unittest.mock import patch

    from app.services.conversation import ParsedMessage, handle_inbound_message

    async def _must_not_run(**kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("the model was asked to answer an opt-in")

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="07", consent=True, opted_out=True)
            assert await may_send_automated(lead, "sms", db) is False

            with patch("app.services.conversation.generate_reply", _must_not_run):
                result = await handle_inbound_message(
                    ParsedMessage(
                        channel="sms",
                        external_id="optout-e2e-2",
                        from_identifier=lead.phone,
                        from_name=None,
                        content="START",
                    ),
                    db,
                )
            assert result["status"] == "opted_in"

            await db.refresh(lead)
            assert lead.opted_out_at is None
            assert await may_send_automated(lead, "sms", db) is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_ordinary_message_after_opting_out_gets_no_ai_reply() -> None:
    """The revocation used to last exactly one turn.

    The interception catches the message that CONTAINS the stop word. Nothing
    caught the next one: the lead texted STOP, got the confirmation, then wrote
    anything at all the following day and the model answered with a full
    automated reply. Their message must still be STORED — a person answers it
    — but nothing may be generated or sent.
    """
    from unittest.mock import patch

    from app.services.conversation import ParsedMessage, handle_inbound_message

    async def _must_not_run(**kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("the model answered a lead who had opted out")

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="20", consent=True, opted_out=True)

            with patch("app.services.conversation.generate_reply", _must_not_run):
                result = await handle_inbound_message(
                    ParsedMessage(
                        channel="sms",
                        external_id="optout-after-1",
                        from_identifier=lead.phone,
                        from_name=None,
                        content="Actually, what's available in Wash Park under 900k?",
                    ),
                    db,
                )
            assert result["status"] == "opted_out_no_reply"

        async with get_bypass_session_factory()() as db:
            counts = (
                await db.execute(
                    text(
                        "SELECT m.direction, count(*) FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE c.lead_id = :l GROUP BY m.direction"
                    ),
                    {"l": lead.id},
                )
            ).all()
            by_direction = {d: n for d, n in counts}
            # Their question is on file for a human; nothing went back.
            assert by_direction.get("inbound", 0) >= 1
            assert by_direction.get("outbound", 0) == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_retry_sweep_drops_messages_queued_before_the_opt_out() -> None:
    """A revocation has to reach what was already in the queue.

    The gate lived in the follow-up worker, which checks BEFORE creating the
    row — so anything already queued sailed past it and the sweep delivered it
    minutes or hours after the person said STOP.
    """
    from app.services.delivery import retry_pending_sends

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="21", consent=True, opted_out=True)
            conv_id = (
                await db.execute(
                    text(
                        "SELECT id FROM conversations WHERE lead_id = :l LIMIT 1"
                    ),
                    {"l": lead.id},
                )
            ).scalar_one()
            db.add(
                Message(
                    conversation_id=conv_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="A listing you might like!",
                    delivery_status=MessageStatus.PENDING,
                    send_attempts=1,
                    next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
            await db.commit()

            await retry_pending_sends(db)

            status = (
                await db.execute(
                    text(
                        "SELECT delivery_status FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE c.lead_id = :l AND m.direction = 'outbound'"
                    ),
                    {"l": lead.id},
                )
            ).scalar_one()
            assert status == "failed", "queued message must be dropped, not sent"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_sweep_reports_what_it_dropped() -> None:
    # "0 sent, 0 failed" while silently discarding a revoked message is the one
    # reading of a quiet sweep that is not true.
    from app.services.delivery import retry_pending_sends

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="22", consent=True, opted_out=True)
            conv_id = (
                await db.execute(
                    text("SELECT id FROM conversations WHERE lead_id = :l LIMIT 1"),
                    {"l": lead.id},
                )
            ).scalar_one()
            db.add(
                Message(
                    conversation_id=conv_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="A listing you might like!",
                    delivery_status=MessageStatus.PENDING,
                    send_attempts=1,
                    next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
            await db.commit()

            assert (await retry_pending_sends(db))["dropped"] == 1
    finally:
        await _cleanup()


def test_an_emoji_prefix_is_not_stripped_and_we_say_so() -> None:
    # The comment used to claim this strips "anything that is not a letter".
    # It strips the characters in _PUNCTUATION and no others, so an unlisted
    # emoji leaves the message unmatched. Pinned so the behaviour and the
    # documentation cannot drift apart again.
    assert opt_out_keyword("🛑 STOP", "sms") is not None  # listed
    assert opt_out_keyword("🚫stop", "sms") is None  # not listed


@pytest.mark.asyncio
async def test_start_from_a_lead_who_never_opted_out_is_just_a_message() -> None:
    """"ALTA" from an ordinary lead must not be answered with a confirmation.

    The 4b condition is `stop_word or (start_word and already_opted_out)`. Drop
    the second half and every "start", "alta" or "resume" from a normal lead
    gets "You're subscribed again" instead of an answer to what they asked —
    and the model never sees the message. Nothing tested that half.
    """
    from unittest.mock import patch

    from app.services.conversation import ParsedMessage, handle_inbound_message
    from app.services.llm import LLMResult

    async def _reply(**kwargs: object) -> LLMResult:
        return LLMResult(
            text="Happy to help — which neighbourhood?",
            provider="test",
            model="test",
            input_tokens=1,
            output_tokens=1,
        )

    try:
        async with get_session_factory()() as db:
            lead = await _lead(db, suffix="23", consent=True, opted_out=False)

            with patch("app.services.conversation.generate_reply", _reply):
                result = await handle_inbound_message(
                    ParsedMessage(
                        channel="sms",
                        external_id="startword-1",
                        from_identifier=lead.phone,
                        from_name=None,
                        content="ALTA",
                    ),
                    db,
                )
            assert result["status"] != "opted_in"

        async with get_bypass_session_factory()() as db:
            outbound = (
                await db.execute(
                    text(
                        "SELECT m.content FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE c.lead_id = :l AND m.direction = 'outbound'"
                    ),
                    {"l": lead.id},
                )
            ).scalars().all()
            assert all("suscribi" not in c.lower() for c in outbound), outbound
            assert all("subscribed again" not in c.lower() for c in outbound), outbound
    finally:
        await _cleanup()
