"""Somebody fills the website form and hears back.

Measured in production on 2026-09-19, not imagined. A real person submitted the
form on denverhomestory.com. The lead was written, the agency got its notice by
email AND by Telegram, the panel showed the row — and the person who had just
read "We'll call you back within a few hours" received nothing at all. The only
lead-facing mail on that route is `send_calculator_breakdown`, and it needs a
`calculator_snapshot` that somebody who never opened the calculator does not
have. On a funnel with zero form submissions in ninety days, the first person to
bother writing got silence.

The fix routes the form's own sentence through `handle_inbound_message`, the
same channel-agnostic pipeline that answers an email — so the reply is
generated, screened, footed and threaded by code that already works, and the
classifier finally reads the chip the way `ConsultForm.tsx` always claimed it
did.

What these tests are actually defending, in order of what would hurt most:

* **One lead, not two.** The pipeline does its own upsert. If it matches on the
  wrong column the agency gets two rows for one person, two score histories and
  half a conversation each — worse than the silence this replaces.
* **One notice.** The capture already told her. A second arriving a second
  later about the same person is not twice the signal.
* **Nothing at all when the breakdown is already writing.**
* **Silence for anyone who opted out**, on the lane most likely to forget it.

The LLM is patched, never called: these assert the wiring, and a test that
depended on what a model said would be asserting the model.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import Conversation, Lead, Message
from app.models.lead import LeadIntent
from app.models.message import MessageDirection
from app.services.tenant_context import org_scope

ORG = 1
MARK = "%@form.test"


@pytest.fixture
def database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("POSTAL_ADDRESS", "123 Test Ave Ste 1, Denver, CO 80200")
    monkeypatch.setenv("CONTENT_CTA_URL", "https://example.test")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_limiter() -> None:
    """The capture route is rate limited per IP, and every test here is one IP.

    Without this the fifth submission in the file gets a 429 — and a test that
    never asserted the status code went green on a request the route refused to
    process. `test_an_opted_out_person_hears_nothing` was passing that way:
    nobody was emailed because nobody was captured.
    """
    from app.api.v1.public import reset_rate_limits

    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """Nothing in this file may reach the realtor.

    On 2026-09-19 her address was repointed in PRODUCTION to keep a rehearsal
    away from her. A probe address left behind here is a real notice that never
    arrives, so it is put back either way.
    """
    from app.models.agent_settings import AgentSettings

    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            created = row is None
            if created:
                row = AgentSettings(org_id=ORG)
                db.add(row)
            previous = row.booking_contact_email
            row.booking_contact_email = "form-probe@example.com"
            await db.commit()
    yield
    with org_scope(ORG):
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
    from sqlalchemy import text

    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE lead_id IN "
                "(SELECT id FROM leads WHERE email LIKE :m))"
            ),
            {"m": MARK},
        )
        for stmt in (
            "DELETE FROM conversations WHERE lead_id IN (SELECT id FROM leads WHERE email LIKE :m)",
            "DELETE FROM lead_events WHERE lead_id IN (SELECT id FROM leads WHERE email LIKE :m)",
            "DELETE FROM listing_requests WHERE lead_id IN (SELECT id FROM leads WHERE email LIKE :m)",
            "DELETE FROM leads WHERE email LIKE :m",
        ):
            await db.execute(text(stmt), {"m": MARK})
        await db.commit()


def _sender() -> AsyncMock:
    """A provider double that answers with a DIFFERENT id every time.

    `messages.external_id` is UNIQUE, which is what makes webhook retries
    idempotent. A mock with a constant `return_value` therefore blows up on the
    second send of a turn with an IntegrityError that looks like a bug in the
    code under test and is not: Resend returns a fresh id per message.
    """
    seen = {"n": 0}

    async def _send(**_kwargs: object) -> dict[str, object]:
        seen["n"] += 1
        return {"id": f"resend.{uuid.uuid4().hex[:8]}.{seen['n']}", "simulated": False}

    return AsyncMock(side_effect=_send)


def _senders(sender: AsyncMock):
    """Every binding of `send_email` this route can reach. There are three.

    `conversation.py` and `listing_requests.py` import it lazily inside the
    function, so patching `app.services.email.send_email` reaches them.
    `lead_notify.py` and `calculator_email.py` bind the name at module load,
    so it does not — and each one was found the same way, by an assertion
    coming back with an empty list on a send that had plainly happened.

    That is how a test asserting "she is told once" passes while asserting
    nothing at all, so all three are listed here rather than discovered one at
    a time.
    """
    return (
        patch("app.services.email.send_email", new=sender),
        patch("app.services.lead_notify.send_email", new=sender),
        patch("app.services.calculator_email.send_email", new=sender),
    )


def _patches(intent: str = "buy", reply: str = "Hi Ender — two quick questions."):
    """The classifier and the writer, both pinned. Returns the context managers."""
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.llm import LLMResult

    result = IntentResult(
        intent=intent,  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(),
    )
    written = LLMResult(
        text=reply, provider="minimax", model="MiniMax-M3",
        input_tokens=10, output_tokens=10,
    )
    return (
        patch("app.services.conversation.classify_intent", AsyncMock(return_value=result)),
        patch("app.services.conversation.generate_reply", AsyncMock(return_value=written)),
    )


async def _submit(client: AsyncClient, email: str, message: str = "I'm looking to buy.", **extra):
    body = {"name": "Probe", "email": email, "message": message, **extra}
    return await client.post("/api/v1/public/leads", json=body)


# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_person_who_filled_the_form_hears_back(
    database_url: str, agency_mailbox: None
) -> None:
    """The whole point: a reply reaches the address they typed."""
    email = f"hears+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
        assert resp.status_code == 202, resp.text

        to_the_lead = [
            c for c in sender.await_args_list if c.kwargs.get("to") == email
        ]
        assert len(to_the_lead) == 1, "exactly one reply, and it exists at all"
        body = to_the_lead[0].kwargs["body_text"]
        # The compliant footer rides along, because this is automated
        # commercial email to somebody who is not talking to us yet.
        assert "Unsubscribe here" in body or "unsubscribe" in body.lower(), body
        assert "123 Test Ave" in body, "the postal address has to be in it"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_person_is_one_lead(database_url: str, agency_mailbox: None) -> None:
    """The pipeline runs its own upsert. If it misses, she gets two rows.

    Asserted with a phone present as well as absent, because the lookup is by
    the `phone` column — which for an email lead holds the address — and the
    two shapes take different branches.
    """
    for extra in ({}, {"phone": "+17205551234"}):
        email = f"one+{uuid.uuid4().hex[:8]}@form.test"
        sender = _sender()
        classify, write = _patches()
        try:
            direct, notices, breakdown = _senders(sender)
            with classify, write, direct, notices, breakdown:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await _submit(client, email, **extra)
            assert resp.status_code == 202, resp.text

            async with get_bypass_session_factory()() as db:
                count = (
                    await db.execute(
                        select(func.count()).select_from(Lead).where(Lead.email == email)
                    )
                ).scalar_one()
            assert count == 1, f"{extra or 'no phone'}: {count} leads for one person"
        finally:
            await _cleanup()


@pytest.mark.asyncio
async def test_the_agency_is_told_once(database_url: str, agency_mailbox: None) -> None:
    """Capture already told her. The pipeline must not tell her again."""
    email = f"once+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
                assert resp.status_code == 202, resp.text

        to_agency = [
            c for c in sender.await_args_list
            if c.kwargs.get("to") == "form-probe@example.com"
        ]
        assert len(to_agency) == 1, [c.kwargs.get("subject") for c in to_agency]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_chip_finally_fills_the_intent(
    database_url: str, agency_mailbox: None
) -> None:
    """`ConsultForm.tsx` says the classifier reads the chip. It did not.

    The form wrote to a `web` conversation the pipeline never saw, so every
    website lead arrived with `intent` empty and scored zero on it. This is the
    assertion that the comment is now true.
    """
    email = f"intent+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches(intent="buy")
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
                assert resp.status_code == 202, resp.text

        async with get_bypass_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.email == email))
            ).scalar_one()
        assert lead.intent == LeadIntent.BUY, lead.intent
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_inbox_row_is_not_taken_away(
    database_url: str, agency_mailbox: None
) -> None:
    """Two conversations is the correct shape, not duplication.

    The `web` one is what the Inbox shows and what analytics joins on; the
    `email` one is the thread a reply comes back to. Losing the first would
    take this lead out of the panel.
    """
    email = f"inbox+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
                assert resp.status_code == 202, resp.text

        async with get_bypass_session_factory()() as db:
            lead_id = (
                await db.execute(select(Lead.id).where(Lead.email == email))
            ).scalar_one()
            channels = (
                await db.execute(
                    select(Conversation.channel).where(Conversation.lead_id == lead_id)
                )
            ).scalars().all()
            inbound = (
                await db.execute(
                    select(func.count())
                    .select_from(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.lead_id == lead_id,
                        Message.direction == MessageDirection.INBOUND,
                    )
                )
            ).scalar_one()
        assert "web" in channels, channels
        assert "email" in channels, channels
        # One per conversation: the Inbox summary and the raw sentence Clara
        # answered. Not the same string, and neither is a copy of the other.
        assert inbound == 2, inbound
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_calculator_lead_is_not_written_to_twice(
    database_url: str, agency_mailbox: None
) -> None:
    """They already get their own numbers back. Two emails from one button is
    worse than one."""
    email = f"calc+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    # The shape the route actually validates: flat, and `credit` is a word.
    # The first version of this test sent `{"inputs": {...}}` with a numeric
    # credit score, the snapshot came back None, and the test SKIPPED itself —
    # a green run that checked nothing.
    calculator = {"rent": 2400, "savings": 60000, "credit": "good", "lang": "en"}
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email, calculator=calculator)
                assert resp.status_code == 202, resp.text

        async with get_bypass_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.email == email))
            ).scalar_one()
        assert lead.calculator_snapshot is not None, "the premise of this test"
        replies = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        # Exactly one: the breakdown. Clara stands down because the visitor is
        # already being written to, and two emails from one button press is
        # worse than one.
        assert len(replies) == 1, [c.kwargs.get("subject") for c in replies]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opted_out_person_hears_nothing(
    database_url: str, agency_mailbox: None
) -> None:
    """The newest lane is the one most likely to forget the oldest rule."""
    from datetime import UTC, datetime

    email = f"stop+{uuid.uuid4().hex[:8]}@form.test"
    async with get_bypass_session_factory()() as db:
        db.add(
            Lead(
                org_id=ORG,
                phone=email,
                email=email,
                name="Probe",
                opted_out_at=datetime.now(UTC),
                opted_out_keyword="STOP",
            )
        )
        await db.commit()

    sender = _sender()
    classify, write = _patches()
    try:
        direct, notices, breakdown = _senders(sender)
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
                assert resp.status_code == 202, resp.text

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert to_the_lead == [], [c.kwargs.get("subject") for c in to_the_lead]
    finally:
        await _cleanup()


def test_the_name_is_a_fact_or_a_stated_absence() -> None:
    """The model never sees the lead row, only the message history.

    The first version of this note said "greet them by name if you have it"
    and passed no name. In production, on the very first real send, a lead
    called Angel Belloso was answered with "Thanks for reaching out, Sarah!".

    An instruction to use a fact the model does not hold is an instruction to
    invent one, so the name goes in when there is one and its absence is
    spelled out when there is not.
    """
    from app.services.conversation import _form_first_contact_note

    named = _form_first_contact_note("Angel Belloso")
    assert "Angel" in named
    assert "por ningUn otro" in named, "using another name has to be ruled out"

    anonymous = _form_first_contact_note(None)
    assert "NO SABES SU NOMBRE" in anonymous
    assert "NO te lo inventes" in anonymous
    # And nothing in the anonymous version invites a greeting it cannot fill.
    assert "Se llama" not in anonymous

    for blank in ("", "   "):
        assert "NO SABES SU NOMBRE" in _form_first_contact_note(blank), repr(blank)


def test_the_note_asks_and_does_not_lecture() -> None:
    """The steering, not the model's output.

    A form hands Clara three words. A model given three words and no
    instruction writes a paragraph about the market, which is the failure
    `_options_coming_note` already exists to prevent on the other lane.
    """
    from app.services.conversation import _form_first_contact_note

    note = _form_first_contact_note("Probe").lower()
    assert "formulario" in note
    assert "tres preguntas" in note, "the cap on questions has to be stated"
    for forbidden in ("no enumeres propiedades", "no inventes direcciones"):
        assert forbidden in note, forbidden
    assert "no preguntes nada que ya te haya dicho" in note


@pytest.mark.asyncio
async def test_clara_is_told_this_came_from_the_form(
    database_url: str, agency_mailbox: None
) -> None:
    """The steering reaches the model, not just the module.

    Without this, removing the one `elif` that injects the note breaks nothing
    in the suite: every other test here passes on a reply the model was free to
    invent. The prompt is the deliverable on this lane — a form hands Clara
    three words, and three words with no instruction produce a paragraph about
    the market.
    """
    from app.services.llm import LLMResult

    email = f"note+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    written = LLMResult(
        text="Hi — two quick questions.", provider="minimax", model="MiniMax-M3",
        input_tokens=10, output_tokens=10,
    )
    writer = AsyncMock(return_value=written)
    classify, _unused = _patches()
    direct, notices, breakdown = _senders(sender)
    try:
        with classify, patch(
            "app.services.conversation.generate_reply", new=writer
        ), direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
        assert resp.status_code == 202, resp.text

        writer.assert_awaited()
        system = writer.await_args.kwargs["system"]
        assert "FORMULARIO DE LA WEB" in system, system[-400:]
        assert "TRES preguntas" in system
        # The name has to REACH the prompt, not merely be formattable into it.
        # Testing the note function alone left this hole: passing `None` instead
        # of `lead.name` kept every other test green, and that is the exact bug
        # that answered a lead called Angel Belloso with "Thanks for reaching
        # out, Sarah!" on the first real send.
        assert "Se llama Probe" in system, system[-400:]
        assert "NO SABES SU NOMBRE" not in system
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_double_submit_is_answered_once(
    database_url: str, agency_mailbox: None
) -> None:
    """Somebody presses the button twice, or the browser retries.

    Capture already filters that into `status == "duplicate"`, and this lane
    sits inside the `"ok"` branch for exactly that reason. Asserted here
    because the guard is one word in a condition and its absence would mail the
    same person twice within a second.
    """
    email = f"twice+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    direct, notices, breakdown = _senders(sender)
    try:
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await _submit(client, email)
                second = await _submit(client, email)
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert len(to_the_lead) == 1, [c.kwargs.get("subject") for c in to_the_lead]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_subject_is_in_the_language_they_wrote_in(
    database_url: str, agency_mailbox: None
) -> None:
    """A form carries no subject, so the pipeline's fallback becomes the norm.

    That fallback was the literal string "Tu consulta" for everybody — Spanish
    on a reply whose body the language steering had just pushed into English.
    Rare enough to stay wrong while only email leads reached it; the first
    thing an English speaker sees now that the form does.
    """
    email = f"subj+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches()
    direct, notices, breakdown = _senders(sender)
    try:
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email, message="I'm looking to buy.")
        assert resp.status_code == 202, resp.text

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert to_the_lead, "no reply to assert a subject on"
        subject = to_the_lead[0].kwargs["subject"]
        assert "Tu consulta" not in subject, subject
        assert subject.strip(), subject
    finally:
        await _cleanup()


# ──────────────────────────────────────────────────────────────────────────
# The HTML half of a reply
#
# From a real inbox on 2026-09-19. Clara's answer ended on the compliant
# footer printed the only way plain text can print a link:
#
#     Don't want these emails? Unsubscribe here:
#     https://www.denverhomestory.com/api/v1/public/unsubscribe/MTI3NQ.tS2yN…
#
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reply_carries_an_html_half_with_the_link_behind_a_word(
    database_url: str, agency_mailbox: None
) -> None:
    """Both halves, and the token stops being printed at the reader."""
    from app.services.listing_requests import strip_tags

    email = f"html+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches(reply="Hi Paco — which areas, and what budget?")
    direct, notices, breakdown = _senders(sender)
    try:
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
        assert resp.status_code == 202, resp.text

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert to_the_lead, "no reply to inspect"
        sent = to_the_lead[0].kwargs

        # The text half is untouched: it is the message of record.
        assert "Unsubscribe here" in sent["body_text"]
        assert "/api/v1/public/unsubscribe/" in sent["body_text"]

        html = sent["body_html"]
        assert html and html.startswith("<!doctype html>")
        assert ">Unsubscribe</a>" in html
        assert "Hi Paco" in strip_tags(html), "the reply itself has to be in it"
        # The law's own words stay readable; only the URL hides.
        visible = strip_tags(html)
        assert "123 Test Ave" in visible
        assert "/api/v1/public/unsubscribe/" not in visible
    finally:
        await _cleanup()


def test_what_the_model_writes_cannot_become_markup() -> None:
    """The body is model output on one lane and a realtor's typing on the other.

    Neither is markup. An ampersand in a brokerage name is not an attack, it is
    Tuesday, and a `<` from either source must arrive as a `<`.
    """
    from app.services.email_html import document, paragraphs

    html = document(paragraphs("Ruiz & Co <script>alert(1)</script>\n\nSecond line."))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Ruiz &amp; Co" in html
    assert html.count("<p ") == 2, "a blank line is a paragraph break"


def test_only_http_links_become_links() -> None:
    """Inert rubbish in plain text, a clickable link once rendered."""
    from app.services.email_html import paragraphs

    assert '<a href="https://x.test/tour"' in paragraphs("See https://x.test/tour")
    for hostile in ("javascript:alert(1)", "data:text/html;base64,PHM+"):
        out = paragraphs(f"Look at {hostile} now")
        assert "<a " not in out, out


# ──────────────────────────────────────────────────────────────────────────
# The reply budget
#
# Ender, watching a real thread run three turns with no end in sight: "no se
# debe formar un peloteo de emails entre Clara y el prospecto — uno pidiendo
# más info y el siguiente ya debe venir con un link para que coloque la hora en
# que prefiere ser contactado, y la respuesta se le debe pasar a Natalia."
# ──────────────────────────────────────────────────────────────────────────


def test_the_budget_is_two_and_the_holding_line_is_daily() -> None:
    """The two numbers, named, so changing one is a deliberate act."""
    from datetime import timedelta

    from app.services.conversation import HOLDING_LINE_EVERY, MAX_AUTOMATED_REPLIES

    assert MAX_AUTOMATED_REPLIES == 2
    assert HOLDING_LINE_EVERY == timedelta(days=1)


def test_the_holding_line_is_fixed_and_bilingual() -> None:
    """Fixed, not generated — a generated answer is a reply, and a reply
    invites another, which is the ping-pong this exists to end."""
    from app.services.conversation import _holding_line

    en, es = _holding_line("en"), _holding_line("es")
    assert "Natalia" in en and "Natalia" in es
    assert en != es
    # Twice in a row is the same sentence: nothing here varies per call.
    assert _holding_line("en") == en


def test_the_last_reply_is_told_not_to_write_the_address() -> None:
    """A model asked to reproduce a signed token reproduces it wrong."""
    from app.services.conversation import _last_automated_reply_note

    with_link = _last_automated_reply_note("https://x.test/options/tok")
    assert "ÚLTIMA RESPUESTA" in with_link
    assert "NO inventes ninguna dirección" in with_link
    # And it must not ask the model to close by requesting a time either: the
    # code appends that line itself, so a model that also writes one makes the
    # email ask twice.
    assert "NO cierres pidiéndole" in with_link
    without = _last_automated_reply_note(None)
    assert "ÚLTIMA RESPUESTA" in without
    # With no link there is nothing to invite them to, so it must not ask.
    assert "enlace" not in without


def test_the_invitation_has_a_sentence_and_its_words() -> None:
    """The text half prints the address; the HTML half hides it behind words."""
    from app.services.conversation import _callback_invite
    from app.services.email_html import link_paragraph

    for lang in ("en", "es"):
        sentence, words = _callback_invite(lang)
        assert sentence and words and sentence != words
    sentence, words = _callback_invite("en")
    html = link_paragraph(sentence, "https://x.test/options/tok?a=1&b=2", words)
    assert f">{words}</a>" in html
    assert "https://x.test/options/tok?a=1&amp;b=2" in html
    # The address is not ALSO printed as text beside its own link.
    assert html.count("x.test") == 1


@pytest.mark.asyncio
async def test_the_second_reply_carries_the_link_and_the_third_does_not_reply(
    database_url: str, agency_mailbox: None
) -> None:
    """The whole rule, through the real capture route and the real webhook.

    Asserted end to end because the budget is counted from the database and a
    unit test of the counter would pass while the pipeline kept writing.
    """
    from app.services.conversation import _automated_replies_so_far

    email = f"budget+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    classify, write = _patches(reply="Which area, and what budget?")
    direct, notices, breakdown = _senders(sender)
    try:
        with classify, write, direct, notices, breakdown:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await _submit(client, email)
        assert resp.status_code == 202, resp.text

        async with get_bypass_session_factory()() as db:
            lead_id = (
                await db.execute(select(Lead.id).where(Lead.email == email))
            ).scalar_one()
            assert await _automated_replies_so_far(lead_id, db) == 1, (
                "the form reply is the first of the two"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_after_two_replies_the_model_is_never_called_again(
    database_url: str, agency_mailbox: None
) -> None:
    """The budget spent: a fixed sentence, a notice, and no generation at all.

    `generate_reply` is asserted NOT awaited, which is the assertion that
    matters. A test that only checked the text would pass on a pipeline that
    still paid for a turn and then threw it away — and the cost of a model that
    keeps running is not only money, it is that somebody eventually ships a
    branch where its output is used.
    """
    from app.models.message import MessageSender, MessageStatus
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.tenant_context import set_org_id

    set_org_id(ORG)
    email = f"spent+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    writer = AsyncMock()
    classify, _unused = _patches()
    try:
        # A lead who has already had both replies.
        async with get_bypass_session_factory()() as db:
            lead = Lead(org_id=ORG, phone=email, email=email, name="Probe")
            db.add(lead)
            await db.flush()
            conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
            db.add(conv)
            await db.flush()
            for n in range(2):
                db.add(
                    Message(
                        org_id=ORG,
                        conversation_id=conv.id,
                        direction=MessageDirection.OUTBOUND,
                        sender=MessageSender.AGENT,
                        content=f"reply {n}",
                        delivery_status=MessageStatus.SENT,
                        internal=False,
                    )
                )
            await db.commit()
            lead_id = lead.id

        parsed = ParsedMessage(
            channel="email",
            external_id=f"third-{uuid.uuid4().hex[:8]}",
            from_identifier=email,
            from_name="Probe",
            content="Any news?",
            subject="Re: Your message",
        )
        # The APP session inside `org_scope`, not the bypass one: the pipeline
        # takes `org_id` from the RLS context, and a bypass session leaves it
        # NULL — the insert then fails and the idempotency guard reports a
        # "duplicate" that never happened. Reaching for the bypass factory
        # because it is convenient is how a test measures the wrong thing.
        from app.db.base import get_session_factory

        direct, notices, breakdown = _senders(sender)
        with classify, patch(
            "app.services.conversation.generate_reply", new=writer
        ), direct, notices, breakdown, org_scope(ORG):
            async with get_session_factory()() as db:
                result = await handle_inbound_message(parsed, db)

        assert result["status"] == "handed_over", result
        writer.assert_not_awaited()

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert len(to_the_lead) == 1, "the fixed sentence, once"
        assert "Natalia will be in touch" in to_the_lead[0].kwargs["body_text"]

        to_agency = [
            c for c in sender.await_args_list
            if c.kwargs.get("to") == "form-probe@example.com"
        ]
        assert to_agency, "she has to hear that they are waiting"
        assert "waiting for you" in to_agency[0].kwargs["subject"], to_agency[0].kwargs

        # And a fourth message the same day gets no second copy of the sentence.
        sender.reset_mock()
        parsed_again = ParsedMessage(
            channel="email",
            external_id=f"fourth-{uuid.uuid4().hex[:8]}",
            from_identifier=email,
            from_name="Probe",
            content="Hello?",
            subject="Re: Your message",
        )
        direct, notices, breakdown = _senders(sender)
        with classify, patch(
            "app.services.conversation.generate_reply", new=writer
        ), direct, notices, breakdown, org_scope(ORG):
            async with get_session_factory()() as db:
                await handle_inbound_message(parsed_again, db)

        again_to_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert again_to_lead == [], "once a day, not once a message"
        again_to_agency = [
            c for c in sender.await_args_list
            if c.kwargs.get("to") == "form-probe@example.com"
        ]
        assert again_to_agency, "but she hears about it every time"
        assert lead_id
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_asking_for_houses_still_gets_the_link_to_pick_a_time(
    database_url: str, agency_mailbox: None
) -> None:
    """Both, not one. Measured on lead 1278 in production on 2026-09-20.

    The picker used to be skipped whenever the person asked to see property, so
    the last automated reply closed with "someone from our team will be in touch
    with you shortly" — the vaguest sentence this product can produce, and the
    exact thing the link exists to replace. The shortlist takes a person and a
    day; the call is what they choose a time for. They are not rivals.

    A lead may hold ONE open request — a partial unique index on `lead_id WHERE
    status = 'open'` — so the row is the same row, and `origin` records which
    caller made it. It has to be `message`: that is the one whose notice asks
    the agency to pick. The first version of this fix opened the callback row
    first, the origin came back `callback`, and the "pick up to six" email
    silently stopped being sent.
    """
    from sqlalchemy import text as sql_text

    from app.models.message import MessageSender, MessageStatus
    from app.services._common import ParsedMessage
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.conversation import _callback_invite, handle_inbound_message
    from app.services.llm import LLMResult
    from app.services.tenant_context import set_org_id

    set_org_id(ORG)
    email = f"both+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    wants = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(wants_listings=True),
    )
    written = LLMResult(
        text="Natalia will put a shortlist together for you.",
        provider="minimax", model="MiniMax-M3", input_tokens=10, output_tokens=10,
    )
    try:
        # One reply already spent, so this inbound is the LAST one allowed.
        async with get_bypass_session_factory()() as db:
            lead = Lead(org_id=ORG, phone=email, email=email, name="Probe", zone="Wash Park")
            db.add(lead)
            await db.flush()
            conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
            db.add(conv)
            await db.flush()
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="reply one",
                    delivery_status=MessageStatus.SENT,
                    internal=False,
                )
            )
            await db.commit()
            lead_id = lead.id

        parsed = ParsedMessage(
            channel="email",
            external_id=f"houses-{uuid.uuid4().hex[:8]}",
            from_identifier=email,
            from_name="Probe",
            content="Can you show me what is for sale in Wash Park?",
            subject="Re: Your message",
        )
        from app.db.base import get_session_factory

        direct, notices, breakdown = _senders(sender)
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=wants)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=written)
        ), direct, notices, breakdown, org_scope(ORG):
            async with get_session_factory()() as db:
                await handle_inbound_message(parsed, db)

        to_the_lead = [c for c in sender.await_args_list if c.kwargs.get("to") == email]
        assert len(to_the_lead) == 1, "one reply, not one per branch"
        body = to_the_lead[0].kwargs["body_text"]
        sentence, words = _callback_invite("en")
        assert sentence in body, f"the last reply must carry the picker: {body!r}"
        # Asked for once. The code appends the invitation, so a model note that
        # also tells it to close with one produces the same request twice.
        assert body.count(sentence) == 1, body

        html = to_the_lead[0].kwargs.get("body_html") or ""
        assert f">{words}</a>" in html, "the HTML half hides it behind the words"

        async with get_bypass_session_factory()() as db:
            origins = sorted(
                r[0] for r in (
                    await db.execute(
                        sql_text(
                            "SELECT origin FROM listing_requests WHERE lead_id = :i"
                        ),
                        {"i": lead_id},
                    )
                ).all()
            )
        assert origins == ["message"], origins

        # The row is only half of it. The agency has to be ASKED to pick, and
        # that email is what the ordering bug took away while the link kept
        # working — a failure no assertion about the reply would have seen.
        to_agency = [
            c for c in sender.await_args_list
            if c.kwargs.get("to") == "form-probe@example.com"
        ]
        assert to_agency, "she has to be asked to pick the shortlist"
        assert any(
            "listings" in c.kwargs.get("subject", "") for c in to_agency
        ), [c.kwargs.get("subject") for c in to_agency]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_turn_clara_hands_over_is_never_silent(
    database_url: str, agency_mailbox: None
) -> None:
    """She promised a person would follow up. Somebody has to be told.

    Measured on lead 1279 in production (2026-09-20). The classifier read "we
    are looking for a house in DTC, garage, 2 bed, office, 2 bath, buying in 6
    months" as NOT asking for listings, so no options request was filed — and
    the reply still ended with "a member of our team will get back to you with
    options that fit what you described". Nothing reached any inbox. The lead
    sat in the panel with a promise behind it and nobody holding the promise.

    The classifier was widened too, but this is the net underneath it: a
    safeguard that only works when a model judges correctly is not a safeguard.
    So the assertion is on the turn, not on the intent.
    """
    from app.models.message import MessageSender, MessageStatus
    from app.services._common import ParsedMessage
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult
    from app.services.tenant_context import set_org_id

    set_org_id(ORG)
    email = f"handover+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()
    # Deliberately NOT asking for listings: this is the case that was silent.
    quiet = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(wants_listings=False),
    )
    written = LLMResult(
        text="Someone from the team will get back to you.",
        provider="minimax", model="MiniMax-M3", input_tokens=10, output_tokens=10,
    )
    try:
        async with get_bypass_session_factory()() as db:
            lead = Lead(org_id=ORG, phone=email, email=email, name="Probe")
            db.add(lead)
            await db.flush()
            conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
            db.add(conv)
            await db.flush()
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="reply one",
                    delivery_status=MessageStatus.SENT,
                    internal=False,
                )
            )
            await db.commit()

        parsed = ParsedMessage(
            channel="email",
            external_id=f"handover-{uuid.uuid4().hex[:8]}",
            from_identifier=email,
            from_name="Probe",
            content="We want a house in DTC, 2 bed, office, buying in 6 months.",
            subject="Re: Your message",
        )
        from app.db.base import get_session_factory

        direct, notices, breakdown = _senders(sender)
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=quiet)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=written)
        ), direct, notices, breakdown, org_scope(ORG):
            async with get_session_factory()() as db:
                await handle_inbound_message(parsed, db)

        to_agency = [
            c for c in sender.await_args_list
            if c.kwargs.get("to") == "form-probe@example.com"
        ]
        assert to_agency, "the handover turn reached nobody"
        assert any(
            "yours now" in c.kwargs.get("subject", "") for c in to_agency
        ), [c.kwargs.get("subject") for c in to_agency]
        # It says what she has to know: that Clara has stopped.
        assert any(
            "last automated reply" in c.kwargs.get("body_text", "")
            for c in to_agency
        ), [c.kwargs.get("body_text", "")[:120] for c in to_agency]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_what_they_asked_for_survives_the_turn(
    database_url: str, agency_mailbox: None
) -> None:
    """The wiring, not the function. Measured on lead 1279, 2026-09-20.

    `storable_count` can be perfect and this can still be broken: the turn has
    to actually assign the four fields, and a test of the helper would pass
    against a pipeline that never called it. That is the mistake this file has
    already made twice — once with the reader's name, once with the footer.

    The second half is the one worth having. Somebody correcting themselves
    ("no, three bedrooms") must end up with three: a first guess that cannot be
    corrected sticks to the lead for ever and quietly matches the wrong houses.
    """
    from app.services._common import ParsedMessage
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult
    from app.services.tenant_context import set_org_id

    set_org_id(ORG)
    email = f"asked+{uuid.uuid4().hex[:8]}@form.test"
    sender = _sender()

    def _said(**entities: object) -> IntentResult:
        return IntentResult(
            intent="buy",  # type: ignore[arg-type]
            confidence=0.95,
            entities=IntentEntities(**entities),  # type: ignore[arg-type]
        )

    written = LLMResult(
        text="Noted.", provider="minimax", model="MiniMax-M3",
        input_tokens=10, output_tokens=10,
    )

    async def _turn(result: IntentResult, content: str) -> None:
        from app.db.base import get_session_factory

        parsed = ParsedMessage(
            channel="email",
            external_id=f"asked-{uuid.uuid4().hex[:8]}",
            from_identifier=email,
            from_name="Probe",
            content=content,
            subject="Re: Your message",
        )
        direct, notices, breakdown = _senders(sender)
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=result)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=written)
        ), direct, notices, breakdown, org_scope(ORG):
            async with get_session_factory()() as db:
                await handle_inbound_message(parsed, db)

    try:
        await _turn(
            _said(
                zone="DTC", beds_min=2, baths_min=2, garage_min=2,
                wants_office=True, urgency="months",
            ),
            "We are looking a house, in DTC, garage with space for two SUV, "
            "2 bet, office, 2 bath, we want to buy in 6 month",
        )

        async with get_bypass_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.email == email))
            ).scalar_one()
            assert lead.beds_min == 2
            assert lead.baths_min == Decimal("2.0")
            assert lead.garage_min == 2
            assert lead.wants_office is True
            assert lead.zone == "DTC"

        # They correct themselves, and the correction wins.
        await _turn(_said(beds_min=3), "Actually we need three bedrooms.")

        async with get_bypass_session_factory()() as db:
            lead = (
                await db.execute(select(Lead).where(Lead.email == email))
            ).scalar_one()
            assert lead.beds_min == 3, "a count they corrected must not stick at the old one"
            # And what they did not repeat is not forgotten.
            assert lead.garage_min == 2
            assert lead.wants_office is True
    finally:
        await _cleanup()
